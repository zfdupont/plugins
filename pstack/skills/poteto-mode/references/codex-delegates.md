# Codex role values in Claude Code

A role value in `~/.claude/rules/pstack-models.md` may name a Codex model:
`codex:<model-id> <effort>`, such as `codex:gpt-6.2-sol high`. The effort is
the last token, as for Claude values. In Claude Code the `Agent` tool cannot
run a Codex model, so a seat with a `codex:` value runs as a T3 Code
`delegate_task` child instead. Read this file once per session, before the
first spawn of a `codex:` seat. The skills' steps, briefs, roles, fan-out
counts and verdicts do not change. Only the mechanics do.

In Codex (you have `spawn_agent`), drop the `codex:` prefix and pass the rest
as `spawn_agent`'s `model` and `reasoning_effort`. Ignore the rest of this file.

## Before the first Codex seat

1. Load `mcp__t3-code__delegate_task` and `mcp__t3-code__orchestrator_capabilities`
   with `ToolSearch` (`select:` both). If they do not load, you are not in T3
   Code. Run every `codex:` seat on the calling skill's default for that role,
   and say so once.
2. Call `orchestrator_capabilities` once per thread. Take the provider with
   `driverKind: "codex"` and `canRunChildTask: true`. Check that the model id
   is listed (pass `search` if `omittedModels` is above 0) and that its
   `reasoningEffort` option accepts the effort. If no Codex provider can run
   a child, or it does not list the model, run that seat on the role's
   default and say so. If only the effort is not accepted, use the nearest
   lower effort it accepts and say so.

## Spawning

| Skill says | For a `codex:` seat |
| --- | --- |
| an `Agent` call, a spawn, a subagent | `delegate_task` with `target: {providerInstanceId, model, options: {reasoningEffort}}`, a short `title` (for example `explorer-1`), and the brief as `task`. The child sees no parent history, as with `Agent` |
| `model` and `effort` | `target.model` is the id after `codex:`. `target.options.reasoningEffort` is the effort. The poteto-mode Subagents rules for raising or lowering effort apply unchanged |
| `subagent_type: "pstack:poteto-agent"` or `"pstack:comment-sicko"` | start `task` with the full text of `../../../agents/<name>.md` (resolved against this file's directory) without its frontmatter, then a line `---`, then the brief |
| `subagent_type: "general-purpose"` | nothing to add |
| `subagent_type: "Explore"` | `isolation: "shared"`. The brief already says "do not edit files". Check `git status` afterward as the skill says |
| `isolation: "worktree"` | `isolation: "worktree"`. The child's checkout starts at the parent commit without uncommitted edits. When a skill copies uncommitted changes into each worktree, write `git diff HEAD` to a patch file at an absolute path outside the repo, and start the brief with "first run `git apply <path>`" |
| role of the seat | `role`: `implementation` for code delegates and swarm workers, `research` for explorers, investigators and reflect reviewers, `design` for arena and architect runners, `review` for interrogate adversaries and judges, `general` otherwise |
| background by default | `mode: "async"`. Start all of a step's seats, Claude and Codex, in one message before you wait on any. Follow each call's `next`. Do not poll with `task_status`, `sleep` or Monitor |
| an output path in the brief | give an absolute path. A worktree child writes inside its own checkout, so tell it to report the absolute path of every file it wrote |
| resume or follow up a subagent | a new `delegate_task` with consolidated scope, per poteto-mode's fresh-subagents rule |
| a stop or hold order | `task_cancel` with the `taskId`. Never `t3_thread_interrupt` |

Do not set `runtimeMode` or `interactionMode`. The child inherits yours.

## MCP-dependent briefs

A Codex child may not have this session's MCP servers. When a brief depends on
an MCP server (a `why` investigator that owns one, a `reflect` reviewer that
looks up tickets or traces), add to the brief: "If you cannot call
`<server>`'s tools, stop and reply `MCP unavailable: <server>`." On that
reply, run the seat again on the role's default and say so.

## Families and judges

For the **arena** skill's family rules, a `codex:` entry's family is its model
id. Two different Codex ids keep a panel diverse. In Claude Code the parent is
a Claude model, so a `codex:` entry is never from the parent's family and can
always judge.

## Reports

A child's final reply is its report. You own it as you own an `Agent` report:
review the diff or the files it names, and write your own summary.
