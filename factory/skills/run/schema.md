# factory.yaml reference

`factory/factory.yaml` holds everything about a repo's factory that is not the
loop itself. `/factory:setup` writes it; the owner edits it to override; setup
may propose a rewrite later. Reviewer and QA checklists are not here: each
reviewer is a repo agent at `.claude/agents/factory-review-<name>.md`, and QA is
the agent `qa.agent` names.

Skills never parse this file themselves. They call
`scripts/factory_config.py` (run with `uv run --script`):

| command | prints |
|---|---|
| `validate <repo>` | `ok` and exit 0, or one `factory.yaml: ...` line per problem and exit 1 |
| `get <repo> <dotted.key>` | the value as JSON, defaults applied; `null` when missing |
| `select <repo> <base> <head>` | `{"run": [...], "skipped": [...]}` for the round |
| `lane <repo> <base> <head>` | `{"lane": "trivial"\|"full", "why": "...", "skip": [...]}` for the diff (`skip` only for `trivial`) |
| `escalate-hit <repo> <base> <head>` | `{"hit": [{"when", "files"}], "unchecked": [...]}`: `escalate` entries whose `paths` match the diff (plus the thin-tests rule), and the plain-string entries only the approver can judge |
| `builder-done <worktree> <before_sha> <build_md> <round>` | `done` and exit 0, or the reason and exit 1 |
| `migration-check <repo> [--loop-file <path>]` | `ok` and exit 0, or one line per blocker (an active loop in the given state file, a dirty tree, a job in flight) and exit 1 |

## Keys

Any key not in this table is an error.

| key | type | default | meaning |
|---|---|---|---|
| `version` | int | required, `1` | schema version |
| `base` | string | required | branch jobs start from and merge into |
| `max_rework` | int | `2` | builder resumes per job before arbitration |
| `max_arbiter_rework` | int | `1` | automatic arbiter `REWORK`s per job |
| `worktrees` | string | `../<repo-dir>-factory` | job worktrees go in `<worktrees>/<job-id>` |
| `context` | list of paths | `[]` | what spec-writer, builder, reviewers, approver and arbiter read first |
| `rules` | path, optional `#Heading` | none | the repo's hard rules (for example `.mex/AGENTS.md#Non-Negotiables`) |
| `tests` | `none`, `thin` or `ok` | `ok` if `commands.test` exists, else `none` | state of the test suite; setup sets it from the survey (`thin`: the command runs but few or no tests exercise the code). Anything but `ok` tells the approver and arbiter to escalate changes they cannot check |
| `commands` | map name to shell command | required, non-empty unless `tests: none` | open set; the builder runs every one and all must pass. Name the test command `test` |
| `merge_gate` | list of `commands` keys | `[test]` if `test` exists, else `[]` | what the orchestrator reruns on `base` after a merge |
| `scout` | map | `{}` | `todo_paths` (list), `docs` (list), `checks` (list of one-line foundations checks) |
| `builder` | map | `{runtime: claude, resume: session}` | see Builder |
| `reviewers` | list | required, non-empty | see Reviewers |
| `qa` | `null` or map | `null` | `agent` (repo agent name), optional `paths` |
| `escalate` | list of strings or `{when, paths}` | `[]` | the approver escalates on any of these, even when reviews pass. A string is prose only the approver can judge. An object adds `paths` (globs, same rules as Reviewers): when the diff matches none of them and the other auto-approve conditions hold, the orchestrator approves without the approver. See Escalate |
| `lanes` | map | `{}` | optional fast lanes. Only `trivial` exists. See Lanes |
| `related` | list of `{path, contract}` | `[]` | sibling repos; reviewers named `contract*` get them in their prompt |
| `models` | map role to `<model> [effort]` | `{}` | roles: `spec-writer`, `builder`, `reviewers`, `approver`, `arbiter`, `scout`, `setup-surveyor`, `foundations-scout`, `tuner`, `triage`; model is `opus`, `sonnet`, `haiku`, `fable` or `inherit`; effort is `low`, `medium`, `high`, `xhigh` or `max` |

## Builder

- `runtime: claude` spawns `factory:builder` and resumes it with SendMessage
  each round.
- `runtime: command` runs `builder.command` with Bash in the job worktree. It
  must contain `{prompt_file}`; it may also use `{session}` and `{out_prefix}`.
  - `{prompt_file}` is `jobs/<id>/builder-prompt-<N>.md` (absolute path).
  - `{session}` is `factory-<job-id>` with `resume: session` (the same every
    round, so the runner can resume), or `factory-<job-id>-r<N>` with
    `resume: fresh`.
  - `{out_prefix}` is `jobs/<id>/builder-r<N>` (absolute path), where the runner
    may write logs.
  - A run is done only when `builder-done` passes: a new commit on the branch
    and a `## Round <N>` line in `build.md`.

## Reviewers

Each entry:

| field | meaning |
|---|---|
| `name` | matches `^[a-z][a-z0-9-]*$`, unique, not `qa`; the agent is `.claude/agents/factory-review-<name>.md` and writes `round-N/review-<name>.md` |
| `why` | one line naming what in this repo makes the reviewer worth running |
| `paths` | optional non-empty list of globs; without it the reviewer runs every round |
| `model` | optional `<model> [effort]`, overrides `models.reviewers` |

A reviewer with `paths` runs only when a file in
`git diff --name-only <base>...<head>` matches one of them. QA follows the same
rule with `qa.paths`, runs in the same round, and writes `round-N/review-qa.md`.

Glob rules (gitignore style):

- a pattern matches a changed file if it matches the file's path or any
  directory above it, so `web` and `web/` both cover everything under `web/`;
- a pattern with no `/` (other than a trailing one) matches at any depth:
  `*.py` matches `src/a.py`, `web` matches `src/web/a.js`;
- a pattern with a `/` is anchored at the repo root: `src/greet` matches
  `src/greet/cli.py` but not `lib/src/greet/cli.py`;
- `**/` matches zero or more directories (`src/**/test_*.py` matches
  `src/test_a.py`); `**` elsewhere matches any characters, including `/`;
- `*` matches any characters except `/`; `?` matches one character except `/`;
- everything else is literal.

Renames count under both names: moving `web/api.py` to `legacy/api.py` runs a
`web/` reviewer.

At least one reviewer must have no `paths`, so every round has a reviewer.

## Escalate

Each entry is a string or `{when: "<prose>", paths: [globs]}`.

Auto-approve: after a passing final round, the orchestrator approves a job
without spawning the approver when all of these hold:

- every review passed;
- the `merge_gate` commands pass when the orchestrator runs them in the job
  worktree;
- `CFG escalate-hit` lists nothing under `hit` and nothing under `unchecked`.

`hit` holds the object entries whose `paths` match the diff. It also holds the
thin-tests rule: when `tests` is `thin` or `none`, a diff that touches `src/` or
`scripts/` always goes to the approver. `unchecked` holds every plain-string
entry, so a repo that wants auto-approve converts its string entries to the
object form. Leave one as a string to force the approver whenever that rule
cannot be expressed as paths (for example, deleted tests). With only string
entries, nothing changes: the approver always runs.

`decision.md` for an auto-approved job reads `APPROVE`, then
`auto: no escalate path matched, merge_gate green`.

## Lanes

```yaml
lanes:
  trivial:
    paths: ["*.md", "test/**"]   # required, globs
    max_changed_lines: 40        # optional, default 40
    skip: [spec, approval]       # optional, default []
```

Without `lanes`, `/factory:run` never triages and every job takes the full
path. With it, a `factory:triage` agent (`models.triage`) reads `feature.md`
and predicts `LANE: trivial` or `LANE: full`. A `trivial` job with `spec` in
`skip` gets `feature.md` copied to `spec.md` instead of a spec-writer run.
After the build, `CFG lane` classifies the real diff: `trivial` only if every
changed file matches `paths`, added plus deleted lines (a binary file counts
as 1000) stay within `max_changed_lines`, and no `escalate` entry's `paths`
match. A job triaged `trivial` whose diff is `full` is promoted: the full
reviewer set and the approver run, and the missing spec is not backfilled.
`approval` in `skip` lets a job whose diff is `trivial` auto-approve even when
`escalate` has plain-string entries (it still needs passing reviews, a green
`merge_gate`, and no `hit`).

The board job records `lane` (`trivial` or `full`); the dashboard shows it as a
chip.

## Example

```yaml
version: 1
base: main
context: [CLAUDE.md, .mex/AGENTS.md, .mex/context/conventions.md]
rules: .mex/AGENTS.md#Non-Negotiables
commands:
  test: uv run pytest tests/
  build: make build
merge_gate: [test]
scout:
  todo_paths: [src/, scripts/]
  docs: [README.md, docs/]
  checks:
    - every loader of an on-disk format refuses a version it does not know, with a test
builder:
  runtime: command
  command: scripts/run_agent.sh {session} {prompt_file} {out_prefix}
  resume: session
reviewers:
  - name: invariants
    why: on-disk formats and module boundaries are the hard rules
  - name: logic
    why: correctness of the core rules and their edge cases
  - name: maintainability
    why: conventions doc, simplicity, dead code
  - name: api-contract
    paths: [web/**]
    why: the web API has an external consumer
qa: null
escalate:
  - changes an on-disk format without a version bump
  - {when: adds a dependency or changes the build toolchain, paths: [pyproject.toml, Makefile]}
  - deletes tests
lanes:
  trivial: {paths: ["*.md", "docs/**"], max_changed_lines: 40, skip: [spec, approval]}
related: []
models:
  reviewers: sonnet high
  approver: opus high
  arbiter: opus max
  triage: haiku
```
