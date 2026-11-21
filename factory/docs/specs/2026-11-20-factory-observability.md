# Factory observability: event log and stats

Status: spec for a factory job. Date: 2026-11-20. Target: factory 0.5.0.

## Goal

The factory records workflow state (`board.json`, job folders) but no time,
tokens, or per-agent runs, and `board.json` is overwritten in place. Add an
append-only event log that only the orchestrator writes, through a deterministic
`CFG event` command. Add a `CFG stats` command that turns the log, the board,
and the job folders into efficiency metrics. Then give the tuner those numbers,
so `/factory:tune` suggestions on cost and convergence rest on measured data
instead of verdicts alone.

The existing hard rules still hold: agents talk only through files, each agent
writes only its own file, and the orchestrator is the only writer of shared
state. A logging failure must never stall, fail, or change the stage of a job.

## Behavior

### `CFG event <repo> <kind> key=value ...`

Appends one JSON line to `<repo>/.factory/events.jsonl`, creating the file if it
is missing. If `.factory/` itself is missing, it first creates it as `CFG init` does,
so the folder still ignores itself. The script stamps `ts` (UTC, `YYYY-MM-DDTHH:MM:SSZ`) and `kind`.
Callers never pass `ts`.

| kind | required keys | optional keys |
|---|---|---|
| `stage` | `job`, `stage`, `round` | `lane` |
| `agent` | `job`, `role`, `phase` (`start` or `end`), `round` | `model`, `effort`, `name`, `verdict`, `tokens`, `tool_uses`, `duration_ms` |
| `command` | `job`, `round`, `name`, `exit` | `seconds` |

- `job` matches `^\d{3}-[a-z0-9-]+$`. `stage` is one of the board stages
  (`spec`, `build`, `review`, `approval`, `arbitration`, `needs-human`,
  `merged`). `role` is a `models` role, `reviewer`, or `qa`. For a reviewer,
  `name` is the reviewer name.
- `round`, `exit`, `tokens`, `tool_uses`, `duration_ms` and `seconds` are
  written as integers. A value that does not parse as an integer is an error.
- On success it prints `ok` and exits 0. On an unknown kind, a missing required
  key, an unknown key, or a bad value, it prints one `event: ...` line per
  problem, writes nothing, and exits 1.
- Each line is written with a single `write` in append mode, so a crash cannot
  leave a partial line before a full one.

Example line:

```json
{"ts":"2026-11-20T14:03:07Z","kind":"agent","job":"004-status-json","role":"reviewer","name":"logic","phase":"end","round":2,"verdict":"PASS","tokens":41230,"tool_uses":18,"duration_ms":95400}
```

### `CFG stats <repo>`

Prints one JSON object to stdout and exits 0. It reads `.factory/board.json`,
`.factory/events.jsonl` and `.factory/jobs/*/`. When `events.jsonl` is missing or
empty, every time and token field is `null` and the board-derived fields are
still filled in, so the command works on repos that ran jobs before 0.5.0.

```json
{
  "jobs_total": 12,
  "jobs_finished": 10,
  "bad_event_lines": 0,
  "first_round_pass_rate": 0.4,
  "mean_rounds": 1.8,
  "max_rework_hits": 1,
  "auto_approve_rate": 0.5,
  "escalation_rate": 0.3,
  "triage": {"predicted": 6, "correct": 5, "promoted": 1},
  "stage_seconds": {"spec": {"total": 1800, "mean": 180}, "build": {...}, ...},
  "roles": {"builder": {"runs": 18, "tokens": 900000, "seconds": 5400}, ...},
  "reviewers": {"logic": {"runs": 18, "changes": 7, "change_rate": 0.39, "tokens": 400000, "seconds": 1700}, ...},
  "jobs": [
    {"id": "004-status-json", "lane": "full", "stage": "merged", "rounds": 2,
     "rework": 1, "wall_seconds": 2400, "tokens": 310000,
     "stage_seconds": {"spec": 200, "build": 900, "review": 1100, "approval": 200}}
  ]
}
```

Definitions:

- Finished: stage `merged` or `needs-human`. The rates use finished jobs only.
  A rate with a zero denominator is `null`.
- `first_round_pass_rate`: finished jobs whose round-1 verdicts (from board
  `history`, or `reviews` when `history` is empty) contain no `CHANGES`.
- `mean_rounds`: mean board `round` over finished jobs. `max_rework_hits`:
  finished jobs whose `rework` equals the `max_rework` setting.
- `auto_approve_rate`: finished jobs whose `decision.md` has an `auto:` line,
  out of finished jobs with a `decision.md`. `escalation_rate`: finished jobs
  whose `decision.md` (or any `decision-<N>.md`) starts with `ESCALATE`, out of
  the same set.
- `triage`: jobs with a `triage.md`. `predicted` is their count. `correct` is the
  number whose `LANE:` line matches the board `lane`. `promoted` is the number
  predicted `trivial` whose board lane is `full`.
- `stage_seconds` for one job: for each `stage` event, the time until the job's
  next `stage` event. The last stage of a job has no end and is not counted.
  The top-level `stage_seconds` sums and averages these over jobs.
- `roles` and `reviewers`: an `agent` `end` event counts one run and adds its
  `tokens` and `duration_ms / 1000` (when present). `changes` counts reviewer
  `end` events with `verdict: CHANGES`. `change_rate` is `changes / runs`.
- `wall_seconds`: last event `ts` minus first event `ts` for the job. `tokens`:
  the sum of `tokens` over the job's `agent` events.
- Lines that are not valid JSON objects with a `kind` are skipped and counted in
  `bad_event_lines`.

If `factory.yaml` fails `validate`, it prints the `validate` lines and exits 1,
as `overview` does.

### Orchestrator (`skills/run/SKILL.md`)

A new `## Events` section says that after every board write that changes a job's
`stage`, the orchestrator runs `CFG event REPO stage job=<id> stage=<stage>
round=<N>`, plus `lane=<lane>` when the board has one. Also:

- Before every agent spawn or SendMessage resume: `agent ... phase=start` with
  `role`, `round`, `model`, `effort` (as resolved), and `name` for a reviewer.
- When the agent returns: `agent ... phase=end`, with `verdict` for a reviewer,
  QA, approver (`APPROVE` or `ESCALATE`) or arbiter (`ACCEPT`, `REWORK` or
  `OWNER`). Add `tokens`, `tool_uses` and `duration_ms` when the Agent tool's
  result reports them, and leave them out otherwise. For `runtime: command`,
  leave them out (the `ts` gap covers duration).
- After each command in `round-N/commands.md` and each `merge_gate` command:
  `command ... name=<key> exit=<code> seconds=<elapsed>`, where the elapsed time
  is measured in the same Bash call (for example with `SECONDS`).
- If `CFG event` exits non-zero, tell the user its output in one line and keep
  going. Never retry it, and never let it change the job.

`## Rules` adds `events.jsonl` to the list of files the orchestrator writes.

### Tuner (`agents/tuner.md`, `skills/tune/SKILL.md`)

- `/factory:tune` passes the tuner the `CFG` command line and REPO. The tuner
  first runs `CFG stats REPO` against the real repo, not the scratch checkout,
  because the record lives in REPO's `.factory/` folder. It cites the numbers as
  evidence.
- `cost` items use `roles` and `reviewers` tokens and seconds when they are
  non-null. A `cost` item that names a reviewer cites its `runs`, `changes` and
  `tokens`.
- `convergence` items cite `first_round_pass_rate`, `mean_rounds` and
  `max_rework_hits`.
- A new kind, `latency`: a stage whose mean `stage_seconds` is the largest
  share of job wall time, with a suggestion to shorten it (for example a
  narrower `merge_gate`, `paths` on a slow reviewer, or a lane).
- A new kind, `triage`: `promoted` at 2 or more, or `correct / predicted` under
  0.8, with a suggestion to change `lanes.trivial.paths` or `models.triage`.
- The first line of `tune.md` also states whether event data was present.

### Overview

`/factory:overview` adds one more line after the board counts:
`first-round pass <rate>, mean rounds <n>, auto-approve <rate>`, taken from `CFG
stats`. If a rate is `null` it shows `-`.

## Design

- `skills/run/scripts/factory_config.py`: add `event` and `stats` subparsers and
  the functions `append_event(repo, kind, pairs) -> list[str]` (errors) and
  `stats(repo, cfg) -> dict`. Keep them pure apart from file IO, as the existing
  helpers are. Add an `EVENT_KINDS` table next to the other constants. Do not
  add dependencies.
- `skills/run/schema.md`: add `event` and `stats` to the command table, plus an
  `## Events` section with the kinds table and a pointer to `CFG stats`.
- `skills/run/SKILL.md`: the `## Events` section, the `## Rules` line, and the
  `## overview` line.
- `agents/tuner.md` and `skills/tune/SKILL.md`: as in Behavior.
- `README.md`: one paragraph under the commands table about `events.jsonl` and
  `CFG stats`.
- `.claude-plugin/plugin.json` and the repo root `.claude-plugin/marketplace.json`:
  set the factory version to `0.5.0`.
- Tests in `factory/tests/`, using the existing `conftest.py` helpers
  (`make_repo`, `write_board`, `run_cli`).

## Acceptance criteria

- [ ] AC1: `event` with a valid `stage` call appends exactly one line, which
  parses as JSON with `ts` in `YYYY-MM-DDTHH:MM:SSZ` form, the given keys, and
  `round` as an int. It prints `ok` and exits 0. (test: `factory/tests/test_events.py`)
- [ ] AC2: `event` creates `.factory/events.jsonl` when it is missing, and a
  second call appends without changing the first line. (test: `factory/tests/test_events.py`)
- [ ] AC3: `event` with an unknown kind, a missing required key, an unknown key,
  a bad `job` id, a bad `stage`, a bad `phase`, or a non-integer `tokens` exits
  1, prints an `event: ` line that names the problem, and leaves the file
  byte-for-byte unchanged. (test: `factory/tests/test_events.py`)
- [ ] AC4: `event` rejects a caller-supplied `ts`. (test: `factory/tests/test_events.py`)
- [ ] AC5: `stats` with no `events.jsonl` returns board-derived fields (for a
  fixture board) and `null` for every time and token field, and exits 0. (test: `factory/tests/test_stats.py`)
- [ ] AC6: `stats` on a fixture with known events gives the expected per-job
  `stage_seconds`, `wall_seconds`, `tokens`, and the top-level `roles` and
  `reviewers` totals, including `change_rate`. The last stage of each job is not
  counted. (test: `factory/tests/test_stats.py`)
- [ ] AC7: `first_round_pass_rate`, `mean_rounds`, `max_rework_hits`,
  `auto_approve_rate`, `escalation_rate` and `triage` match hand-computed values
  for a fixture with merged, needs-human and in-flight jobs. In-flight jobs are
  excluded from the rates, and a zero denominator gives `null`. (test: `factory/tests/test_stats.py`)
- [ ] AC8: `stats` skips malformed lines and counts them in `bad_event_lines`.
  (test: `factory/tests/test_stats.py`)
- [ ] AC9: `stats` on an invalid `factory.yaml` prints the `validate` lines and
  exits 1. (test: `factory/tests/test_stats.py`)
- [ ] AC10: `schema.md` lists `event` and `stats` in its command table, and
  `SKILL.md` has an `## Events` section that names every call site in Behavior
  and the "warn and continue" rule. (test: `factory/tests/test_docs.py`, a grep for each)
- [ ] AC11: `tuner.md` names the `latency` and `triage` kinds and tells the tuner
  to run `CFG stats` before anything else. (test: `factory/tests/test_docs.py`)
- [ ] AC12: `plugin.json` and `marketplace.json` both say `0.5.0`. (test: `factory/tests/test_docs.py`)
- [ ] `uv run --with pytest --with pyyaml pytest factory/tests -q` passes from the repo root.

## Out of scope

- Dashboard changes, such as time in stage on the cards. That is a follow-up
  once the data exists.
- Agents writing events themselves. Only the orchestrator writes the log.
- Rotating, compacting or committing `events.jsonl`. The owner decides whether
  to gitignore it.
- Backfilling events for jobs that ran before 0.5.0.
- Dollar cost. Tokens only; prices change and live outside the repo.
- Exporting to external tools (OpenTelemetry, trackers). The tracker mirror
  design (`2026-11-03-tracker-mirror-design.md`) is a separate effort.
