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
| `builder-done <worktree> <before_sha> <build_md> <round>` | `done` and exit 0, or the reason and exit 1 |
| `migration-check <repo>` | `ok` and exit 0, or one line per blocker and exit 1 |

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
| `commands` | map name to shell command | required, non-empty | open set; the builder runs every one and all must pass |
| `merge_gate` | list of `commands` keys | `[test]` if `test` exists, else `[]` | what the orchestrator reruns on `base` after a merge |
| `scout` | map | `{}` | `todo_paths` (list), `docs` (list), `checks` (list of one-line foundations checks) |
| `builder` | map | `{runtime: claude, resume: session}` | see Builder |
| `reviewers` | list | required, non-empty | see Reviewers |
| `qa` | `null` or map | `null` | `agent` (repo agent name), optional `paths` |
| `escalate` | list of strings | `[]` | the approver escalates on any of these, even when reviews pass |
| `related` | list of `{path, contract}` | `[]` | sibling repos; reviewers named `contract*` get them in their prompt |
| `models` | map role to `<model> [effort]` | `{}` | roles: `spec-writer`, `builder`, `reviewers`, `approver`, `arbiter`, `scout`, `setup-surveyor`, `foundations-scout`, `tuner`; model is `opus`, `sonnet`, `haiku`, `fable` or `inherit`; effort is `low`, `medium`, `high`, `xhigh` or `max` |

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
| `name` | matches `^[a-z][a-z0-9-]*$`, unique; the agent is `.claude/agents/factory-review-<name>.md` and writes `round-N/review-<name>.md` |
| `why` | one line naming what in this repo makes the reviewer worth running |
| `paths` | optional globs; without it the reviewer runs every round |
| `model` | optional `<model> [effort]`, overrides `models.reviewers` |

A reviewer with `paths` runs only when a file in
`git diff --name-only <base>...<head>` matches one of them. QA follows the same
rule with `qa.paths`, runs in the same round, and writes `round-N/review-qa.md`.

Glob rules, matched against the whole path:

- a pattern ending in `/` matches any path under that directory (`web/`);
- `**` matches any characters, including `/`;
- `*` matches any characters except `/`;
- `?` matches one character except `/`;
- everything else is literal.

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
  - adds a dependency, changes the build toolchain, or deletes tests
related: []
models:
  reviewers: sonnet high
  approver: opus high
  arbiter: opus max
```
