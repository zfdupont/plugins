#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "tomli-w"]
# ///
"""Convert Claude Code agent files (agents/*.md) into Codex custom agents (*.toml).

The Markdown files stay the source of truth. Codex reads one TOML file per agent
from ~/.codex/agents/ (personal) or <repo>/.codex/agents/ (project).

  codex_agents.py plugins [--dest DIR] [--check]   every plugin in this marketplace
  codex_agents.py repo REPO [--check]              REPO/.claude/agents -> REPO/.codex/agents

A plugin agent `<plugin>/agents/<name>.md` becomes `<plugin>-<name>.toml` with
name `<plugin>-<name>`. A repo agent keeps its name. `--check` writes nothing and
exits 1 when an output file is missing or out of date.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import tomli_w
import yaml

ROOT = Path(__file__).resolve().parent.parent
HEADER = "# Generated from {src} by scripts/codex_agents.py. Edit the .md file, not this one.\n"


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta = yaml.safe_load(text[4:end]) or {}
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, text[end + 5 :]


def convert(src: Path, name: str, label: str) -> str:
    meta, body = split_frontmatter(src.read_text())
    description = str(meta.get("description") or "").strip()
    if not description:
        raise ValueError(f"{src}: frontmatter has no description")
    # Claude model aliases and tool lists have no Codex equivalent, so they are
    # dropped: the agent inherits the session's model and tools.
    doc = {
        "name": name,
        "description": description,
        "developer_instructions": body.strip() + "\n",
    }
    return HEADER.format(src=label) + tomli_w.dumps(doc, multiline_strings=True)


def plugin_jobs(dest: Path) -> list[tuple[Path, Path, str, str]]:
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    jobs = []
    for plugin in market["plugins"]:
        root = (ROOT / plugin["source"]).resolve()
        for src in sorted((root / "agents").glob("*.md")):
            name = f"{plugin['name']}-{src.stem}"
            jobs.append((src, dest / f"{name}.toml", name, f"{plugin['name']}/agents/{src.name}"))
    return jobs


def repo_jobs(repo: Path) -> list[tuple[Path, Path, str, str]]:
    jobs = []
    for src in sorted((repo / ".claude" / "agents").glob("*.md")):
        jobs.append((src, repo / ".codex" / "agents" / f"{src.stem}.toml", src.stem, f".claude/agents/{src.name}"))
    return jobs


def run(jobs: list[tuple[Path, Path, str, str]], check: bool) -> int:
    if not jobs:
        print("no agents found")
        return 0
    stale = 0
    for src, out, name, label in jobs:
        text = convert(src, name, label)
        current = out.read_text() if out.exists() else None
        if current == text:
            print(f"ok      {out}")
            continue
        if check:
            print(f"stale   {out}")
            stale += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote   {out}")
    return 1 if stale else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plugins", help="convert every plugin's agents/ in this marketplace")
    p.add_argument("--dest", type=Path, default=Path.home() / ".codex" / "agents")
    p.add_argument("--check", action="store_true")
    r = sub.add_parser("repo", help="convert REPO/.claude/agents into REPO/.codex/agents")
    r.add_argument("repo", type=Path)
    r.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "plugins":
            return run(plugin_jobs(args.dest.expanduser()), args.check)
        return run(repo_jobs(args.repo.expanduser().resolve()), args.check)
    except (ValueError, yaml.YAMLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
