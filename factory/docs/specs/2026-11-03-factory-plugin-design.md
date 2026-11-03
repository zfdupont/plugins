# Factory plugin: design

Status: draft for owner review. Date: 2026-11-03.

## Intent

The sc repo has a working software factory: a Claude Code skill that takes a
feature from spec to merge with a builder, a panel of reviewers, an approver,
and an arbiter, all coordinated through files and a dashboard. It works, but
every part of it is written for sc: the reviewer lineup, their checklists, the
test commands, and the list of things that make a job escalate.

The owner wants the same factory in other repos, starting with `~/pokerbot`,
and later `~/huskies-client` and `~/huskies-server`. Those repos are different
kinds of software and need different reviewers. sc is a security-critical
system tool, so separate UI and UX reviews are mostly wasted there, while its
code review would be better split into logic and maintainability. A React app
like huskies-client is the reverse: it needs real visual and interaction review.

So the factory becomes a plugin in the owner's marketplace (`zfdupont/plugins`,
next to `pstack`). A setup step reads a repo and proposes the factory shape that
fits it. The owner approves or edits the proposal. The result is written to a
YAML file the owner can override, and setup can rewrite later as the repo
changes. A foundations scout checks each repo for the gaps that keep the factory
from judging work well (no tests, no lint, no stated rules, no way to drive the
real program) and turns them into backlog items.

## Goals

1. One plugin, `factory`, that runs the existing loop (spec, build, review
   rounds, approval, arbitration, merge) in any repo.
2. `/factory setup` reads the repo and proposes the whole per-repo shape:
   reviewers, commands, QA, escalation rules, builder runtime, models. Nothing
   is written until the owner approves.
3. The per-repo shape lives in `factory/factory.yaml` plus reviewer agent files
   in the repo. The owner overrides by editing them.
4. Running setup again proposes a full rewrite as a diff with a reason per
   change. The owner approves before anything is written.
5. A foundations scout finds gaps the factory needs filled and proposes them as
   backlog items ranked above feature work.
6. `/factory tune` looks at the current state of the project and the factory's
   own record (settings, board, job history) and suggests improvements, each
   backed by evidence, applied only on the owner's approval.
7. sc migrates onto the plugin first, with no loss of job history, then pokerbot.

## Non-goals (v1)

- GitHub issues or project boards as the state store. State stays in files in
  the repo (`board.json`, `jobs/`).
- Telemetry intake (Sentry, PostHog). None of the target repos has telemetry.
- Running several jobs at once. One job at a time, as today.
- Pushing branches or opening PRs. The factory merges locally and never pushes.
- Depending on pstack. Using pstack principles inside agents is a later option.
- Supporting harnesses other than Claude Code as the orchestrator.

## Anti-goals

The design fails, even if it works, if:

- setup writes or rewrites any file before the owner approves it;
- anything specific to one repo (a command, a path, a rule, a reviewer name)
  ends up hardcoded in the plugin;
- migrating sc loses or breaks existing jobs, the board, or the dashboard;
- a repo with no tests gets a factory that merges work it cannot check, without
  saying so.

## Survey: what varies between repos

Findings from reading the four repos on 2026-11-02 and 2026-11-03. They are the
evidence for which parts are per-repo.

| | sc | pokerbot | huskies-client | huskies-server |
|---|---|---|---|---|
| Kind | C++20 CLI and daemon, security-critical | Python simulator with C++ training engines (pybind11, libtorch), small web API, deploys to openpoker.ai | React and Vite single-page app with a Leaflet map | Spring Boot read-only API plus Python data pipeline, meeting at MongoDB |
| Rules doc | `.mex/AGENTS.md` Non-Negotiables (filled) | `.mex/AGENTS.md` Non-Negotiables (filled) | `.mex/AGENTS.md` (template, empty) | `CLAUDE.md` only |
| Test | `buck2 test //...` | `uv run pytest tests/` | `pnpm test`, `pnpm test:e2e` (Playwright) | `./mvnw test` (only test class is commented out) |
| Lint | `./scripts/lint.sh` | none found | none | none found |
| Build | Buck2 | `~/bin/buck2 build //neural_cfr:neural_cfr //sixmax:sixmax` | `pnpm build` | `cd server && ./mvnw clean package` |
| Drives the real program | `verify-sc` skill | none (play and eval scripts exist) | Playwright e2e | none |
| Builder today | Claude agent | `pi` on DeepSeek via `scripts/pi_run.sh` (reviewers stay Claude) | n/a | n/a |
| Main risks | plaintext leaks, crypto, key storage, daemon protocol | import boundaries, fixed action vocab, versioned checkpoint formats, chip rescaling, evaluator kicker inversion | visual regressions (dark mode, mobile, responsive), state store pattern | API shape the client depends on, pipeline data correctness, `release` branch deploys |
| Related repo | none | none | huskies-server (its only backend) | huskies-client (its only consumer) |

What stays fixed: the loop, the board and dashboard, the job file layout,
rework and arbitration limits, the approver and arbiter roles, the spec format,
and the file-based handoff between agents.

What varies: the reviewer lineup and checklists, which reviewers run for which
paths, commands, QA, escalation rules, builder runtime, models per role, and
related repos.

## Design

### Plugin layout

```
plugins/factory/
  .claude-plugin/plugin.json
  README.md
  skills/
    factory/SKILL.md            orchestrator: the loop and every /factory command
    factory/schema.md           factory.yaml reference (read by setup and the orchestrator)
    factory/dashboard.html      copied into a repo's factory/ by setup
  agents/
    spec-writer.md
    builder.md
    approver.md
    arbiter.md
    scout.md                    feature scout
    foundations-scout.md        gap scout
    setup-surveyor.md           reads a repo for /factory setup
    tuner.md                    reads the factory's record for /factory tune
  docs/specs/                   this document
```

The marketplace's `.claude-plugin/marketplace.json` gets a `factory` entry.
Plugin agents are namespaced (`factory:builder`), so they never clash with a
repo's own agents.

### What the repo holds

```
<repo>/
  factory/
    factory.yaml                the per-repo shape (setup writes, owner edits)
    board.json  dashboard.html  backlog.md  scout.md  jobs/
  .claude/agents/
    factory-review-<name>.md    one per reviewer (setup writes, owner edits)
    factory-qa.md               if the repo has a QA step
```

Reviewers and QA are repo agents, not plugin agents, because their checklists
are the most repo-specific text in the system. Each is a normal agent file:
frontmatter (`name`, `description`, `tools`, `model`), then the checklist.
Setup writes them from what it found; the plugin ships no reviewer.

### factory.yaml

Setup writes it; the orchestrator reads only it (plus the agent files it names)
for anything repo-specific. Comments carry the reasons setup gave. Example for
pokerbot (illustrative values, not final):

```yaml
version: 1
base: main
max_rework: 2
max_arbiter_rework: 1
worktrees: ../pokerbot-factory      # job worktrees go in <worktrees>/<job-id>

context:                            # what spec-writer, builder, reviewers read first
  - CLAUDE.md
  - .mex/AGENTS.md
  - .mex/context/conventions.md
rules: .mex/AGENTS.md#Non-Negotiables

commands:                           # open set; the builder runs all, each must pass
  test: uv run pytest tests/
  build: ~/bin/buck2 build //neural_cfr:neural_cfr //sixmax:sixmax
merge_gate: [test]                  # what the orchestrator reruns on BASE after merging

scout:                              # repo-specific inputs for both scouts (setup writes)
  todo_paths: [agents/, cfr/, neural_cfr/, sixmax/, web/, scripts/]
  docs: [README.md, docs/]          # where later-milestone and "limits" items live
  checks:                           # extra foundations checks, one line each
    - every checkpoint loader refuses a mismatched vocab hash, with a test

builder:
  runtime: command                  # claude | command
  command: scripts/pi_run.sh {session} {prompt_file} {out_prefix}
  resume: session                   # session: same {session} id each round; fresh: new run each round

reviewers:
  - name: invariants                # agent: .claude/agents/factory-review-invariants.md
    why: import boundaries, action vocab, checkpoint versions and chip scaling are the hard rules
  - name: logic
    why: game rules, pot and stack math, legal-action masking
  - name: maintainability
    why: conventions in .mex/context/conventions.md, simplicity, dead code
  - name: api-contract
    paths: [web/**]
    why: the web API is consumed by the deployed bot
  - name: experiment-rigor
    paths: [cfr/**, neural_cfr/**, sixmax/**, scripts/train_*, scripts/eval_*]
    why: claimed BB/100 or exploitability changes need enough hands to mean anything

qa: null                            # gap: no way to drive the real program yet (see foundations)

escalate:                           # approver escalates on any of these, even when reviews pass
  - changes a checkpoint format, bucket map, or vocab without a version bump
  - touches common/src/game/card.cpp
  - changes deploy scripts (scripts/run_openpoker.sh) or docker/
  - adds a dependency, changes the build toolchain, or deletes tests

related: []                         # sibling repos whose contracts reviewers must read

models:                             # <model> <effort>, passed on each spawn
  spec-writer: opus high
  reviewers: sonnet high
  approver: opus high
  arbiter: opus max
```

Field rules:

- A reviewer with no `paths` runs every round. A reviewer with `paths` runs
  only when the job's diff (`git diff --name-only <base>...HEAD`) matches one of
  the globs. The orchestrator decides once per round and records skipped
  reviewers on the board as `skipped`.
- `qa`, when present, has `agent` (a repo agent name) and optional `paths`. It
  runs in the same parallel round as reviewers and follows the same verdict
  contract. Running the real program is just one more check in the round, and
  this keeps the loop unchanged.
- `related` entries have `path` and `contract` (one line on what the other repo
  depends on). Any reviewer whose name starts with `contract` gets the related
  paths in its prompt.
- `models` keys are roles; `reviewers` sets the default for every reviewer, and
  a reviewer can override with its own `model`. Values map to the Agent tool's
  `model` and `effort`. A missing key means the agent file's frontmatter wins.
- `builder.runtime: claude` spawns `factory:builder` and resumes it with
  SendMessage, as today. `runtime: command` runs the command through Bash in
  the job worktree. The orchestrator writes the round's instructions to
  `jobs/<id>/builder-prompt-N.md` first and fills in the `{session}`,
  `{prompt_file}` and `{out_prefix}` placeholders. The builder's contract is
  the same either way: commit on the branch and append `## Round N` to
  `build.md`.
- Command runner contract: `{session}` is `factory-<job-id>`, the same every
  round when `resume: session` (the runner resumes by that id, as
  `pi_run.sh` does), and `factory-<job-id>-r<N>` when `resume: fresh`.
  `{out_prefix}` is `jobs/<id>/builder-r<N>`, where the runner may put logs.
  The orchestrator runs it in the background with no timeout of its own, and
  treats exit as done. Exit 0 counts only if the branch has a new commit and
  `build.md` has the `## Round N` section; anything else (non-zero exit, no
  commit, no section) sets stage `needs-human` with note "builder run
  failed", pointing at the `{out_prefix}` logs.
- `commands` is an open set. The builder runs every one and all must pass.
  Reviewers rerun `test` themselves, as today. After merging, the orchestrator
  reruns only the `merge_gate` keys (default `[test]`), so an expensive build
  is not repeated at merge.
- `scout` holds the repo-specific inputs the feature scout and foundations
  scout need (where to grep for TODOs, which docs hold later-milestone items,
  extra foundations checks). Setup writes it; the scouts read it instead of
  naming any repo's paths.

### The orchestrator (skills/factory/SKILL.md)

It is today's sc skill with every repo-specific value replaced by a read from
`factory.yaml`:

- Settings come from the YAML. If `factory/factory.yaml` is missing, every
  command except `setup` stops and says to run `/factory setup`.
- Review round N spawns the reviewers the YAML selects for this diff, plus QA,
  in one message. The round closes when every selected one has written its
  file. Skipped reviewers write nothing.
- The board's `reviews` map is keyed by reviewer name, not a fixed four. The
  dashboard reads the names from the board, not from a hardcoded list (today
  `REVIEWERS = ["security", "ux", "ui", "code"]`).
- The approver and arbiter get `rules`, `context`, `escalate`, and `commands`
  from the YAML in their prompt, instead of naming sc files.
- Commands keep their current names: `<feature>`, `next`, `scout`, `approve`,
  `rework`, `arbitrate`. New: `setup`, `scout foundations`, and `tune`.
- Plugin skills are namespaced, so each command is its own thin skill that
  loads the shared orchestrator text: `/factory:run <feature>`,
  `/factory:next`, `/factory:scout`, `/factory:approve`, `/factory:rework`,
  `/factory:arbitrate`, `/factory:setup`, `/factory:tune`. The shared loop
  lives in `skills/run/SKILL.md`; the others read it by relative path. The
  doc's `/factory <cmd>` spelling means these.

The generic agents (spec-writer, builder, approver, arbiter, scout) lose every
sc reference. Where they read `CLAUDE.md`, `.mex/AGENTS.md` or run
`buck2 test //...` today, they read the `context` list, the `rules` doc, and the
`commands` from the YAML, which the orchestrator passes as paths and values.
The rule that prompts contain paths and values, never conversation content,
stays.

### /factory setup

Drafts never touch the working tree. The survey, the proposed files and the
diff live in `.git/factory-setup/` (inside the git dir, so never committed and
never seen by builds), and are deleted after the owner approves or declines.

1. Spawn `factory:setup-surveyor` on the repo. It reads the repo and writes
   `.git/factory-setup/survey.md` with the facts setup needs, each with where it
   found them: the kind of software, languages, build, test, lint and CI
   commands (and whether each actually runs), rules docs, risk areas, existing
   agents and skills that drive the program (like `verify-sc`), how
   implementers run today (for example a `pi` runner), sibling repos that
   consume or serve this one, and the paths that split the code into areas.
2. The orchestrator turns the survey into a proposal: `factory.yaml` and every
   reviewer and QA agent file, each reviewer with a one-line reason. It shows
   the owner the lineup as a short table (reviewer, runs when, why), then the
   rest.
3. The owner approves or edits in chat. Setup writes nothing until then.
4. On approval, setup writes `factory/factory.yaml`, the agent files, and, if
   missing, `board.json` (empty jobs), `backlog.md`, `jobs/`, and
   `dashboard.html`.
5. Setup runs the foundations scout and shows its items as the "fix these
   first" list (below).

On a repo that already has `factory.yaml`, steps 1 to 3 run the same way, but
the proposal is a diff against the current YAML and agent files, with a reason
per change. Hand edits get no special protection: setup may propose to change
or remove them, and the diff shows when it is undoing one. Setup never touches
`board.json` contents, `jobs/`, or `backlog.md` items that already exist.

How setup chooses the lineup: always one reviewer for the repo's hard rules
(security for sc, invariants for pokerbot), one for logic, and one for
maintainability. Add interface reviewers by what the program's interface is:
for a CLI, one combined output-and-flow reviewer; for a web UI, separate visual
and interaction reviewers; for an HTTP API, a contract reviewer (reading
related repos when there are any). Add specialist reviewers, scoped by
`paths`, for areas with their own risk (experiment rigor for training code,
data correctness for a pipeline). Keep the lineup to what the survey can justify
with a fact; every reviewer needs a reason that names something in this repo.

### Foundations scout

`factory:foundations-scout` checks the repo for what the factory needs to judge
work, and writes `factory/scout.md` in the existing scout format with a
`Kind: foundations` line per item. Checklist:

- Tests: a suite exists, runs green, and covers the areas named in the risks.
- Lint and format: a command exists and passes.
- Rules: the rules doc exists and is filled in (not the template).
- QA: some way to drive the real program, and a `qa` entry using it.
- CI: CI runs the same commands as `factory.yaml`.
- Area-specific checks setup records from the survey (for sc: parsers without
  fuzz targets).

Each item must be finishable in one job and name the file or command. Approved
items go to the top of `backlog.md` under `## Foundations`, so `/factory next`
takes them before feature work. `/factory scout` keeps its current meaning
(features); `/factory scout foundations` runs this one.

When `commands.test` is missing or has no real tests, setup says so in the
proposal, and the approver's prompt states that the repo has no test suite, so
it must escalate any change whose correctness it cannot check another way.

### /factory tune

Setup answers "what factory fits this code?". Tune answers "how is this factory
doing, and what should change?". It reads what setup cannot: how the factory has
actually performed.

`factory:tuner` reads `factory.yaml`, the agent files, `board.json`, every job
folder, `backlog.md`, and the repo's current state, and writes
`factory/tune.md`. Each suggestion has a kind, the change, and the evidence
(job ids, file paths, counts). What it looks for:

- **Reviewers that never catch anything.** A reviewer with no `CHANGES` across
  many jobs, or whose findings the builder always waves off, may be cut, merged,
  or scoped with `paths`.
- **Gaps in reviewers.** Defects found late (by the approver, the arbiter, QA,
  or a later job's fix) that no reviewer flagged. Suggest a checklist line or a
  new reviewer.
- **Repeated findings.** The same finding in three or more jobs. Suggest
  encoding it so it cannot recur (a lint, a test, a type, a rules-doc entry), as
  a backlog item, instead of reviewers catching it forever.
- **Convergence.** Jobs that hit `max_rework`, rounds where reviewers
  contradicted each other, and recurring escalation reasons. Suggest spec-writer
  changes, a sharper checklist, or an `escalate` entry.
- **Arbiter outcomes.** If the arbiter keeps choosing `ACCEPT` for one kind of
  escalation, the `escalate` rule is too broad; if the owner keeps overruling
  it, its prompt or the rules doc is missing something.
- **Drift from the code.** New top-level areas no path-scoped reviewer covers,
  commands that no longer run, a QA skill that now exists but is not wired in,
  rules-doc changes since setup.
- **Cost.** Expensive reviewers (high-effort models, slow QA) on jobs where they
  never find anything. Suggest a cheaper model or `paths`.
- **Foundations still open.** Foundations items still unchecked in the backlog.

The orchestrator shows the suggestions ranked by expected impact. The owner
picks which to apply. Settings and agent changes go through the same
diff-and-approve path as rerunning setup; backlog items are appended like
scout items. Tune writes nothing else. With fewer than three finished jobs,
tune says the record is too thin and only reports drift and open foundations.

### Migration of sc

Migration is part of this build, but it waits. As of 2026-11-03 a ralph loop
in `~/sc` ("continue to implement m2 using the factory") drives the repo-local
factory, and its skill, arbiter, board and backlog are uncommitted and still
changing. Sequencing:

- Build and test the plugin entirely in `~/plugins`, without editing `~/sc`.
  The plugin's arbiter and arbitration flow are copied from sc's working files
  as they stand when the plugin build starts; the copy is refreshed from sc
  again just before migration.
- Migration starts only after the owner has stopped the loop and the sc
  factory work is committed on a branch. The migration step first checks that
  `factory/.claude/ralph-loop.local.md` is absent or `active: false`, that the
  sc checkout is clean, and that no job is at stage `spec`, `build`, `review`,
  `approval` or `arbitration`. If any check fails it stops and says which.
- Jobs at `needs-human` or `merged` migrate as they are.

Steps:

1. Write sc's `factory/factory.yaml` by running setup on sc. The expected
   lineup is security, logic, maintainability, and one CLI output-and-flow
   reviewer, with `qa` using `verify-sc` (via a `factory-qa` agent that runs its
   `scv` script). The owner approves it like any other proposal.
2. Board history keeps its old reviewer keys (`security`, `ux`, `ui`, `code`).
   The dashboard shows whatever keys each round has, so old rounds still render.
3. Remove sc's copies: `.claude/skills/factory/` and the `.claude/agents/`
   files the plugin now provides. The uncommitted arbiter work in sc
   (`arbiter.md` and the arbitration section of `SKILL.md`, as of 2026-11-03)
   moves into the plugin as written, minus sc references. It must be committed
   or carried over before the sc copies are removed.
4. Job 007-commit-signing (stage `needs-human`) must still work with
   `/factory arbitrate`, `approve`, and `rework` after migration.

Then pokerbot: run setup, approve, run the foundations scout, take one job
through the loop with the `pi` builder.

## Decided by the owner

- Setup proposes a lineup the owner approves or edits. Nothing is written first.
- Setup proposes the whole factory, not only reviewers: commands, QA,
  escalation, and the rest.
- It must work on other repos; pokerbot is next.
- A scout-like step checks repos for gaps to fill.
- The setup result is overridable through a structured file; YAML.
- Setup may rewrite the YAML later.
- sc migration is part of this build, after the ralph loop in sc ends and its
  factory work is committed.
- A skill looks at the project's current state and the factory settings and
  suggests improvements (`/factory tune`).
- The work lives in a new `factory/` folder in the `zfdupont/plugins` repo,
  cloned to `~/plugins`.

## Calls made by Claude (owner to check)

- Reviewer checklists live in repo agent files, not in the YAML.
- Reviewers and QA are repo agents; the plugin ships none.
- QA runs inside the review round under the same verdict contract, not as its
  own stage.
- Path-scoped reviewers, with skipped ones shown as `skipped` on the board.
- `builder.runtime: command` with placeholders, so pokerbot's `pi` runner works
  without plugin changes.
- Rerunning setup gives hand edits no special protection; the diff is the
  safeguard.
- Foundations items go at the top of the backlog.
- v1 has no pstack dependency and no parallel jobs.
- Setup drafts live in `.git/factory-setup/`, not the working tree.
- One thin skill per command (`/factory:setup`, `/factory:next`, ...).
- `commands` is an open set; `merge_gate` (default `[test]`) is what reruns
  after merge.
- A `scout` key in the YAML holds repo-specific scout inputs.
- The command-runner contract above (session ids, log prefix, done means a
  new commit plus the build.md section).

## Left to the builder

- Exact `factory.yaml` validation: what the orchestrator does with an unknown
  key or a reviewer whose agent file is missing (suggested: stop and name it).
- Glob matching for `paths` (suggested: plain shell-style globs checked by a
  small script the skill ships, not by the model).
- Dashboard changes for dynamic reviewer names and the `skipped` state.
- Wording of the setup proposal table and diff.
- The `setup-surveyor` and `foundations-scout` prompts, within the checklists
  above.
- Plugin README and the marketplace entry.
