# factory

A software factory for Claude Code. A feature goes from spec to merge through a
spec writer, a builder, a panel of reviewers chosen for the repo, an approver,
and an arbiter. Agents hand work to each other through files under `factory/`
in the repo, and `factory/dashboard.html` shows the board.

Each repo gets its own shape. `/factory:setup` reads the codebase and proposes
the reviewers, commands, QA step, escalation rules, builder runtime and models
that fit it. Nothing is written until you approve. The result is
`factory/factory.yaml` plus reviewer agents in `.claude/agents/`; edit them to
override, or run setup again to have it propose a rewrite.

```bash
/plugin marketplace add zfdupont/plugins
/plugin install factory@zfdupont-plugins
```

## Commands

| command | what it does |
| --- | --- |
| `/factory:setup` | Read the repo and propose (or re-propose) its factory |
| `/factory:run <feature>` | Take one feature from spec to merge |
| `/factory:next` | Run the first unchecked backlog item |
| `/factory:scout` | Find small features worth adding to the backlog |
| `/factory:scout foundations` | Find gaps the factory needs filled: tests, lint, rules, QA, CI |
| `/factory:milestone <N> [<N> ...]` | Run whole milestones from the milestones file, one job each: one builder, one review pass, auto-merge unless a step is marked `[ESCALATE`, with no triage, spec or approver |
| `/factory:approve <job-id> [<job-id> ...]` | Merge one or more jobs waiting on you, in order |
| `/factory:rework <job-id> <note>` | Send a job back to the builder with your note |
| `/factory:arbitrate <job-id>` | Run the arbiter on a job waiting on you |
| `/factory:tune` | Suggest improvements from the factory's own record |

The factory merges locally and never pushes.

Watch the board: `cd factory && python3 -m http.server 8765`, then open
http://localhost:8765/dashboard.html.

Design: [docs/specs/2026-11-03-factory-plugin-design.md](docs/specs/2026-11-03-factory-plugin-design.md).
