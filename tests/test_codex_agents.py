import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "codex_agents.py"


def cli(*args):
    return subprocess.run(
        ["uv", "run", "-q", "--script", str(SCRIPT), *map(str, args)],
        capture_output=True, text=True,
    )


def test_plugins_converts_every_agent(tmp_path):
    res = cli("plugins", "--dest", tmp_path)
    assert res.returncode == 0, res.stderr
    expected = {f"factory-{p.stem}.toml" for p in (ROOT / "factory" / "agents").glob("*.md")}
    expected |= {f"pstack-{p.stem}.toml" for p in (ROOT / "pstack" / "agents").glob("*.md")}
    assert {p.name for p in tmp_path.iterdir()} == expected

    doc = tomllib.loads((tmp_path / "factory-builder.toml").read_text())
    assert doc["name"] == "factory-builder"
    assert doc["description"].startswith("Factory stage 2.")
    body = (ROOT / "factory" / "agents" / "builder.md").read_text().split("\n---\n", 1)[1]
    assert doc["developer_instructions"] == body.strip() + "\n"
    assert set(doc) == {"name", "description", "developer_instructions"}


def test_check_reports_stale_then_ok(tmp_path):
    assert cli("plugins", "--dest", tmp_path, "--check").returncode == 1
    assert not any(tmp_path.iterdir())
    cli("plugins", "--dest", tmp_path)
    assert cli("plugins", "--dest", tmp_path, "--check").returncode == 0


def test_repo_mode_keeps_names_and_survives_quotes(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "factory-review-logic.md").write_text(
        "---\nname: factory-review-logic\ndescription: Checks logic.\ntools: Read\nmodel: opus\n---\n"
        'Write """VERDICT: PASS""" and a \\ backslash and \'\'\' quotes.\n'
    )
    res = cli("repo", tmp_path)
    assert res.returncode == 0, res.stderr
    doc = tomllib.loads((tmp_path / ".codex" / "agents" / "factory-review-logic.toml").read_text())
    assert doc["name"] == "factory-review-logic"
    assert doc["developer_instructions"] == 'Write """VERDICT: PASS""" and a \\ backslash and \'\'\' quotes.\n'
    assert "model" not in doc


def test_missing_description_is_an_error(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "x.md").write_text("---\nname: x\n---\nbody\n")
    res = cli("repo", tmp_path)
    assert res.returncode == 2
    assert "no description" in res.stderr
