# Factory Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn sc's repo-local software factory into a `factory` plugin in `zfdupont/plugins` that any repo can adopt through `/factory:setup`, improve through `/factory:tune`, and override through `factory/factory.yaml`.

**Architecture:** Prose skills and agents carry the loop, as today in sc. Everything deterministic (reading and validating `factory.yaml`, picking reviewers by changed paths, checking a builder run finished, the migration precondition) lives in one tested Python script the skills call, so the model never parses YAML or matches globs itself. Per-repo reviewers are repo agent files that setup writes from a shipped template.

**Tech Stack:** Claude Code plugin (skills, agents, `.claude-plugin/plugin.json`), Python 3.10+ run with `uv run --script` (inline dependency `pyyaml`), pytest, plain HTML/JS dashboard.

**Spec:** `factory/docs/specs/2026-11-03-factory-plugin-design.md`

## Global Constraints

- Nothing in `factory/` names a specific repo's commands, paths, rules or reviewers. sc, pokerbot and huskies appear only in docs and test fixtures.
- Setup and tune write nothing in the working tree before the owner approves; drafts go in `.git/factory-setup/`.
- The factory never pushes, and only `/factory:approve` merges a job that escalated.
- Agents get paths and values in their prompts, never conversation content; each agent writes only its own file.
- First lines: reviews `VERDICT: PASS` or `VERDICT: CHANGES`; `decision.md` `APPROVE` or `ESCALATE`; `resolution.md` `ACCEPT`, `REWORK` or `OWNER`.
- Board stages, in order: `spec`, `build`, `review`, `approval`, `arbitration`, `needs-human`, `merged`. Verdicts: `pending`, `PASS`, `CHANGES`, `skipped`.
- Defaults: `max_rework: 2`, `max_arbiter_rework: 1`, `merge_gate: [test]` when `commands.test` exists, else `[]`.
- Do not edit anything under `~/sc` until Task 12, and Task 12 runs only after `migration-check` passes.
- Commit messages are brief, with no Co-Authored-By or other attribution lines (owner's global CLAUDE.md).
- Script runs as `uv run --script factory/skills/run/scripts/factory_config.py <cmd> ...`; tests run as `uv run --with pytest --with pyyaml pytest factory/tests -q` from `~/plugins`.

## Review Focus

1. A `factory.yaml` hand-edited into a bad state (typo in a key, reviewer with no agent file, `merge_gate` naming a missing command): the orchestrator stops and names the problem instead of running a partial round. Pinned in Task 2.
2. A diff where every path-scoped reviewer is skipped and only `always` reviewers run, or a reviewer's `paths` uses a directory prefix like `web/`: selection still matches what a person reading the YAML expects. Pinned in Task 3.
3. A command builder that exits 0 but made no commit, or committed without the `## Round N` section: the job stops at `needs-human`, not review. Pinned in Task 4.
4. An old board whose rounds use `security`/`ux`/`ui`/`code` next to new rounds with other names: the dashboard renders both. Pinned in Task 7.
5. A repo with no real test suite: setup says so, and the approver's prompt tells it to escalate changes it cannot check. Pinned in Tasks 6 and 8.

---

## File structure

```
factory/
  .claude-plugin/plugin.json
  README.md
  skills/
    run/SKILL.md                 shared loop + /factory:run <feature>
    run/schema.md                factory.yaml reference
    run/dashboard.html           copied into <repo>/factory/ by setup
    run/scripts/factory_config.py
    next/SKILL.md  scout/SKILL.md  approve/SKILL.md  rework/SKILL.md
    arbitrate/SKILL.md  setup/SKILL.md  tune/SKILL.md
    setup/reviewer-template.md   shape of a factory-review-<name>.md
  agents/
    spec-writer.md builder.md approver.md arbiter.md scout.md
    foundations-scout.md setup-surveyor.md tuner.md
  tests/
    conftest.py                  fixture repo builder
    test_factory_config.py
  docs/specs/  docs/plans/
.claude-plugin/marketplace.json  (modify: add factory entry)
README.md                        (modify: add factory row)
```

---

### Task 1: Plugin skeleton

**Files:**
- Create: `factory/.claude-plugin/plugin.json`, `factory/README.md`
- Modify: `.claude-plugin/marketplace.json`, `README.md`

**Interfaces:**
- Produces: plugin name `factory`, version `0.1.0`; marketplace entry `{"name": "factory", "source": "./factory", "version": "0.1.0", "category": "development"}`.

- [ ] **Step 1:** Write `plugin.json` following `pstack/.claude-plugin/plugin.json` (name, version `0.1.0`, description, author `zfdupont`, homepage `https://github.com/zfdupont/plugins/tree/main/factory`, repository, license `MIT`, keywords).
- [ ] **Step 2:** Add the marketplace entry and a README row: "`factory` | A spec-to-merge software factory you set up per repo. Start with `/factory:setup`."
- [ ] **Step 3:** `factory/README.md`: what it is, the command list (`/factory:setup`, `/factory:run <feature>`, `/factory:next`, `/factory:scout [foundations]`, `/factory:approve <id>`, `/factory:rework <id> <note>`, `/factory:arbitrate <id>`, `/factory:tune`), install lines matching the root README.
- [ ] **Step 4:** Run `claude plugin validate ./factory` and `claude plugin validate .`. Expected: both report valid.
- [ ] **Step 5:** Commit: `git add factory/.claude-plugin factory/README.md .claude-plugin/marketplace.json README.md && git commit -m "Add factory plugin skeleton"`

### Task 2: `factory_config.py` load, validate, get

**Files:**
- Create: `factory/skills/run/scripts/factory_config.py`, `factory/skills/run/schema.md`, `factory/tests/conftest.py`, `factory/tests/test_factory_config.py`

**Interfaces:**
- Produces (CLI; all paths absolute or relative to cwd):
  - `validate <repo>`: exit 0 and prints `ok`; else exit 1, one line per problem, each starting `factory.yaml: `.
  - `get <repo> <dotted.key>`: prints the value as JSON with defaults applied (`builder.runtime`, `commands`, `merge_gate`); missing key prints `null`.
  - Python: `load(repo: Path) -> dict` (defaults applied), `validate(repo: Path) -> list[str]`.
- Script header: `#!/usr/bin/env -S uv run --script` with a PEP 723 block, `requires-python = ">=3.10"`, `dependencies = ["pyyaml"]`.
- Fixture: `make_repo(tmp_path, yaml_text: str, agents: list[str]) -> Path` in `conftest.py` creates `factory/factory.yaml` and `.claude/agents/<name>.md` files.

Validation rules (put the same table in `schema.md`, with every key from the spec's YAML example and its default):

| Key | Rule |
|---|---|
| top level | only `version base max_rework max_arbiter_rework worktrees context rules commands merge_gate scout builder reviewers qa escalate related models` |
| `version` | must be `1` |
| `base` | required string |
| `commands` | required mapping of name to non-empty string |
| `merge_gate` | every entry is a key of `commands` |
| `builder.runtime` | `claude` (default) or `command`; `command` requires `builder.command` containing `{prompt_file}`; `resume` is `session` (default) or `fresh` |
| `reviewers` | non-empty list; `name` matches `^[a-z][a-z0-9-]*$` and is unique; `why` required; `paths` optional list of strings; `.claude/agents/factory-review-<name>.md` exists |
| `qa` | null or `{agent, paths?}`; `.claude/agents/<agent>.md` exists |
| `models` | values match `^(opus|sonnet|haiku|fable|inherit)( (low|medium|high|xhigh|max))?$` |
| `related` | list of `{path, contract}` |

- [ ] **Step 1: Write the failing tests**

```python
def test_valid_minimal_config(tmp_path):
    repo = make_repo(tmp_path, MINIMAL, agents=["factory-review-logic"])
    assert validate(repo) == []
    cfg = load(repo)
    assert cfg["max_rework"] == 2 and cfg["max_arbiter_rework"] == 1
    assert cfg["merge_gate"] == ["test"]
    assert cfg["builder"] == {"runtime": "claude", "resume": "session"}

def test_unknown_key_named(tmp_path):      # Review Focus 1
    repo = make_repo(tmp_path, MINIMAL + "reviewrs: []\n", agents=["factory-review-logic"])
    assert "factory.yaml: unknown key 'reviewrs'" in validate(repo)

def test_reviewer_without_agent_file(tmp_path):
    repo = make_repo(tmp_path, MINIMAL, agents=[])
    assert "factory.yaml: reviewer 'logic' has no .claude/agents/factory-review-logic.md" in validate(repo)

def test_merge_gate_names_missing_command(tmp_path):
    repo = make_repo(tmp_path, MINIMAL + "merge_gate: [lint]\n", agents=["factory-review-logic"])
    assert "factory.yaml: merge_gate 'lint' is not in commands" in validate(repo)

def test_command_runtime_needs_prompt_placeholder(tmp_path): ...
    # builder: {runtime: command, command: "run.sh"} -> "factory.yaml: builder.command must contain {prompt_file}"

def test_no_test_command_gives_empty_merge_gate(tmp_path): ...
    # commands: {build: make} -> load()["merge_gate"] == []

def test_get_cli_prints_json(tmp_path): ...
    # subprocess `get <repo> builder.runtime` -> stdout '"claude"\n'; `get <repo> nope` -> 'null\n'

def test_missing_file(tmp_path): ...
    # no factory/factory.yaml -> ["factory.yaml: not found; run /factory:setup"]
```

`MINIMAL` is `version: 1\nbase: main\ncommands: {test: pytest}\nreviewers:\n  - {name: logic, why: x}\n`.

- [ ] **Step 2:** Run the tests. Expected: FAIL (module not found).
- [ ] **Step 3:** Implement `load`, `validate`, and the `validate`/`get` subcommands with `argparse`. `load` on a missing file raises; `validate` returns the not-found message instead.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "Add factory.yaml loader and validator"`

### Task 3: Reviewer selection by changed paths

**Files:**
- Modify: `factory/skills/run/scripts/factory_config.py`, `factory/tests/test_factory_config.py`

**Interfaces:**
- Produces: `select <repo> <base> <head>` prints `{"run": [...], "skipped": [...]}`, names in YAML order, with `"qa"` last in whichever list applies. Python: `select(cfg: dict, changed: list[str]) -> dict` and `glob_match(pattern: str, path: str) -> bool`. Changed files come from `git -C <repo> diff --name-only <base>...<head>`.

Glob rules (document in `schema.md`): a pattern ending in `/` matches any path under that directory; `**` matches any characters including `/`; `*` matches any characters except `/`; `?` matches one character except `/`; anything else is literal. Match against the whole path.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("pat,path,ok", [
    ("web/**", "web/app.py", True),
    ("web/**", "webapp/x.py", False),
    ("web/", "web/a/b.py", True),
    ("scripts/train_*", "scripts/train_cfr.py", True),
    ("scripts/train_*", "scripts/sub/train_x.py", False),
    ("**/*.cpp", "common/src/game/card.cpp", True),
])
def test_glob_match(pat, path, ok):
    assert glob_match(pat, path) is ok

def test_select_skips_unmatched_scoped_reviewers():          # Review Focus 2
    cfg = {"reviewers": [{"name": "logic"}, {"name": "api", "paths": ["web/**"]}], "qa": None}
    assert select(cfg, ["cfr/a.py"]) == {"run": ["logic"], "skipped": ["api"]}

def test_select_qa_last():
    cfg = {"reviewers": [{"name": "logic"}], "qa": {"agent": "factory-qa"}}
    assert select(cfg, ["x"]) == {"run": ["logic", "qa"], "skipped": []}

def test_select_cli_uses_git_diff(tmp_path): ...
    # fixture repo with a commit on a branch touching web/app.py -> "api" in run
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `glob_match` by translating the pattern to a regex per the rules, and `select`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "Select reviewers by changed paths"`

### Task 4: Builder-run and migration checks

**Files:**
- Modify: `factory/skills/run/scripts/factory_config.py`, `factory/tests/test_factory_config.py`

**Interfaces:**
- Produces:
  - `builder-done <worktree> <before_sha> <build_md> <round>`: exit 0 printing `done` only if `git -C <worktree> rev-list <before_sha>..HEAD` is non-empty and `build_md` has a line exactly `## Round <round>`; else exit 1 with `no new commit` or `build.md has no ## Round <round>`.
  - `migration-check <repo>`: exit 0 printing `ok`; else exit 1, one line per failure: `ralph loop active (factory/.claude/ralph-loop.local.md)` when that file exists with `active: true` in its frontmatter; `working tree not clean`; `job <id> in flight at stage <stage>` for each board job at `spec`, `build`, `review`, `approval` or `arbitration`.

- [ ] **Step 1: Write the failing tests**

```python
def test_builder_done_needs_commit(tmp_path):                 # Review Focus 3
    wt, before = git_repo_with_commit(tmp_path)
    (tmp_path / "build.md").write_text("## Round 1\n")
    assert run_cli("builder-done", wt, before, tmp_path / "build.md", "1").stdout.strip() == "no new commit"

def test_builder_done_needs_round_section(tmp_path): ...       # commit made, build.md has "## Round 0" -> exit 1
def test_builder_done_ok(tmp_path): ...                        # commit + "## Round 2" for round 2 -> "done"
def test_migration_check_flags_active_loop(tmp_path): ...
def test_migration_check_flags_in_flight_job(tmp_path): ...    # board job at "review" -> "job 003-x in flight at stage review"
def test_migration_check_ok_with_needs_human_and_merged(tmp_path): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement both subcommands.
- [ ] **Step 4:** Run the whole suite. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "Add builder-done and migration checks"`

### Task 5: Generic agents

**Files:**
- Create: `factory/agents/spec-writer.md`, `builder.md`, `approver.md`, `arbiter.md`, `scout.md`
- Sources (read only): `~/sc/.claude/agents/{spec-writer,builder,approver,arbiter,scout}.md` as they are in the working tree when this task starts.

**Interfaces:**
- Consumes: the prompt values the orchestrator passes (Task 6): job folder, worktree, branch, base, round, and from `factory.yaml` the `context` paths, `rules` path, `commands` mapping, `escalate` list, `scout` block, and a `no_tests: true` flag when `commands` has no `test`.
- Produces: the same output files and first-line contracts as sc's agents.

- [ ] **Step 1:** Port each agent keeping its structure and contracts. Replace every sc-specific item with the passed value: `CLAUDE.md`/`.mex/...` reads become "read every path in `context`, and the rules doc at `rules`"; `buck2 test //...` and `./scripts/lint.sh` become "run every command in `commands`"; the approver's sensitive-area list becomes "the `escalate` list"; the scout's search list reads `scout.todo_paths` and `scout.docs`; the builder's GoogleTest and `defs.bzl` lines become "write a test for each acceptance criterion in the repo's existing test framework and layout". Drop `model:` frontmatter lines (models come from `factory.yaml`, with the agent default left to the parent model).
- [ ] **Step 2:** Approver: add "If the prompt says `no_tests: true`, the repo has no test suite: ESCALATE any change whose correctness you cannot check by running it or reading it." (Review Focus 5.)
- [ ] **Step 3:** Arbiter: also replace its sc reads (`docs/specs/`, `docs/plans/2026-10-28-m3-use-cases.md`) with the `context` paths.
- [ ] **Step 4:** Verify: `grep -nE 'buck2|libsodium|libgit2|GoogleTest|defs\.bzl|refs/sc|sc: |\.mex/|SC_HOME|\bsc\b' factory/agents/*.md` prints nothing, and `claude plugin validate ./factory` passes.
- [ ] **Step 5:** Commit: `git commit -m "Port factory agents without repo specifics"`

### Task 6: Orchestrator and command skills

**Files:**
- Create: `factory/skills/run/SKILL.md`, `factory/skills/{next,scout,approve,rework,arbitrate}/SKILL.md`
- Source (read only): `~/sc/.claude/skills/factory/SKILL.md` working tree.

**Interfaces:**
- Consumes: Task 2-4 subcommands, Task 5 agent names (`factory:spec-writer`, `factory:builder`, `factory:approver`, `factory:arbiter`, `factory:scout`), repo agents `factory-review-<name>` and `qa.agent`.
- Produces: `run/SKILL.md` sections the thin skills point to by name: `## Setup check`, `## /factory:run`, `## Review round N`, `## Approval`, `## Arbitration`, `## Merge`, `## next`, `## scout`, `## approve`, `## rework`, `## arbitrate`, `## Rules`.

- [ ] **Step 1:** Port sc's skill into `run/SKILL.md`, with every Settings line replaced by values read through `factory_config.py get`. Add `## Setup check`: run `validate`. On a non-zero exit, print its lines and stop (Review Focus 1). With no file, say to run `/factory:setup`.
- [ ] **Step 2:** Review round: call `select <repo> <base> factory/<id>`, spawn every `run` name in one message (reviewer `r` is agent `factory-review-<r>`, writing `round-N/review-<r>.md`; QA is `qa.agent`, writing `round-N/review-qa.md`), and set each `skipped` name to `skipped` on the board. The round closes when every `run` file exists.
- [ ] **Step 3:** Builder step: for `runtime: claude`, spawn and resume `factory:builder` as sc does. For `runtime: command`, record `git rev-parse HEAD` in the worktree, write `jobs/<id>/builder-prompt-<N>.md`, and fill in `{session}`, `{prompt_file}` and `{out_prefix}` per the spec. Run it in the background from the worktree, then call `builder-done`. On failure, stage `needs-human`, note "builder run failed", and point at `jobs/<id>/builder-r<N>*`.
- [ ] **Step 4:** Spawns pass `model`/`effort` from `models` (role keys `spec-writer`, `builder`, `reviewers`, `approver`, `arbiter`, `scout`, and a per-reviewer `model` override). Merge runs only the `merge_gate` commands. Worktrees go under `worktrees` (default `../<repo-dir-name>-factory`). Reviewers whose name starts with `contract` also get every `related` entry (`path` and `contract`) in their prompt. Approver and arbiter prompts carry `rules`, `context`, `escalate`, `commands`, and `no_tests: true` when `commands` has no `test`.
- [ ] **Step 5:** Each thin skill: frontmatter `name` and a description naming its command, then "Read `../run/SKILL.md` relative to this skill's base directory, run `## Setup check`, then follow `## <section>` with these arguments: `$ARGUMENTS`." `scout` routes `foundations` to the setup skill's foundations section (Task 8).
- [ ] **Step 6:** Verify: the Task 5 grep over `factory/skills/` prints nothing outside `schema.md` examples, and `claude plugin details ./factory` lists all eight skills and eight agents once Tasks 8 and 9 land. For now, it lists six skills and five agents.
- [ ] **Step 7:** Commit: `git commit -m "Add factory orchestrator and command skills"`

### Task 7: Dashboard with dynamic reviewers

**Files:**
- Create: `factory/skills/run/dashboard.html` (from `~/sc/factory/dashboard.html` working tree)
- Create: `factory/tests/fixtures/board-mixed.json`

**Interfaces:**
- Consumes: `board.json` as in the spec; `reviews` values may be `skipped`.

- [ ] **Step 1:** Write `board-mixed.json`: one job whose `history` has round 1 with keys `security ux ui code`, and whose current round has `security logic maintainability cli` with `cli: "skipped"`. Add a second job at `arbitration`.
- [ ] **Step 2:** Replace `const REVIEWERS = [...]` with per-row names: each round row shows that round's own keys in their stored order. Style `skipped` as a muted chip labelled `skip`. Make sure the `arbitration` stage has a column.
- [ ] **Step 3:** Verify: copy the fixture to `board.json` next to the dashboard in a scratch dir, serve it with `python3 -m http.server`, and open it in the built-in browser. Expected: both rows render with their own chips, the skipped chip is muted, and both jobs show in their stage columns (Review Focus 4).
- [ ] **Step 4:** Commit: `git commit -m "Factory dashboard reads reviewer names from the board"`

### Task 8: Setup and the foundations scout

**Files:**
- Create: `factory/skills/setup/SKILL.md`, `factory/skills/setup/reviewer-template.md`, `factory/agents/setup-surveyor.md`, `factory/agents/foundations-scout.md`

**Interfaces:**
- Consumes: `validate`, the dashboard (Task 7), `factory:scout`'s `scout.md` format.
- Produces: `/factory:setup`, `## Foundations` section (used by `/factory:scout foundations`), and survey file `.git/factory-setup/survey.md` with headings `## Kind`, `## Languages`, `## Commands` (each with "runs: yes/no" and the output tail), `## Rules docs`, `## Risks`, `## Program drivers`, `## Builder today`, `## Related repos`, `## Areas`, `## Gaps`.

- [ ] **Step 1:** `setup-surveyor.md`: reads the repo and writes only the survey, citing a file for every fact. It runs each candidate command once to fill "runs". Tools: Read, Grep, Glob, Bash, Write.
- [ ] **Step 2:** `reviewer-template.md`: frontmatter (`name: factory-review-<name>`, `description`, `tools: Read, Grep, Glob, Bash, Write`). Inputs line, a "Read" block, a "Check" list (setup fills it from the survey), and a "Write" block with the verdict contract and `file:line` findings. Include the QA variant (`factory-qa`, which runs the program driver).
- [ ] **Step 3:** `setup/SKILL.md`, following the spec's `/factory setup` section:
  - survey;
  - draft `factory.yaml` and agent files in `.git/factory-setup/proposed/`;
  - show the lineup table (reviewer, runs when, why), then the rest;
  - on a rerun, show `diff -ru` against the current files with a reason per change;
  - write only after the owner approves;
  - then run `validate` and copy in `dashboard.html`, plus an empty board, `backlog.md` and `jobs/` if missing;
  - delete `.git/factory-setup/`.

  Include the spec's lineup rules verbatim. If the survey shows no runnable `test` command, the proposal states "no test suite" first (Review Focus 5).
- [ ] **Step 4:** `foundations-scout.md` and `## Foundations`: the spec's checklist plus `scout.checks`. It writes `factory/scout.md` items with `Kind: foundations`. Approved items go under `## Foundations` at the top of `backlog.md`.
- [ ] **Step 5:** Verify on a fixture: create a scratch repo with `pyproject.toml`, one module, a pytest test and a `README.md`. Run `claude -p --plugin-dir ~/plugins/factory "/factory:setup This is a test fixture; I approve the proposal as written."` there. Expected: `factory/factory.yaml` passes `validate`, at least a logic and a maintainability reviewer file exist, `.git/factory-setup/` is gone, and the output lists foundations items that include a missing lint command.
- [ ] **Step 6:** Commit: `git commit -m "Add factory setup and foundations scout"`

### Task 9: Tune

**Files:**
- Create: `factory/skills/tune/SKILL.md`, `factory/agents/tuner.md`

**Interfaces:**
- Consumes: board, job folders, `factory.yaml`, agent files, `backlog.md`; the setup skill's diff-and-approve steps (it references Task 8's section by name instead of repeating them).
- Produces: `factory/tune.md`. Each item has `Kind:` (one of `cut-reviewer`, `reviewer-gap`, `repeated-finding`, `convergence`, `arbiter`, `drift`, `cost`, `foundations`), `Change:`, `Evidence:` (job ids, paths, counts) and `Impact:` (`high`, `medium` or `low`).

- [ ] **Step 1:** `tuner.md`: the spec's checklist, with "fewer than three finished jobs: report only `drift` and `foundations`". It writes only `factory/tune.md`.
- [ ] **Step 2:** `tune/SKILL.md`:
  - run `## Setup check`;
  - spawn the tuner;
  - show items ranked by impact as one multi-select question;
  - send chosen settings and agent changes through setup's diff-and-approve section;
  - append chosen backlog items.
- [ ] **Step 3:** Verify: in the Task 8 fixture, copy in `~/sc/factory/jobs/001-version` and `002-status-json` with matching board entries, and run `claude -p --plugin-dir ~/plugins/factory "/factory:tune"`. Expected: `tune.md` exists, says the record is thin (2 jobs), and has only `drift` or `foundations` items.
- [ ] **Step 4:** Commit: `git commit -m "Add factory tune"`

### Task 10: End-to-end trial on the fixture

**Files:** none in the plugin unless the trial finds defects (fix them in the task that owns the file).

- [ ] **Step 1:** In the Task 8 fixture, run `claude -p --plugin-dir ~/plugins/factory "/factory:run add a --version flag to the CLI"`.
- [ ] **Step 2:** Expected: the job reaches `merged` or `needs-human`; `board.json` records one review file per `run` reviewer per round and `skipped` for the rest; the merge commit is on `main`; nothing was pushed (`git log origin/main` absent or unchanged).
- [ ] **Step 3:** Repeat with `builder.runtime: command` pointing at a two-line stub runner that commits nothing. Expected: stage `needs-human`, note "builder run failed".
- [ ] **Step 4:** `claude plugin validate .` passes. Commit any fixes: `git commit -m "Fix issues found in factory trial"`

### Task 11: pokerbot (owner in the loop)

- [ ] **Step 1:** The owner installs the plugin locally (`/plugin marketplace add ~/plugins` or `--plugin-dir`) and runs `/factory:setup` in `~/pokerbot`. Expected: a proposal with an invariants reviewer, `builder.runtime: command` using `scripts/pi_run.sh`, and `qa: null` flagged as a gap. The owner approves or edits it.
- [ ] **Step 2:** `/factory:scout foundations`; the owner picks items.
- [ ] **Step 3:** `/factory:next` on one item. Expected: the `pi` builder runs, `builder-done` passes, and the review round runs only the selected reviewers.

### Task 12: Migrate sc (after the loop ends)

- [ ] **Step 1:** Run `uv run --script ~/plugins/factory/skills/run/scripts/factory_config.py migration-check ~/sc`. Expected: `ok`. If not, stop and report the lines. Do not touch sc.
- [ ] **Step 2:** Diff sc's working `arbiter.md` and factory `SKILL.md` against the versions Task 5 and Task 6 started from. Port any changes into the plugin and commit there.
- [ ] **Step 3:** In sc, on a new branch, run `/factory:setup`. Expected: lineup of security, logic, maintainability and a CLI output-and-flow reviewer, plus `qa` with a `factory-qa` agent that runs `.claude/skills/verify-sc/scv`. The owner approves.
- [ ] **Step 4:** Remove `~/sc/.claude/skills/factory/` and the sc agents the plugin replaces (`spec-writer builder approver arbiter scout review-*`). Keep `factory/board.json`, `jobs/` and `backlog.md`.
- [ ] **Step 5:** Expected: the dashboard renders old rounds with their old keys, and `/factory:arbitrate 007-commit-signing` (or `approve`/`rework`, the owner's choice) works on the existing job.
- [ ] **Step 6:** Run `buck2 test //...` in sc. Expected: pass. Commit in sc: `git commit -m "Move factory to the factory plugin"`. Never push.
