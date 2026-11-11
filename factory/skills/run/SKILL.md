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
   `tests`, `commands`, `merge_gate`, `scout`, `builder`, `reviewers`, `qa`,
   `escalate`, `related`, `models`, `lanes`. `NO_TESTS` is true when `tests` is `none` or
   `thin`.

Worktrees are `<worktrees>/<job-id>`, resolved against REPO, outside the repo
so the repo's own commands never see them.

## Spawning agents

- Plugin agents: `factory:triage`, `factory:spec-writer`, `factory:builder`, `factory:approver`,
  `factory:arbiter`, `factory:scout`. A milestone job (see `## milestone`) uses only
  the builder, the reviewers and, on rework, the arbiter. Reviewer `<r>` is the repo agent
  `factory-review-<r>`; QA is the repo agent named by `qa.agent`.
- Model and effort: look up the role in `models` (`triage`, `spec-writer`,
  `builder`, `approver`, `arbiter`, `scout`; every reviewer and QA use `reviewers`, unless
  the reviewer entry has its own `model`). A value `<model> <effort>` maps to
  the Agent tool's `model` and `effort`. `inherit`, or no entry, omits them.
- Every prompt carries absolute paths and these values, never conversation
  content: job folder, worktree, branch (`factory/<job-id>`), `base`, round N,
  the `context` paths, the `rules` doc, and `commands`.
  - The approver and arbiter also get `escalate` and `no_tests: true` when
    `NO_TESTS`. The approver also gets the list of reviewers that ran in the
    final round.
  - Every reviewer and the approver also get `<job folder>/round-N/commands.md`
    with: "It is the authoritative result of every command at the HEAD sha it
    records. Do not rerun commands unless the sha differs from the worktree
    HEAD; if you do rerun, run only the command that bears on your checklist
    and only the tests you cite. A failing command in it is a CHANGES item."
  - Every reviewer whose name starts with `contract` also gets every `related`
    entry (path and contract).

## The loop

```
feature
  -> triage (only if `lanes`)           writes triage.md; LANE: trivial skips spec-writer
  -> spec-writer                        writes spec.md
  -> builder                            writes build.md, commits on factory/<job-id>
  -> orchestrator runs `commands`       writes round-N/commands.md
  -> review round N, in parallel:       writes round-N/review-<r>.md
       every reviewer and QA that `CFG select` picks for this diff
  -> WAIT FOR ALL picked files
       any CHANGES and rework < max_rework  -> builder again, round N+1
       any CHANGES and rework = max_rework  -> arbiter
       all PASS                             -> approver, or auto-approve (below)
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
  "lane": "full",
  "stage": "review",
  "round": 2,
  "rework": 1,
  "reviews": { "security": "CHANGES", "logic": "PASS", "api": "skipped", "qa": "pending" },
  "history": [ { "round": 1, "reviews": { "security": "CHANGES", "logic": "PASS", "api": "skipped", "qa": "PASS" } } ],
  "note": "one line for the card",
  "updated": "2026-10-28T14:03:00Z"
} ] }
```

`lane` is `trivial` or `full`; omit it when the repo has no `lanes`. A milestone
job (see `## milestone`) has lane `milestone`. The dashboard shows it as a chip.

Stages, in order: `spec`, `build`, `review`, `approval`, `arbitration`,
`needs-human`, `merged`. A verdict is `pending`, `PASS`, `CHANGES`, or
`skipped`. `reviews` holds one key per reviewer in `reviewers` order, then `qa`
if the repo has QA. When a round closes, push `{round, reviews}` onto `history`
before you start the next round.

## Job files

```
factory/jobs/<job-id>/
  feature.md            the request (you write it)
  triage.md             triage (only when the repo has `lanes`)
  spec.md               spec-writer (or a copy of feature.md for a trivial job)
  build.md              builder (one "## Round N" section per round)
  builder-prompt-N.md   you, for a command builder
  builder-rN-*          a command builder's logs
  round-N/commands.md   you: the result of every command at that round's HEAD
  round-N/review-<r>.md one per reviewer that ran, plus review-qa.md
  rework-N.md           human or arbiter feedback for /factory:rework (you write it)
  decision.md           approver (or you, for an auto-approval)
  resolution.md         arbiter (after an escalation)
```

Job ids are `NNN-slug`: the next free 3-digit number in `factory/jobs/`, plus a
short kebab-case slug of the feature.

## /factory:run

`/factory:run <feature>`:

1. Pick the job id. Write `jobs/<id>/feature.md` with the feature text. Add the
   job to the board at stage `spec`, round 0, rework 0.
1b. Triage. If `lanes` is empty, skip this step. Otherwise spawn
   `factory:triage` with the job folder, REPO, `context`, `escalate` and
   `lanes.trivial`. Wait for `triage.md` and read its first line. `LANE:
   trivial` sets board `lane` to `trivial`; anything else, or a missing file,
   sets it to `full`.
2. If the lane is `trivial` and `lanes.trivial.skip` has `spec`, write
   `spec.md` as the line `# Trivial lane: build this request as written, no
   separate spec.` followed by `feature.md` verbatim. Otherwise spawn
   `factory:spec-writer` with the job folder and REPO and wait for `spec.md`.
3. Create the branch and worktree:
   `git worktree add -b factory/<id> <worktrees>/<id> <base>`.
   Set stage `build`, round 1.
4. Run the builder for round 1 (below).
5. Run a review round (below).

## Builder round N

Both runtimes: first record `BEFORE=$(git -C <worktree> rev-parse HEAD)`. When
the builder has finished, run
`CFG builder-done <worktree> $BEFORE <job folder>/build.md N`. If it exits
non-zero, set stage `needs-human` with note "builder run failed: <its output>"
and stop.

`runtime: claude`:
- Round 1, or no reachable builder: spawn `factory:builder` named
  `builder-<id>` and record its id in `builder`. Prompt: job folder, worktree,
  branch, round N, `context`, `rules`, `commands`. On a fresh spawn after round
  1, tell it to read `build.md` and the round's review or rework files first.
- Later rounds: resume the same builder with SendMessage: "Round N. Read
  `jobs/<id>/round-<N-1>/` (and `jobs/<id>/rework-<N>.md` if it exists) and fix
  every CHANGES item. Append `## Round N` to build.md."
- Wait for it to finish, then run the `builder-done` check above. Do not wait
  further for `build.md`: a builder that stopped without its section has
  failed the round.

`runtime: command`:
1. Write `jobs/<id>/builder-prompt-N.md` with what a Claude builder would get:
   - the prompt values above;
   - for round 1, "implement spec.md";
   - for later rounds, the review and rework files to fix;
   - the full text of the `factory:builder` agent's instructions (this plugin's
     `agents/builder.md`, without its frontmatter).
2. Fill in `builder.command`, single-quoting each filled-in value so paths
   with spaces survive:
   - `{prompt_file}` is that prompt file (absolute path);
   - `{session}` is `factory-<id>` when `resume: session`, `factory-<id>-r<N>`
     when `resume: fresh`;
   - `{out_prefix}` is `<job folder>/builder-r<N>` (absolute path).
   Record the session id in `builder`.
3. Run it with Bash from the worktree, in the background. Wait for it to exit
   and record its exit code.
4. A non-zero exit code: set stage `needs-human` with note "builder run failed:
   runner exited <code>", tell the user the logs are at
   `jobs/<id>/builder-r<N>*`, and stop. Exit 0: run the `builder-done` check;
   on failure, point the user at the same logs.

## Review round N

1. Create `jobs/<id>/round-N/`.
   - Lane check. If `lanes` is not empty, run `CFG lane REPO <base>
     factory/<id>` on the real diff and set board `lane` to its answer. If the
     triage said `trivial` and this says `full`, the job is promoted: note
     "promoted to full: <why>", and it takes the full path from here (the full
     reviewer set and the approver; the missing spec is not backfilled).
   - Commands. Run every `commands` entry once in the worktree and write
     `round-N/commands.md`: the HEAD sha (`git -C <worktree> rev-parse HEAD`),
     then per command its text, exit code, and last 20 lines of output. Reviewers
     and the approver read this file instead of rerunning.
   - Run `CFG select REPO <base> factory/<id>`.
   If `run` is empty, set stage `needs-human` with note "no reviewer matched
   this diff" and stop. Otherwise set stage `review` and replace `reviews` with
   every `run` name as `pending` and every `skipped` name as `skipped`.
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

First try to auto-approve. Run each `merge_gate` command in the worktree and
run `CFG escalate-hit REPO <base> factory/<id>`. Approve without the approver
when all reviews passed, every `merge_gate` command passed, and `hit` is empty
and `unchecked` is empty. `unchecked` may be non-empty when board `lane` is
`trivial` and `lanes.trivial.skip` has `approval`. Check the plain string
`deletes tests` yourself instead of leaving it to the approver: it is satisfied
when `git -C <worktree> diff --diff-filter=D --name-only <base>...HEAD` lists no
test file and `git -C <worktree> diff <base>...HEAD` removes no `expect(` or
`it(` line without adding one back; drop it from `unchecked` when so. A job with
lane `milestone` never spawns the approver; see `## milestone` for what it does
instead. To approve, write
`decision.md` as `APPROVE`, then the line `auto: no escalate path matched,
merge_gate green`, and go to Merge. Otherwise spawn the approver:

Spawn `factory:approver` with the job folder, worktree, branch, `base`, the
final round number, the reviewers that ran in it, `rules`, `context`,
`escalate`, `commands`, `round-N/commands.md`, and `no_tests: true` when
`NO_TESTS`. Read the first line of `decision.md`:
- `APPROVE`: Merge (below).
- `ESCALATE`: note = the approver's one-line reason, then go to Arbitration.

## Arbitration

1. Set stage `arbitration`. Spawn `factory:arbiter` with the job folder,
   worktree, branch, `base`, the final round number, the reason it escalated
   (the path of `decision.md`, or "review did not converge after N rounds"),
   `rules`, `context`, `escalate`, `commands`, and `no_tests: true` when
   `NO_TESTS`. Wait for `resolution.md`.
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
2. If that checkout has uncommitted changes (`git status --porcelain` prints
   anything), set stage `needs-human` with note "base checkout has uncommitted
   changes" and stop; never stash or discard them. Otherwise, in that checkout:
   `git merge --no-ff factory/<id> -m "Merge factory/<id>"`.
   If the merge conflicts, run `git merge --abort`, set stage `needs-human` with
   note "merge conflict", and stop.
3. Run each `merge_gate` command there. If one fails, report it, set stage
   `needs-human` with note "merge gate failed: <command>", and stop; do not
   revert on your own.
4. Remove the job worktree (`git worktree remove <worktrees>/<id>`). Keep the
   branch. Never push.
5. Add follow-ups to the backlog. Read the final round's reviews, `decision.md`,
   and the builder's notes in `build.md`. Collect every non-blocking finding,
   nit, flaky test, and item the spec defers to later work, unless a backlog
   item already covers it. Append each one to `backlog.md` as `- [ ] <item>`
   under a `## Follow-ups from job <id>` heading at the end of the file. Write
   each item as a concrete feature that names the file or command. Tell the
   user how many you added.
6. Set stage `merged`. Merge is the only place that sets it.

## milestone

`/factory:milestone <N> [<N> ...]`. One milestone is one job. Use it when
`factory/milestones.md` (or the file the repo's docs name) holds a `## M<N>.`
section with a `**Steps:**` list. It skips triage, the spec-writer and the
approver, uses one builder for every step and one review pass for the whole
diff, and auto-merges unless the milestone text explicitly flags a step.

For each `<N>`, in the order given (a later milestone depends on the earlier one
being merged, so never run two at once; stop the whole list at the first job
that does not reach `merged`):

1. Job id `NNN-m<N>-<slug>`. Write `jobs/<id>/feature.md`: the `## M<N>.`
   section verbatim, preceded by the file's `## Conventions` section. Add the
   job to the board with lane `milestone`, stage `build`, round 1.
2. Write `spec.md` as the line `# Milestone job: build every step in order, one
   commit per step, no separate spec.` followed by `feature.md` verbatim. Create
   the branch and worktree as in `## /factory:run` step 3.
3. Run the builder (`## Builder round N`) with this added to its prompt:
   "This is a milestone job. Implement every step of the Steps list in order,
   one commit per step, and run the commands after the last step. Write one
   `## Round 1` section in build.md with a line per step. Do not run mutation
   or fault-injection experiments unless a step asks for them."
4. Run a review round (`## Review round N`). Skip its lane check; the lane stays
   `milestone`. Reviewers that `CFG select` picks run exactly as for any job.
5. Close the round as usual: CHANGES go to rework (builder resumed), and past
   `max_rework` to the arbiter.
6. All PASS: stage `approval`. Never spawn `factory:approver`.
   - Flagged: if the `## M<N>.` section of `feature.md` (not the Conventions
     text before it, which mentions the marker) contains the text `[ESCALATE`, set stage
     `needs-human` with a note listing each flagged step and its reason, and
     stop the list. The owner runs `/factory:approve <id>` when satisfied.
     This is the only reason a milestone job stops for a human.
   - Otherwise run the auto-approve checks from `## Approval` (merge gate on
     the worktree, `escalate-hit`, the mechanical `deletes tests` check). If all
     hold, write `decision.md` as `APPROVE` then the line `auto: milestone, no
     flagged step, merge_gate green`, and go to Merge. If `escalate-hit` returns
     a `hit` (a path-based `escalate` entry matched), set stage `needs-human`
     with the entry's `when` as the note and stop the list.
7. After Merge, print the milestone's `**Observable in game:**` paragraph as the
   owner check, then continue to the next `<N>` only if the user passed several
   and none of the earlier ones has an owner check the user has not already
   confirmed; otherwise stop and say which `/factory:milestone` to run after the
   check.

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

`<job-id> [<job-id> ...]`. Each must be at stage `needs-human`; for any other
stage, say which stage it is at and skip that id. With several ids, handle them
in the order given and stop at the first one that fails Merge, leaving the rest
at `needs-human`. For each job, show the user `resolution.md` if it exists, else
`decision.md` (or the last round's CHANGES items, or for a milestone job the
flagged steps and the review verdict), in two or three lines per job; if no
review round finished (for example, the builder run failed), say so. Then Merge
that job; the merge gate runs after each one. The user typing the command is the
approval; do not ask again. In Merge step 5, also add the `- [ ]` follow-ups from
an `ACCEPT` resolution's `## Next step`. Its spec amendment stays on record in
`resolution.md`; nobody rewrites `spec.md`.

## arbitrate

`<job-id>`. For a job at stage `needs-human` that has no `resolution.md` yet
(for example, one whose builder run failed or that escalated before the arbiter
existed). Run Arbitration.

## rework

`<job-id> <note>`. Only for a job at stage `needs-human`; for any other stage,
say which stage it is at and stop.

1. Write the note to `jobs/<id>/rework-<round+1>.md`. Recreate the worktree if
   it was removed (`git worktree add <worktrees>/<id> factory/<id>`).
2. Increment `round`, set `rework` to 0, stage `build`. Rename `decision.md` (if any)
   to `decision-<old round>.md`, and `resolution.md` (if any) to
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
  `builder-prompt-N.md`, `board.json`, and `backlog.md`, `round-N/commands.md`, and `decision.md` for an auto-approval (including a milestone job's); `triage` writes `triage.md`; `scout` writes
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
