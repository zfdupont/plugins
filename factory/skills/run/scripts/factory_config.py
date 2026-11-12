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
    "rules", "tests", "commands", "merge_gate", "scout", "builder", "reviewers", "qa",
    "escalate", "related", "models", "lanes",
}
LANE_NAMES = {"trivial"}
LANE_KEYS = {"paths", "max_changed_lines", "skip"}
LANE_SKIPS = {"spec", "approval"}
ESCALATE_KEYS = {"when", "paths"}
DEFAULT_MAX_CHANGED_LINES = 40
THIN_TESTS_PATHS = ["src/", "scripts/"]
BUILDER_KEYS = {"runtime", "command", "resume"}
QA_KEYS = {"agent", "paths"}
SCOUT_KEYS = {"todo_paths", "docs", "checks"}
REVIEWER_KEYS = {"name", "why", "paths", "model"}
MODEL_ROLES = {
    "spec-writer", "builder", "reviewers", "approver", "arbiter", "scout",
    "setup-surveyor", "foundations-scout", "tuner", "triage", "roadmapper",
}
TESTS_STATES = ("none", "thin", "ok")
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
    cfg.setdefault("tests", "ok" if "test" in commands else "none")
    builder = dict(cfg.get("builder") or {})
    builder.setdefault("runtime", "claude")
    builder.setdefault("resume", "session")
    cfg["builder"] = builder
    cfg.setdefault("qa", None)
    for key in ("context", "reviewers", "escalate", "related"):
        cfg.setdefault(key, [])
    cfg.setdefault("models", {})
    cfg.setdefault("scout", {})
    cfg["lanes"] = cfg.get("lanes") or {}
    return cfg


def is_path_list(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


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

    def mapping(key: str, allowed: set[str] | None = None) -> dict:
        value = raw.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            errors.append(f"factory.yaml: {key} must be a mapping")
            return {}
        if allowed is not None:
            errors.extend(f"factory.yaml: unknown key '{key}.{k}'" for k in value if k not in allowed)
        return value

    def string_list(key: str) -> list:
        value = raw.get(key)
        if value is None:
            return []
        if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            errors.append(f"factory.yaml: {key} must be a list")
            return []
        return value

    if raw.get("version") != 1:
        errors.append("factory.yaml: version must be 1")
    if not isinstance(raw.get("base"), str):
        errors.append("factory.yaml: base is required")
    for key in ("max_rework", "max_arbiter_rework"):
        if key in raw and not (isinstance(raw[key], int) and not isinstance(raw[key], bool) and raw[key] >= 0):
            errors.append(f"factory.yaml: {key} must be a whole number")
    tests = raw.get("tests")
    if tests is not None and tests not in TESTS_STATES:
        errors.append("factory.yaml: tests must be none, thin or ok")
    string_list("context")

    escalate = raw.get("escalate")
    if escalate is not None and not isinstance(escalate, list):
        errors.append("factory.yaml: escalate must be a list")
    for i, entry in enumerate(escalate if isinstance(escalate, list) else []):
        if isinstance(entry, str):
            continue
        if not isinstance(entry, dict):
            errors.append(f"factory.yaml: escalate[{i}] must be a string or a mapping with when and paths")
            continue
        errors.extend(f"factory.yaml: unknown key 'escalate[{i}].{k}'" for k in entry if k not in ESCALATE_KEYS)
        if not (isinstance(entry.get("when"), str) and entry["when"]):
            errors.append(f"factory.yaml: escalate[{i}] needs a when")
        if "paths" in entry and not is_path_list(entry["paths"]):
            errors.append(f"factory.yaml: escalate[{i}] paths must be a non-empty list of strings")

    for lane, spec in mapping("lanes").items():
        if lane not in LANE_NAMES:
            errors.append(f"factory.yaml: unknown key 'lanes.{lane}'")
            continue
        if not isinstance(spec, dict):
            errors.append(f"factory.yaml: lanes.{lane} must be a mapping")
            continue
        errors.extend(f"factory.yaml: unknown key 'lanes.{lane}.{k}'" for k in spec if k not in LANE_KEYS)
        if not is_path_list(spec.get("paths")):
            errors.append(f"factory.yaml: lanes.{lane}.paths must be a non-empty list of strings")
        limit = spec.get("max_changed_lines", DEFAULT_MAX_CHANGED_LINES)
        if not (isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0):
            errors.append(f"factory.yaml: lanes.{lane}.max_changed_lines must be a whole number")
        skip = spec.get("skip", [])
        if not (isinstance(skip, list) and all(v in LANE_SKIPS for v in skip)):
            errors.append(f"factory.yaml: lanes.{lane}.skip must be a list of spec, approval")

    commands = raw.get("commands")
    if not isinstance(commands, dict) or (not commands and tests != "none"):
        errors.append("factory.yaml: commands is required")
        commands = {}
    for name, cmd in commands.items():
        if not isinstance(cmd, str) or not cmd.strip():
            errors.append(f"factory.yaml: commands.{name} must be a non-empty string")
    for name in string_list("merge_gate"):
        if name not in commands:
            errors.append(f"factory.yaml: merge_gate '{name}' is not in commands")

    scout = mapping("scout", SCOUT_KEYS)
    for key in SCOUT_KEYS & scout.keys():
        if not (isinstance(scout[key], list) and all(isinstance(v, str) for v in scout[key])):
            errors.append(f"factory.yaml: scout.{key} must be a list")

    builder = mapping("builder", BUILDER_KEYS)
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
    seen, always_on = set(), False
    for rev in reviewers:
        if not isinstance(rev, dict):
            errors.append("factory.yaml: each reviewer must be a mapping with name and why")
            continue
        name = str(rev.get("name", ""))
        errors.extend(f"factory.yaml: unknown key 'reviewers.{name}.{k}'" for k in rev if k not in REVIEWER_KEYS)
        if not NAME_RE.match(name):
            errors.append(f"factory.yaml: reviewer name '{name}' must match ^[a-z][a-z0-9-]*$")
        if name == "qa":
            errors.append("factory.yaml: reviewer name 'qa' is reserved for QA")
        if name in seen:
            errors.append(f"factory.yaml: reviewer '{name}' appears twice")
        seen.add(name)
        if not rev.get("why"):
            errors.append(f"factory.yaml: reviewer '{name}' needs a why")
        if "paths" not in rev:
            always_on = True
        elif not is_path_list(rev["paths"]):
            errors.append(f"factory.yaml: reviewer '{name}' paths must be a non-empty list of strings")
        if "model" in rev and not MODEL_RE.match(str(rev["model"])):
            errors.append(f"factory.yaml: reviewer '{name}' model '{rev['model']}' must be '<model> [effort]'")
        if not agent_file(repo, f"factory-review-{name}").exists():
            errors.append(f"factory.yaml: reviewer '{name}' has no .claude/agents/factory-review-{name}.md")
    if reviewers and not always_on:
        errors.append("factory.yaml: at least one reviewer must run every round (no paths)")

    if raw.get("qa") is not None:
        qa = mapping("qa", QA_KEYS)
        agent = qa.get("agent")
        if not agent:
            errors.append("factory.yaml: qa must be null or have an agent")
        elif not agent_file(repo, agent).exists():
            errors.append(f"factory.yaml: qa agent '{agent}' has no .claude/agents/{agent}.md")
        if "paths" in qa and not is_path_list(qa["paths"]):
            errors.append("factory.yaml: qa paths must be a non-empty list of strings")

    for role, value in mapping("models", MODEL_ROLES).items():
        if not MODEL_RE.match(str(value)):
            errors.append(f"factory.yaml: models.{role} '{value}' must be '<model> [effort]'")

    related = raw.get("related") or []
    if not isinstance(related, list):
        errors.append("factory.yaml: related must be a list")
        related = []
    for rel in related:
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
    pattern = pattern.rstrip("/")
    if "/" not in pattern:
        pattern = "**/" + pattern
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
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
    """Gitignore-style match under the rules in ../schema.md: the pattern
    matches the path itself or any directory above it."""
    regex = glob_regex(pattern)
    parts = path.split("/")
    return any(regex.fullmatch("/".join(parts[:n])) for n in range(len(parts), 0, -1))


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


def escalate_paths(cfg: dict) -> list[tuple[str, list[str]]]:
    """(when, paths) for each escalate entry that can be checked mechanically."""
    return [(e["when"], e["paths"]) for e in cfg.get("escalate") or [] if isinstance(e, dict) and e.get("paths")]


def escalate_hit(cfg: dict, changed: list[str]) -> dict:
    """Which escalate entries stop an automatic approval for this diff.

    hit: entries with paths that match, and the thin-tests rule when the diff
    touches src/ or scripts/. unchecked: plain-string entries, which only the
    approver can judge."""
    hit = []
    for when, paths in escalate_paths(cfg):
        files = [f for f in changed if any(glob_match(p, f) for p in paths)]
        if files:
            hit.append({"when": when, "files": files})
    if cfg.get("tests", "ok") != "ok":
        files = [f for f in changed if any(glob_match(p, f) for p in THIN_TESTS_PATHS)]
        if files:
            hit.append({"when": f"tests is {cfg['tests']} and the diff touches src/ or scripts/", "files": files})
    unchecked = [e for e in cfg.get("escalate") or [] if isinstance(e, str)]
    return {"hit": hit, "unchecked": unchecked}


def lane(cfg: dict, changed: list[str], lines: int) -> dict:
    """Which lane a diff belongs to: trivial only when the repo defines the
    lane and the diff stays inside its paths, size and escalate paths."""
    spec = (cfg.get("lanes") or {}).get("trivial")
    if not spec:
        return {"lane": "full", "why": "no trivial lane configured"}
    if not changed:
        return {"lane": "full", "why": "no changed files"}
    outside = [f for f in changed if not any(glob_match(p, f) for p in spec["paths"])]
    if outside:
        return {"lane": "full", "why": f"outside lane paths: {', '.join(outside[:5])}"}
    limit = spec.get("max_changed_lines", DEFAULT_MAX_CHANGED_LINES)
    if lines > limit:
        return {"lane": "full", "why": f"{lines} changed lines exceeds {limit}"}
    for when, paths in escalate_paths(cfg):
        hits = [f for f in changed if any(glob_match(p, f) for p in paths)]
        if hits:
            return {"lane": "full", "why": f"escalate path matched ({when}): {', '.join(hits[:5])}"}
    return {"lane": "trivial", "why": f"{len(changed)} files, {lines} lines, all inside lane paths", "skip": spec.get("skip", [])}


def git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    out = git_out(repo, "diff", "-z", "--no-renames", "--name-only", f"{base}...{head}")
    return [f for f in out.split("\0") if f]


def changed_lines(repo: Path, base: str, head: str) -> int:
    """Added plus deleted lines; a binary file counts as 1000."""
    total = 0
    for rec in git_out(repo, "diff", "-z", "--no-renames", "--numstat", f"{base}...{head}").split("\0"):
        if not rec:
            continue
        added, deleted, _ = rec.split("\t", 2)
        total += 1000 if added == "-" else int(added) + int(deleted)
    return total


IN_FLIGHT = ("spec", "build", "review", "approval", "arbitration")


def builder_done(worktree: Path, before_sha: str, build_md: Path, round_n: str) -> str | None:
    """None when the builder finished round_n; otherwise the reason it did not."""
    if not git_out(worktree, "rev-list", f"{before_sha}..HEAD").strip():
        return "no new commit"
    lines = build_md.read_text().splitlines() if build_md.exists() else []
    if f"## Round {round_n}" not in (line.rstrip() for line in lines):
        return f"build.md has no ## Round {round_n}"
    return None


def loop_active(path: Path) -> bool:
    if not path.exists():
        return False
    parts = path.read_text().split("---")
    front = yaml.safe_load(parts[1]) if len(parts) >= 3 else None
    return bool(isinstance(front, dict) and front.get("active"))


def migration_blockers(repo: Path, loop_file: str | None = None) -> list[str]:
    """Why the repo's factory cannot be migrated right now; [] when it can.

    loop_file names a loop state file (frontmatter with `active:`) whose loop
    must be stopped first, relative to repo."""
    blockers = []
    if loop_file and loop_active(repo / loop_file):
        blockers.append(f"loop active ({loop_file})")
    if git_out(repo, "status", "--porcelain").strip():
        blockers.append("working tree not clean")
    board = repo / "factory" / "board.json"
    jobs = json.loads(board.read_text()).get("jobs", []) if board.exists() else []
    for job in jobs:
        if job.get("stage") in IN_FLIGHT:
            blockers.append(f"job {job.get('id')} in flight at stage {job['stage']}")
    return blockers


def overview(cfg: dict) -> str:
    """A text diagram of the agents and steps this repo's factory runs."""
    models = cfg.get("models") or {}

    def model(role: str, fallback: str | None = None) -> str:
        value = models.get(role) or (models.get(fallback) if fallback else None)
        return value or "inherit"

    def box(title: str, detail: str) -> list[str]:
        return [f"  [ {title} ]  {detail}".rstrip()]

    def arrow(note: str = "") -> list[str]:
        return ["      |" + (f"  {note}" if note else ""), "      v"]

    builder = cfg["builder"]
    runtime = builder["runtime"] + (f" ({builder['resume']} resume)" if builder["runtime"] == "command" else "")
    lanes = cfg["lanes"]
    trivial = lanes.get("trivial")
    skip = (trivial or {}).get("skip") or []
    gate = cfg.get("merge_gate") or []
    out = [f"factory overview (base: {cfg.get('base', 'main')}, tests: {cfg.get('tests')})", ""]
    out += box("feature", "/factory:run, /factory:next, or a backlog item")
    out += arrow()
    if trivial:
        out += box("triage", f"model {model('triage')}; lane trivial or full")
        out += arrow("trivial lane skips: " + (", ".join(skip) if skip else "nothing"))
    out += box("spec-writer", f"model {model('spec-writer')}; writes spec.md")
    out += arrow()
    out += box("builder", f"{runtime}; model {model('builder')}; commits on factory/<job>")
    out += arrow()
    commands = cfg.get("commands") or {}
    out += box("commands", ", ".join(commands) if commands else "none")
    out += arrow()
    reviewers = cfg.get("reviewers") or []
    out += box("review", f"in parallel, picked per diff; default model {model('reviewers')}")
    for r in reviewers:
        scope = ", ".join(r["paths"]) if r.get("paths") else "always"
        extra = f"; model {r['model']}" if r.get("model") else ""
        out.append(f"      |- {r['name']}: {scope}{extra}")
    qa = cfg.get("qa")
    if qa:
        scope = ", ".join(qa["paths"]) if qa.get("paths") else "always"
        out.append(f"      |- qa ({qa['agent']}): {scope}")
    out.append(f"      '- any CHANGES -> back to builder (up to {cfg['max_rework']} rework rounds)")
    out += arrow()
    out += box("approval", f"model {model('approver')}; auto when reviews pass, gate green, no escalate hit")
    if gate:
        out.append("      merge gate: " + ", ".join(gate))
    for e in cfg.get("escalate") or []:
        out.append("      escalate: " + (e if isinstance(e, str) else e["when"]))
    out.append(f"      '- ESCALATE or no convergence -> [ arbiter ] model {model('arbiter')}"
               f"; up to {cfg['max_arbiter_rework']} rework")
    out += arrow()
    out += box("merge", f"--no-ff into {cfg.get('base', 'main')}; never pushes")
    out += ["", "other commands", f"  setup     [ setup-surveyor ] model {model('setup-surveyor')}",
            f"  scout     [ scout ] model {model('scout')}; [ foundations-scout ] model {model('foundations-scout', 'scout')}",
            f"  milestone one builder, one review pass, no triage, spec or approver",
            f"  roadmap   [ roadmapper ] model {model('roadmapper')}; interviews you, writes milestones.md",
            f"  tune      [ tuner ] model {model('tuner')}"]
    if cfg.get("related"):
        out.append("related repos: " + ", ".join(r.get("path", str(r)) if isinstance(r, dict) else str(r) for r in cfg["related"]))
    return "\n".join(out)


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
    for name in ("lane", "escalate-hit"):
        p = sub.add_parser(name)
        for arg in ("repo", "base", "head"):
            p.add_argument(arg)
    sub.add_parser("overview").add_argument("repo")
    p = sub.add_parser("builder-done")
    for arg in ("worktree", "before_sha", "build_md", "round"):
        p.add_argument(arg)
    p = sub.add_parser("migration-check")
    p.add_argument("repo")
    p.add_argument("--loop-file")
    args = parser.parse_args(argv)

    if args.cmd == "builder-done":
        reason = builder_done(Path(args.worktree), args.before_sha, Path(args.build_md), args.round)
        print(reason or "done")
        return 1 if reason else 0
    if args.cmd == "migration-check":
        blockers = migration_blockers(Path(args.repo), args.loop_file)
        print("\n".join(blockers) if blockers else "ok")
        return 1 if blockers else 0

    if args.cmd == "overview":
        repo = Path(args.repo)
        errors = validate(repo)
        if errors:
            print("\n".join(errors))
            return 1
        print(overview(load(repo)))
        return 0
    if args.cmd == "validate":
        errors = validate(Path(args.repo))
        print("\n".join(errors) if errors else "ok")
        return 1 if errors else 0
    if args.cmd == "get":
        print(json.dumps(get(load(Path(args.repo)), args.key)))
        return 0
    if args.cmd == "select":
        repo = Path(args.repo)
        print(json.dumps(select(load(repo), changed_files(repo, args.base, args.head))))
        return 0
    if args.cmd == "lane":
        repo = Path(args.repo)
        result = lane(load(repo), changed_files(repo, args.base, args.head), changed_lines(repo, args.base, args.head))
        print(json.dumps(result))
        return 0
    if args.cmd == "escalate-hit":
        repo = Path(args.repo)
        print(json.dumps(escalate_hit(load(repo), changed_files(repo, args.base, args.head))))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
