#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Deterministic helpers for the factory skills.

The skills call this instead of reading factory.yaml or matching paths
themselves. See ../schema.md for the factory.yaml reference.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

KNOWN_KEYS = {
    "version", "base", "max_rework", "max_arbiter_rework", "worktrees", "context",
    "rules", "commands", "merge_gate", "scout", "builder", "reviewers", "qa",
    "escalate", "related", "models",
}
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
MODEL_RE = re.compile(r"^(opus|sonnet|haiku|fable|inherit)( (low|medium|high|xhigh|max))?$")


def config_path(repo: Path) -> Path:
    return Path(repo) / "factory" / "factory.yaml"


def read_raw(repo: Path):
    return yaml.safe_load(config_path(repo).read_text())


def load(repo: Path) -> dict:
    """factory.yaml with defaults applied. Raises if the file is missing."""
    repo = Path(repo)
    cfg = dict(read_raw(repo) or {})
    commands = cfg.get("commands") or {}
    cfg.setdefault("max_rework", 2)
    cfg.setdefault("max_arbiter_rework", 1)
    cfg.setdefault("worktrees", f"../{repo.resolve().name}-factory")
    cfg.setdefault("merge_gate", ["test"] if "test" in commands else [])
    builder = dict(cfg.get("builder") or {})
    builder.setdefault("runtime", "claude")
    builder.setdefault("resume", "session")
    cfg["builder"] = builder
    cfg.setdefault("qa", None)
    for key in ("context", "reviewers", "escalate", "related"):
        cfg.setdefault(key, [])
    cfg.setdefault("models", {})
    cfg.setdefault("scout", {})
    return cfg


def agent_file(repo: Path, name: str) -> Path:
    return Path(repo) / ".claude" / "agents" / f"{name}.md"


def validate(repo: Path) -> list[str]:
    """Every problem with factory.yaml, one message each; [] when valid."""
    repo = Path(repo)
    if not config_path(repo).exists():
        return ["factory.yaml: not found; run /factory:setup"]
    try:
        raw = read_raw(repo)
    except yaml.YAMLError as exc:
        return [f"factory.yaml: invalid YAML: {' '.join(str(exc).split())}"]
    if not isinstance(raw, dict):
        return ["factory.yaml: must be a mapping"]

    errors = [f"factory.yaml: unknown key '{k}'" for k in raw if k not in KNOWN_KEYS]
    if raw.get("version") != 1:
        errors.append("factory.yaml: version must be 1")
    if not isinstance(raw.get("base"), str):
        errors.append("factory.yaml: base is required")

    commands = raw.get("commands")
    if not isinstance(commands, dict) or not commands:
        errors.append("factory.yaml: commands is required")
        commands = {}
    for name, cmd in commands.items():
        if not isinstance(cmd, str) or not cmd.strip():
            errors.append(f"factory.yaml: commands.{name} must be a non-empty string")
    for name in raw.get("merge_gate") or []:
        if name not in commands:
            errors.append(f"factory.yaml: merge_gate '{name}' is not in commands")

    builder = raw.get("builder") or {}
    runtime = builder.get("runtime", "claude")
    if runtime not in ("claude", "command"):
        errors.append("factory.yaml: builder.runtime must be claude or command")
    if runtime == "command" and "{prompt_file}" not in str(builder.get("command", "")):
        errors.append("factory.yaml: builder.command must contain {prompt_file}")
    if builder.get("resume", "session") not in ("session", "fresh"):
        errors.append("factory.yaml: builder.resume must be session or fresh")

    reviewers = raw.get("reviewers")
    if not isinstance(reviewers, list) or not reviewers:
        errors.append("factory.yaml: reviewers must be a non-empty list")
        reviewers = []
    seen = set()
    for rev in reviewers:
        if not isinstance(rev, dict):
            errors.append("factory.yaml: each reviewer must be a mapping with name and why")
            continue
        name = str(rev.get("name", ""))
        if not NAME_RE.match(name):
            errors.append(f"factory.yaml: reviewer name '{name}' must match ^[a-z][a-z0-9-]*$")
        if name in seen:
            errors.append(f"factory.yaml: reviewer '{name}' appears twice")
        seen.add(name)
        if not rev.get("why"):
            errors.append(f"factory.yaml: reviewer '{name}' needs a why")
        paths = rev.get("paths")
        if paths is not None and not (isinstance(paths, list) and all(isinstance(p, str) for p in paths)):
            errors.append(f"factory.yaml: reviewer '{name}' paths must be a list of strings")
        if not agent_file(repo, f"factory-review-{name}").exists():
            errors.append(f"factory.yaml: reviewer '{name}' has no .claude/agents/factory-review-{name}.md")

    qa = raw.get("qa")
    if qa is not None:
        agent = qa.get("agent") if isinstance(qa, dict) else None
        if not agent:
            errors.append("factory.yaml: qa must be null or have an agent")
        elif not agent_file(repo, agent).exists():
            errors.append(f"factory.yaml: qa agent '{agent}' has no .claude/agents/{agent}.md")

    for role, value in (raw.get("models") or {}).items():
        if not MODEL_RE.match(str(value)):
            errors.append(f"factory.yaml: models.{role} '{value}' must be '<model> [effort]'")

    for rel in raw.get("related") or []:
        if not (isinstance(rel, dict) and rel.get("path") and rel.get("contract")):
            errors.append("factory.yaml: related entries need path and contract")
    return errors


def get(cfg: dict, dotted: str):
    value = cfg
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def glob_regex(pattern: str) -> re.Pattern:
    if pattern.endswith("/"):
        pattern += "**"
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def glob_match(pattern: str, path: str) -> bool:
    """Whole-path match under the rules in ../schema.md."""
    return glob_regex(pattern).fullmatch(path) is not None


def select(cfg: dict, changed: list[str]) -> dict:
    """Which reviewers (and qa) run this round, given the changed files."""
    run, skipped = [], []

    def place(name: str, paths) -> None:
        hit = paths is None or any(glob_match(p, f) for p in paths for f in changed)
        (run if hit else skipped).append(name)

    for rev in cfg.get("reviewers") or []:
        place(rev["name"], rev.get("paths"))
    if cfg.get("qa"):
        place("qa", cfg["qa"].get("paths"))
    return {"run": run, "skipped": skipped}


def git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="factory_config.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").add_argument("repo")
    p = sub.add_parser("get")
    p.add_argument("repo")
    p.add_argument("key")
    p = sub.add_parser("select")
    for arg in ("repo", "base", "head"):
        p.add_argument(arg)
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        errors = validate(Path(args.repo))
        print("\n".join(errors) if errors else "ok")
        return 1 if errors else 0
    if args.cmd == "get":
        print(json.dumps(get(load(Path(args.repo)), args.key)))
        return 0
    if args.cmd == "select":
        repo = Path(args.repo)
        changed = [f for f in git_out(repo, "diff", "-z", "--name-only", f"{args.base}...{args.head}").split("\0") if f]
        print(json.dumps(select(load(repo), changed)))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
