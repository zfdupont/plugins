---
name: setup-pstack
description: Configure which models pstack uses per role and at what reasoning budget. Detects your available models and writes a rule file Claude Code loads into every session, overriding the skill defaults. Use for /setup-pstack, "configure pstack models", "pstack budget", or changing pstack's model choices.
---

# Setup pstack

In Codex (you have `spawn_agent`, not `Agent`), first read `../poteto-mode/references/runtimes.md`, resolved against this skill's base directory. It maps this skill's Claude Code tools, model names and paths.

Write `~/.claude/rules/pstack-models.md`, a rule file that sets pstack's model per role. Claude Code loads every `.md` file in `~/.claude/rules/` into each new session, so the role lines are always in context. Never put the role lines in `CLAUDE.md` or `AGENTS.md`.

## Steps

### 1. Detect available models

Read the `model` values the `Agent` tool schema lists (normally `opus`, `sonnet`, `haiku`, `fable`) and the `effort` values it accepts (`low`, `medium`, `high`, `xhigh`, `max`). Write each real model as `<model> <effort>`, such as `opus xhigh`. The effort is the last token. The aliases `inherit-parent` and `auto` are always valid. Both mean: omit `model`, so the role runs on the session model.

Then check for Codex. In Codex, skip this check, because its models are already the ones `spawn_agent` lists. In Claude Code, load `mcp__t3-code__orchestrator_capabilities` with `ToolSearch`. If it loads, call it and take the provider with `driverKind: "codex"` and `canRunChildTask: true`. Write each of its models as `codex:<model-id> <effort>`, such as `codex:gpt-6.2-sol high`, with the efforts its `reasoningEffort` option lists. Among them, find its most capable model (the Codex frontier model) and its general coding model. If you cannot tell them apart, ask. If the tool does not load or no Codex provider can run a child, Codex is not available: skip step 3 (b) and offer no `codex:` values. A `codex:` seat runs through T3 `delegate_task`, per `../poteto-mode/references/codex-delegates.md`.

### 2. Load current state

The default role-to-model mapping is the file shape shown in step 5 below. If `~/.claude/rules/pstack-models.md` already exists, read it and treat its `# budget` and `# providers` lines and its role values as the current choices. Otherwise start from those defaults. A line whose role is not in step 5, such as `how critics`, is from a retired role. Drop it.

### 3. Budget, map, and confirm

**(a) Ask for a budget.** Prefer `AskUserQuestion` over free text. Offer these four options with these exact labels, and name the current budget when the file records one. With no file, say that `large` matches the skill defaults.

- `unlimited — max reasoning`
- `large — xhigh reasoning`
- `medium — high reasoning`
- `small — medium reasoning`

**(b) Ask for a provider split (Codex only).** When step 1 found Codex, ask which provider does the bulk of the work. Prefer `AskUserQuestion`. Offer these two options with these exact labels, and name the current split when the file's `# providers` line records one:

- `claude-first — skill defaults`
- `codex-first — Claude only for the final judgment`

`codex-first` keeps Claude for the roles whose output is the final word: `hardest tasks`, `why synthesizer`, and `reflect judgment, divergent, synthesizer` keep their defaults. The parent chat, which orchestrates every skill, stays on Claude too. Every other role moves to Codex. With F the Codex frontier model and C its general coding model, and each effort set by the budget in (c):

| Role | `codex-first` value |
| --- | --- |
| `feature, refactoring`, `bug-fix`, `perf-issue`, `hillclimb`, `how explorer`, `why investigators`, `reflect tooling`, `swarm workers` | `codex:C` |
| `judgment and prose`, `how explainer` | `codex:F` |
| `arena runners`, `architect runners`, `interrogate reviewers` | `codex:F`, `codex:C` |
| `arena cross-judge pool` | `codex:F`, `opus` |

Choosing a split replaces those roles' values, even ones the user changed earlier. The roles that stay on Claude keep the step 2 values.

**(c) Apply the budget.** Build the working table from the skill defaults, with the step (b) split applied, and on a re-run keep any role you changed by model, list, or alias (`inherit-parent`, `auto`). `unlimited`, `large`, `medium`, and `small` set the effort token of every real entry, panel and `codex:` entries included, to `max`, `xhigh`, `high`, or `medium`. `inherit-parent` and `auto` do not change. So `unlimited` turns `opus xhigh` into `opus max`, and `small` turns `sonnet xhigh` into `sonnet medium`.

**(d) Show the roles and confirm.** Show every role with its value. Also list each line step 2 dropped. Ask whether to accept as-is or change specific roles, offering the detected models (Claude and `codex:`) plus `inherit-parent` and `auto` as the options. Prefer `AskUserQuestion` over free text. For panel roles (arena runners, architect runners, interrogate reviewers) the value is a list, and one subagent runs per entry, alias entries included, so the list length sets the count. Mix models in a panel (`opus` and `sonnet`, or two `codex:` models, say) so the panel stays diverse. `arena cross-judge pool` is also a list, but Arena runs one judge. It tries only entries on a model other than the parent's, in list order, so order it by preference. An `inherit-parent` or `auto` value never judges. `swarm workers` is the default model for every worker unless a race or comparison assigns another model per arm.

### 4. Validate

Every Claude model written must be one the `Agent` schema accepts, with an effort it accepts. Every `codex:` model must be one step 1 listed for the Codex provider, with an effort its `reasoningEffort` option accepts. `inherit-parent` and `auto` always pass. If a chosen value is not valid, stop and ask again.

### 5. Write the file

Write `~/.claude/rules/pstack-models.md` with no frontmatter: the comment lines, a `# budget` line with the chosen label and its target effort, a `# providers` line with the step 3 (b) label when step 3 (b) ran (`claude-first` or `codex-first`), and one line per role, using the same labels poteto-mode uses. Overwrite the whole file so re-runs stay idempotent. Shape:

```
# pstack model configuration. One line per role. Delete a line to fall back to the skill default.
# A value `<model> <effort>` maps to the Agent tool's `model` and `effort` fields.
# A value `codex:<model> <effort>` runs on Codex through T3 `delegate_task` (pstack poteto-mode/references/codex-delegates.md).
# `inherit-parent` or `auto` as a value: the role runs on the session model (omit Agent `model`). Alias entries in a panel list still count toward its fan-out.
# budget: large (xhigh)
feature, refactoring: sonnet xhigh
bug-fix: sonnet xhigh
perf-issue: sonnet xhigh
hillclimb: sonnet xhigh
judgment and prose: opus xhigh
hardest tasks: opus xhigh
how explorer: sonnet xhigh
how explainer: opus xhigh
why investigators: sonnet xhigh
why synthesizer: opus xhigh
reflect tooling: sonnet xhigh
reflect judgment, divergent, synthesizer: opus xhigh
arena runners: opus xhigh, sonnet xhigh
arena cross-judge pool: opus xhigh, sonnet xhigh
swarm workers: sonnet xhigh
architect runners: opus xhigh, sonnet xhigh
interrogate reviewers: opus xhigh, sonnet xhigh
```

### 6. Confirm

Tell the user the file was written and that it applies to new sessions. Re-running this skill updates it.

### 7. Offer a verification skill (optional)

Check whether the project has a way to drive the real app for proof (a `verify-*` skill, or an existing harness). If not, offer once: "want a project-local verification skill, so agents can drive the app the way a user does and prove changes work? I can generate one with /pstack:create-verification-skill." On yes, run the **create-verification-skill** skill. On no, move on without pushing.

### 8. Offer a formal verification skill (optional)

Check whether the project already has a formal verification skill (a project skill that runs a model checker, a proof, or another verifier against the code). If not, offer once: "want a formal verification skill, so agents can prove a key property of your code holds in every case in scope, not only the cases tests reach? I can generate one with /pstack:create-formal-verification-skill." On yes, run the **create-formal-verification-skill** skill. On no, move on without pushing.
