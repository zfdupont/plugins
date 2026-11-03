---
name: run
description: Run the software factory on one feature, from spec to merge. Use for /factory:run <feature>. Also holds the shared loop the other /factory:* commands follow. The session that runs it is the orchestrator.
---

# Factory

You are the orchestrator. You run the loop below, spawn every agent, and you are
the only writer of `factory/board.json`. Agents get their context from files and
from the values you pass, not from this conversation, and each writes only its
own file.

`REPO` is the repo's top-level directory (`git rev-parse --show-toplevel`).
`CFG` means `uv run -q --script <this skill's base directory>/scripts/factory_config.py`.
`schema.md` in this skill's base directory is the `factory.yaml` reference.

## Setup check

Run this before every command except `/factory:setup`.

1. Run `CFG validate REPO`. If it exits non-zero, print its lines and stop. If
   the only line says `not found`, tell the user to run `/factory:setup`.
2. Read the settings with `CFG get REPO <key>` and keep them for this run:
   `base`, `max_rework`, `max_arbiter_rework`, `worktrees`, `context`, `rules`,
   `commands`, `merge_gate`, `scout`, `builder`, `reviewers`, `qa`, `escalate`,
   `related`, `models`. `NO_TESTS` is true when `commands` has no `test` key.

Worktrees are `<worktrees>/<job-id>`, resolved against REPO, outside the repo
so the repo's own commands never see them.

## Spawning agents

- Plugin agents: `factory:spec-writer`, `factory:builder`, `factory:approver`,
  `factory:arbiter`, `factory:scout`. Reviewer `<r>` is the repo agent
  `factory-review-<r>`; QA is the repo agent named by `qa.agent`.
- Model and effort: look up the role in `models` (`spec-writer`, `builder`,
  `approver`, `arbiter`, `scout`; every reviewer and QA use `reviewers`, unless
  the reviewer entry has its own `model`). A value `<model> <effort>` maps to
  the Agent tool's `model` and `effort`. `inherit`, or no entry, omits them.
- Every prompt carries absolute paths and these values, never conversation
  content: job folder, worktree, branch (`factory/<job-id>`), `base`, round N,
  the `context` paths, the `rules` doc, and `commands`.
  - The approver and arbiter also get `escalate` and `no_tests: true` when
    `NO_TESTS`. The approver also gets the list of reviewers that ran in the
    final round.
  - Every reviewer whose name starts with `contract` also gets every `related`
    entry (path and contract).

## The loop

```
feature
  -> spec-writer                        writes spec.md
  -> builder                            writes build.md, commits on factory/<job-id>
  -> review round N, in parallel:       writes round-N/review-<r>.md
       every reviewer and QA that `CFG select` picks for this diff
  -> WAIT FOR ALL picked files
       any CHANGES and rework < max_rework  -> builder again, round N+1
       any CHANGES and rework = max_rework  -> arbiter
       all PASS                             -> approver
  -> approver                           writes decision.md
       APPROVE   -> merge factory/<job-id> into base, stage merged
       ESCALATE  -> arbiter
  -> arbiter                            writes resolution.md
       ACCEPT    -> needs-human with the recommendation (waits for /factory:approve)
       REWORK    -> rework with the arbiter's note, review again (max_arbiter_rework per job)
       OWNER     -> needs-human with the arbiter's question
```

## Board

`factory/board.json` drives `factory/dashboard.html`. Rewrite the whole file
after every state change (read it, change the one job, write it back).

```json
{ "jobs": [ {
  "id": "004-status-json",
  "title": "status --json",
  "branch": "factory/004-status-json",
  "worktree": "<worktrees>/004-status-json",
  "builder": "<agent id or name used for SendMessage, or the runner session id>",
  "stage": "review",
  "round": 2,
  "rework": 1,
  "reviews": { "security": "CHANGES", "logic": "PASS", "api": "skipped", "qa": "pending" },
  "history": [ { "round": 1, "reviews": { "security": "CHANGES", "logic": "PASS", "api": "skipped", "qa": "PASS" } } ],
  "note": "one line for the card",
  "updated": "2026-10-28T14:03:00Z"
} ] }
```

Stages, in order: `spec`, `build`, `review`, `approval`, `arbitration`,
`needs-human`, `merged`. A verdict is `pending`, `PASS`, `CHANGES`, or
`skipped`. `reviews` holds one key per reviewer in `reviewers` order, then `qa`
if the repo has QA. When a round closes, push `{round, reviews}` onto `history`
before you reset `reviews`.

## Job files

```
factory/jobs/<job-id>/
  feature.md            the request (you write it)
  spec.md               spec-writer
  build.md              builder (one "## Round N" section per round)
  builder-prompt-N.md   you, for a command builder
  builder-rN-*          a command builder's logs
  round-N/review-<r>.md one per reviewer that ran, plus review-qa.md
  rework-N.md           human or arbiter feedback for /factory:rework (you write it)
  decision.md           approver
  resolution.md         arbiter (after an escalation)
```

Job ids are `NNN-slug`: the next free 3-digit number in `factory/jobs/`, plus a
short kebab-case slug of the feature.

## /factory:run

`/factory:run <feature>`:

1. Pick the job id. Write `jobs/<id>/feature.md` with the feature text. Add the
   job to the board at stage `spec`, round 0, rework 0.
2. Spawn `factory:spec-writer` with the job folder and REPO. Wait for `spec.md`.
3. Create the branch and worktree:
   `git worktree add -b factory/<id> <worktrees>/<id> <base>`.
   Set stage `build`, round 1.
4. Run the builder for round 1 (below).
5. Run a review round (below).

## Builder round N

`runtime: claude`:
- Round 1, or no reachable builder: spawn `factory:builder` named
  `builder-<id>` and record its id in `builder`. Prompt: job folder, worktree,
  branch, round N, `context`, `rules`, `commands`. On a fresh spawn after round
  1, tell it to read `build.md` and the round's review or rework files first.
- Later rounds: resume the same builder with SendMessage: "Round N. Read
  `jobs/<id>/round-<N-1>/` (and `jobs/<id>/rework-<N>.md` if it exists) and fix
  every CHANGES item. Append `## Round N` to build.md."
- Wait for it to finish and for `build.md` to have a `## Round N` section.

`runtime: command`:
1. Record `BEFORE=$(git -C <worktree> rev-parse HEAD)`.
2. Write `jobs/<id>/builder-prompt-N.md` with what a Claude builder would get:
   - the prompt values above;
   - for round 1, "implement spec.md";
   - for later rounds, the review and rework files to fix;
   - the full text of the `factory:builder` agent's instructions (this plugin's
     `agents/builder.md`, without its frontmatter).
3. Fill in `builder.command`:
   - `{prompt_file}` is that prompt file (absolute path);
   - `{session}` is `factory-<id>` when `resume: session`, `factory-<id>-r<N>`
     when `resume: fresh`;
   - `{out_prefix}` is `<job folder>/builder-r<N>` (absolute path).
   Record the session id in `builder`.
4. Run it with Bash from the worktree, in the background. Wait for it to exit.
5. Run `CFG builder-done <worktree> $BEFORE <job folder>/build.md N`. If it
   exits non-zero, set stage `needs-human` with note "builder run failed: <its
   output>", tell the user the logs are at `jobs/<id>/builder-r<N>*`, and stop.

## Review round N

1. Create `jobs/<id>/round-N/`. Run `CFG select REPO <base> factory/<id>`.
   Set stage `review`. In `reviews`, set every `run` name to `pending` and
   every `skipped` name to `skipped`.
2. Spawn every `run` name in ONE message so they run in parallel. Reviewer
   `<r>` writes `round-N/review-<r>.md`; QA writes `round-N/review-qa.md`. Each
   prompt gives job folder, worktree, branch, `base`, round N, its output file,
   `context`, `rules`, `commands` (plus `related` for `contract*` reviewers).
3. As each one finishes, read the first line of its file and update its chip
   (`VERDICT: PASS` -> `PASS`, `VERDICT: CHANGES` -> `CHANGES`). A file without
   a valid first line counts as `CHANGES`.
4. WAIT FOR ALL: the round is done only when every `run` file exists in
   `round-N/`. Never start the builder mid-round, even if a CHANGES verdict is
   already in.
5. Close the round:
   - All PASS: stage `approval`, go to Approval.
   - Any CHANGES and `rework` < `max_rework`: increment `rework`, round N+1,
     stage `build`. Run the builder for round N+1, then review round N+1.
   - Any CHANGES and `rework` = `max_rework`: note "review did not converge
     after N rounds", then go to Arbitration.

## Approval

Spawn `factory:approver` with the job folder, worktree, branch, `base`, the
final round number, the reviewers that ran in it, `rules`, `context`,
`escalate`, `commands`, and `no_tests: true` when `NO_TESTS`. Read the first
line of `decision.md`:
- `APPROVE`: Merge (below), stage `merged`.
- `ESCALATE`: note = the approver's one-line reason, then go to Arbitration.

## Arbitration

1. Set stage `arbitration`. Spawn `factory:arbiter` with the job folder,
   worktree, branch, `base`, the final round number, the reason it escalated
   (the path of `decision.md`, or "review did not converge after N rounds"),
   `rules`, `context`, `escalate`, `commands`. Wait for `resolution.md`.
2. Read its first two lines. The second line is the card note, prefixed with
   the verdict (`ACCEPT: ...`).
   - `ACCEPT`: stage `needs-human`. Tell the user the arbiter recommends
     merging as built and point them at `/factory:approve <id>`. Stop.
   - `REWORK`: if fewer than `max_arbiter_rework` `resolution-*.md` files with
     a `REWORK` first line already exist, run `## rework` with the
     `## Next step` section of `resolution.md` as the note, word for word.
     Otherwise stage `needs-human` with note "arbiter rework did not resolve it".
   - `OWNER`: stage `needs-human`. Show the user the arbiter's question and
     options, recommendation first. Stop.
   - A missing file or an invalid first line: stage `needs-human`, note "arbiter
     gave no resolution". Stop.

## Merge

1. Find where `base` is checked out with `git worktree list`. If nowhere, run
   `git worktree add <worktrees>/_base <base>`.
2. In that checkout: `git merge --no-ff factory/<id> -m "Merge factory/<id>"`.
   If the merge conflicts, run `git merge --abort`, set stage `needs-human` with
   note "merge conflict", and stop.
3. Run each `merge_gate` command there. If one fails, report it and set
   `needs-human`; do not revert on your own.
4. Remove the job worktree (`git worktree remove <worktrees>/<id>`). Keep the
   branch. Never push.
5. Add follow-ups to the backlog. Read the final round's reviews, `decision.md`,
   and the builder's notes in `build.md`. Collect every non-blocking finding,
   nit, flaky test, and item the spec defers to later work, unless a backlog
   item already covers it. Append each one to `backlog.md` as `- [ ] <item>`
   under a `## Follow-ups from job <id>` heading at the end of the file. Write
   each item as a concrete feature that names the file or command. Tell the
   user how many you added.

## next

Read `factory/backlog.md`. Take the first `- [ ]` item (items under
`## Foundations` come first because that section is at the top). Change it to
`- [x]` with ` (job <id>)` appended, then run `## /factory:run` with that item.
If there is none, say so and suggest `/factory:scout` and
`/factory:scout foundations`.

## scout

1. Spawn `factory:scout` with the checkout of `base` (from `git worktree
   list`), the absolute path of `factory/`, `scout`, `escalate`, `context`.
   Wait for `factory/scout.md`.
2. Ask the user which items to add (one multi-select question, one option per
   item, the `Why:` line as its description).
3. Append the chosen items to `backlog.md` as `- [ ] <item>`. Leave the rest in
   `scout.md`; the next scout run overwrites it.

## approve

`<job-id>`. Only for a job at stage `needs-human`. Show the user `resolution.md`
if it exists, else `decision.md` (or the last round's CHANGES items), in two or
three lines, then Merge. The user typing the command is the approval; do not
ask again. In Merge step 5, also add the `- [ ]` follow-ups from an `ACCEPT`
resolution's `## Next step`. Its spec amendment stays on record in
`resolution.md`; nobody rewrites `spec.md`.

## arbitrate

`<job-id>`. For a job at stage `needs-human` that has no `resolution.md` yet
(for example, one whose builder run failed or that escalated before the arbiter
existed). Run Arbitration.

## rework

`<job-id> <note>`:

1. Write the note to `jobs/<id>/rework-<round+1>.md`. Recreate the worktree if
   it was removed (`git worktree add <worktrees>/<id> factory/<id>`).
2. Increment `round`, set `rework` to 0, stage `build`. Rename `decision.md` to
   `decision-<old round>.md`, and `resolution.md` (if any) to
   `resolution-<old round>.md`.
3. Run the builder for the new round. For `runtime: claude`, resume
   `builder-<id>` if it is reachable from this session, pointing at
   `rework-<round>.md`; otherwise spawn a fresh one and tell it to read
   `build.md` and `rework-<round>.md` first.
4. Run a review round, then Approval as usual.

## Rules

- Prompts to agents contain paths and values, never conversation content.
  Anything an agent needs goes in a file first.
- Each agent writes only its own file. You write `feature.md`, `rework-N.md`,
  `builder-prompt-N.md`, `board.json`, and `backlog.md`; `scout` writes
  `scout.md`; `arbiter` writes `resolution.md`.
- Reviews start with `VERDICT: PASS` or `VERDICT: CHANGES`; `decision.md`
  starts with `APPROVE` or `ESCALATE`; `resolution.md` starts with `ACCEPT`,
  `REWORK`, or `OWNER`.
- An agent that finishes without writing its file gets one SendMessage
  asking it to write that file now, word for word what it reported. If the file
  is still missing, treat it as the stage says for a missing file (a review
  counts as `CHANGES`; `decision.md` counts as `ESCALATE`; the others set
  `needs-human`).
- The arbiter never merges anything. Only `/factory:approve` merges a job that
  escalated.
- Never push.
- Tell the user one line per stage change. Point them at the dashboard:
  `cd factory && python3 -m http.server 8765`, then
  http://localhost:8765/dashboard.html
