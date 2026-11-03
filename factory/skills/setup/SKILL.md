---
name: setup
description: Set up the software factory for this repo, or propose an updated setup. Reads the codebase, proposes reviewers, commands, QA, escalation rules, builder runtime and models, and writes factory/factory.yaml only after the owner approves. Use for /factory:setup.
---

# Factory setup

You read the repo, propose the factory that fits it, and write it only after
the owner approves. The same steps cover a first setup and a rerun.

`REPO` is `git rev-parse --show-toplevel`. `RUN` is `../run/` resolved against
this skill's base directory. `CFG` means
`uv run -q --script <RUN>/scripts/factory_config.py`. `<RUN>/schema.md` is the
`factory.yaml` reference; read it before drafting. `reviewer-template.md` in
this skill's base directory is the shape of every reviewer and QA agent.

`DRAFT` is `REPO/.git/factory-setup/`. Everything before approval goes there.
It is inside the git dir, so it is never committed and builds never see it.
Never write to the working tree before the owner approves.

## Survey

1. Delete any old `DRAFT` (run `git worktree remove --force DRAFT/wt` first
   if it exists), then create `DRAFT/proposed/` and a throwaway checkout for
   running commands: `git worktree add --detach DRAFT/wt HEAD`.
2. Spawn `factory:setup-surveyor` with REPO, the scratch checkout `DRAFT/wt`
   (where it runs every command), the survey path `DRAFT/survey.md`, and the
   path of `factory/factory.yaml` if it exists.
   Use `models.setup-surveyor` from the current YAML if there is one. Wait for
   the survey.

## Propose

Draft the whole factory from the survey into `DRAFT/proposed/`, mirroring the
repo layout: `factory/factory.yaml`, one `.claude/agents/factory-review-<name>.md`
per reviewer, and `.claude/agents/<qa agent>.md` if there is QA.

`factory.yaml`, key by key (see `schema.md` for the full reference):

- `base`: the branch the repo merges into (usually `main`).
- `context`: the docs an agent must read to work here (`CLAUDE.md`, the
  knowledge-folder anchor and conventions docs). Keep it short.
- `rules`: the rules doc and heading from the survey, if one is filled in.
- `tests`: from the survey's test count. `ok` when a test command runs and
  real tests exercise the code; `thin` when it runs but few or no tests do (for
  example, every test commented out); `none` when there is no test command.
- `commands`: every command the survey says runs: test, lint, build, type
  check. Name the test command `test`. Leave out commands that do not run, and
  list them as gaps instead. Set `merge_gate` to the fast ones, at least `test`
  when it exists. With `tests: none` and nothing runnable, `commands` may be
  empty.
- `builder`: copy how the repo builds code today. A runner script gives
  `runtime: command` with its arguments mapped to `{session}`,
  `{prompt_file}` and `{out_prefix}`. Otherwise `runtime: claude`.
- `scout`: `todo_paths` from the survey's Areas, `docs` where later work is
  described, and `checks` for repo-specific foundations (for example, every
  parser of untrusted input has a fuzz target).
- `escalate`: one line per risk in the survey's Risks section, written so the
  approver can tell from a diff whether it applies. Always add "adds a
  dependency, changes the build toolchain, or deletes tests".
- `related`: every related repo with its contract.
- `models`: `spec-writer`, `approver` and `arbiter` on the most capable model,
  `reviewers` and `scout` on a mid-tier model, unless the repo or the owner's
  rules say otherwise.

Choosing the reviewer lineup:

- Always one reviewer for the repo's hard rules (security for a security tool,
  invariants for a repo whose rules are formats and boundaries), one for logic
  (correctness, error paths, edge cases), and one for maintainability
  (conventions, simplicity, dead code).
- Add interface reviewers by what the program's interface is:
  - a CLI: one combined output-and-flow reviewer;
  - a web UI: separate visual and interaction reviewers;
  - an HTTP API: a contract reviewer (named `contract-<x>`), which reads the
    related repos when there are any.
- Add specialist reviewers, scoped by `paths`, for areas with their own risk
  (experiment rigor for training code, data correctness for a pipeline).
- Keep the lineup to what the survey can justify with a fact. Every reviewer
  needs a `why` that names something in this repo.
- Scope a reviewer with `paths` whenever its concern lives in part of the
  tree, so jobs elsewhere do not pay for it.

QA: if the survey lists a program driver, set `qa: {agent: factory-qa}` and
write the QA agent from the template's QA variant around that driver.
Otherwise `qa: null`, and list the missing driver as a gap.

Write each agent file from `reviewer-template.md`, with a checklist of four to
eight items that cite this repo's rules, conventions or files.

## Propose and write

This section is shared: `/factory:tune` sends its approved settings changes
through it too.

1. Run `CFG validate DRAFT/proposed` and fix the draft until it passes, so
   the owner only ever sees a valid proposal. Then show the owner the proposal:
   - If `tests` is `none` or `thin`, say first, in one line, that the repo has
     no real test suite, so the approver and arbiter will escalate changes they
     cannot check.
   - The lineup as a table: reviewer, runs when (`always` or its `paths`),
     why. Then QA, the builder runtime, `commands` and `merge_gate`, the
     `escalate` list, `related`, and `models`.
   - On a rerun (a `factory/factory.yaml` already exists): instead of the
     table alone, show `diff -ru` between the current files and
     `DRAFT/proposed/`, then one reason per change. Remind the owner that
     the diff removes any hand edits it does not keep.
2. Ask the owner to approve, or to say what to change. Apply their edits to
   `DRAFT/proposed/` and show the changed parts again. Repeat until they
   approve or decline.
3. Declined: remove `DRAFT/wt` if it exists (`git worktree remove --force`), delete
   `DRAFT`, and stop. Nothing in the working tree changed.
4. Approved: copy `DRAFT/proposed/` over the repo. On a rerun, also delete
   reviewer agent files (`factory-review-*.md`) and the QA agent that the new
   proposal dropped. Never touch `factory/board.json` contents, `factory/jobs/`,
   or existing `backlog.md` items.
5. If missing, create `factory/board.json` as `{"jobs": []}`,
   `factory/backlog.md` as `# Backlog`, and `factory/jobs/.gitkeep`. Copy
   `<RUN>/dashboard.html` to `factory/dashboard.html` (replace it on a rerun).
6. Run `CFG validate REPO`. It passed on the draft, so a failure means the
   copy went wrong: report it and stop.
7. Remove `DRAFT/wt` if it exists (`git worktree remove --force`) and delete `DRAFT`. Tell the owner which files were written, that nothing is
   committed, and how to watch the board:
   `cd factory && python3 -m http.server 8765`.
8. On a first setup, run `## Foundations` next.

## Foundations

Used by `/factory:scout foundations` and at the end of a first setup.

1. Create a throwaway checkout of `base` for running commands:
   `git worktree add --detach REPO/.git/factory-scratch <base>`. Spawn
   `factory:foundations-scout` with that checkout, the absolute path of
   `factory/`, and from the YAML `commands`, `rules`, `context`, `qa`,
   `scout`, and `reviewers`. Use `models.foundations-scout`. Wait for
   `factory/scout.md`, then remove the scratch checkout
   (`git worktree remove --force REPO/.git/factory-scratch`).
2. Show the items as the "fix these first" list. Ask the owner which to add
   (one multi-select question, one option per item, the `Why:` line as its
   description).
3. Add the chosen items to `backlog.md` as `- [ ] <item>` under a
   `## Foundations` heading placed directly after the first line of the file,
   creating the heading if needed, so `/factory:next` takes them before
   feature work.
