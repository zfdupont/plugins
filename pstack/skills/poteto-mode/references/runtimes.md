# Runtimes: Claude Code and Codex

pstack's skills are written for Claude Code. They also run in Codex. If you have
the `Agent` tool, you are in Claude Code: ignore this file. If you have
`spawn_agent`, you are in Codex: read this file once per session, before the
first spawn, question, model choice or transcript read, and map every
Claude Code term in the skills through it. The skills' steps, briefs, roles,
fan-out counts and verdicts do not change. Only the mechanics do.

## Spawning

| Skill says | In Codex |
| --- | --- |
| an `Agent` call, a spawn, a subagent | `spawn_agent` with `fork_turns: "none"`, so the brief stands alone as it does in Claude Code, and a short `task_name` (for example `explorer-1`) |
| `subagent_type: "pstack:poteto-agent"` or `"pstack:comment-sicko"` | `agent_type: "pstack-poteto-agent"` or `"pstack-comment-sicko"` if `spawn_agent` lists that role. Otherwise omit `agent_type` and start `message` with the full text of `../../../agents/<name>.md` (resolved against this file's directory) without its frontmatter, then a line `---`, then the brief |
| `subagent_type: "general-purpose"` | omit `agent_type`. Codex subagents keep your tools and MCP servers |
| `subagent_type: "Explore"` | omit `agent_type`. The brief already says "do not edit files". Check `git status` afterward as the skill says |
| all N agents in one message, so they run in parallel | spawn all N before you wait on any |
| background by default, never `run_in_background: false` | `spawn_agent` never blocks. Collect results with `wait_agent` |
| `isolation: "worktree"` | Codex has no per-spawn worktree. Before spawning, create one per worker: `git worktree add --detach <tmp>/pstack-<slug>-<n> <branch or HEAD>`. Name the path in the brief and tell the worker to work only there. After aggregating, remove the worktrees that hold nothing you keep |
| resume, message or queue a follow-up on a subagent (SendMessage) | `followup_task` with `target` = its `task_name`. A note that must not start a turn is `send_message` |
| a stop or hold order (TaskStop) | `interrupt_agent` |
| the Workflow tool | not available. Run the same fan-out with `spawn_agent` |

## Models

The role lines live in a different file, and Codex does not load it for you.

- Read `~/.codex/pstack-models.md` yourself before the first spawn. It has the
  same shape as `~/.claude/rules/pstack-models.md`, with Codex model ids. If it
  is missing, use the skill's default and map it as below.
- Map Claude model names (in a skill default, or in a role line copied from
  the Claude file) by tier, from the models `spawn_agent` lists: `opus` and
  `fable` are its most capable model, `sonnet` is its general coding model,
  `haiku` is its fastest. A panel that names two different Claude models gets
  two different Codex models, so it stays diverse. If you cannot tell the
  tiers apart, omit `model` and say so.
- `inherit-parent` and `auto` omit `model`, as in Claude Code.
- The effort maps to `reasoning_effort` (`low`, `medium`, `high`, `xhigh`,
  `max`). If `spawn_agent` rejects a model or effort, follow the skill's
  fallback, reading "the Agent tool" as `spawn_agent`.
- "Fast or standard speed" has no per-spawn setting in Codex. Pick the effort
  only.

## Asking the user

`AskUserQuestion` maps to `request_user_input`, which takes one to three
questions and works only in Plan mode. Outside Plan mode, ask in plain text:
number the options, put the recommendation first, say how to pick several when
the question is multi-select, and end your turn. Resume from the same step when
the user answers.

## Todo list

"Open a todolist" or "the todo list" is `update_plan`.

## Paths

| Skill says | In Codex |
| --- | --- |
| `CLAUDE.md` | `AGENTS.md` (read both if both exist) |
| `~/.claude/rules/*.md` | not loaded by Codex. Personal instructions live in `~/.codex/AGENTS.md` |
| `.claude/skills/<skill>/` (project) | `.agents/skills/<skill>/` |
| `~/.claude/skills/<skill>/` (personal) | `~/.codex/skills/<skill>/` |
| `~/.claude/plugins/cache/` | `~/.codex/plugins/cache/`. Never edit a skill there either |
| `~/.claude/projects/<slug>/*.jsonl` (transcripts) | rollout files under `~/.codex/sessions/` (`YYYY/MM/DD/rollout-*.jsonl`). Newer Codex versions may keep history only in their own store. If no readable rollout file covers the session you need, say the transcript is unavailable, skip the transcript step, and work from what you can observe. Never guess at its content |

## setup-pstack in Codex

1. Detect models from the model list in `spawn_agent`'s description, and
   efforts from each model's listed reasoning efforts. `inherit-parent` and
   `auto` stay valid.
2. Run the budget, map and confirm steps as written, asking as `## Asking the
   user` says. Map each default by tier as `## Models` says.
3. Write `~/.codex/pstack-models.md`, not `~/.claude/rules/pstack-models.md`,
   in the same shape. Change the comment line about the Agent tool to "A value
   `<model> <effort>` maps to spawn_agent's `model` and `reasoning_effort`."
   Do not put the role lines in `AGENTS.md`.
4. Tell the user Codex reads the file only when a pstack skill runs, not at
   session start.
