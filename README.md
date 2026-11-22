# plugins

Personal plugin marketplace for Claude Code and Codex.

```bash
/plugin marketplace add zfdupont/plugins
/plugin install pstack@zfdupont-plugins
```

## Codex

Codex reads the same `.claude-plugin/` manifests, so nothing is duplicated:

```bash
codex plugin marketplace add zfdupont/plugins
codex plugin add factory@zfdupont-plugins
codex plugin add pstack@zfdupont-plugins
```

Skills keep their names (`factory:run`, `pstack:poteto-mode`); mention one with
`$` in Codex. Codex plugins cannot ship subagents, so the plugins' `agents/*.md`
are not loaded. To register them as Codex custom agents, generate TOML files
from the Markdown (rerun after an agent changes):

```bash
uv run scripts/codex_agents.py plugins            # -> ~/.codex/agents/<plugin>-<name>.toml
uv run scripts/codex_agents.py repo /path/to/repo # .claude/agents -> .codex/agents
uv run scripts/codex_agents.py plugins --check    # exit 1 if any are stale
```

Factory works in Codex without this step: when `factory-<role>` is not a
registered agent, it spawns a plain subagent with the agent file's text as the
prompt. pstack does the same for `poteto-agent` and `comment-sicko`, and maps
the rest of its Claude Code tools, models and paths in
[`runtimes.md`](./pstack/skills/poteto-mode/references/runtimes.md).

Tests for the converter: `uv run -q --no-project --with pytest pytest tests -q`.

| plugin | what it is |
| --- | --- |
| [pstack](./pstack) | A native Claude Code port of [poteto's pstack](https://github.com/cursor/plugins/tree/1ba91fc25c0977741dd0e267849e6234b037ed0a/pstack) for Cursor. Start with `/pstack:setup-pstack`, then use `/pstack:poteto-mode`. |
| [factory](./factory) | A spec-to-merge software factory you set up per repo. Start with `/factory:setup`. |
