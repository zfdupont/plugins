import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "run" / "scripts" / "factory_config.py"
sys.path.insert(0, str(SCRIPT.parent))

MINIMAL = "version: 1\nbase: main\ncommands: {test: pytest}\nreviewers:\n  - {name: logic, why: x}\n"


def make_repo(tmp_path: Path, yaml_text: str | None, agents: list[str]) -> Path:
    repo = tmp_path / "repo"
    (repo / "factory").mkdir(parents=True)
    (repo / ".claude" / "agents").mkdir(parents=True)
    if yaml_text is not None:
        (repo / "factory" / "factory.yaml").write_text(yaml_text)
    for name in agents:
        (repo / ".claude" / "agents" / f"{name}.md").write_text(f"---\nname: {name}\n---\n")
    return repo


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def git_init(repo: Path) -> None:
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")


def commit_file(repo: Path, rel: str, text: str = "x\n") -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"touch {rel}")
    return git(repo, "rev-parse", "HEAD")


def write_board(repo: Path, jobs: list[dict]) -> None:
    (repo / "factory" / "board.json").write_text(json.dumps({"jobs": jobs}))


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True
    )


@pytest.fixture
def minimal():
    return MINIMAL
