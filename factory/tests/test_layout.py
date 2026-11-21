import json
from pathlib import Path

from conftest import MINIMAL, git, git_init, run_cli

from factory_config import config_path


def bare_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / "factory-review-logic.md").write_text("---\nname: x\n---\n")
    (repo / "README.md").write_text("x\n")
    return repo


def legacy_repo(tmp_path: Path) -> Path:
    """A pre-0.4 repo: everything in factory/, committed."""
    repo = bare_repo(tmp_path)
    old = repo / "factory"
    (old / "jobs" / "001-a").mkdir(parents=True)
    (old / "factory.yaml").write_text(MINIMAL)
    (old / "backlog.md").write_text("# Backlog\n- [ ] thing\n")
    (old / "board.json").write_text(json.dumps({"jobs": [{"id": "001-a", "stage": "merged"}]}))
    (old / "dashboard.html").write_text("old")
    (old / "jobs" / ".gitkeep").write_text("")
    (old / "jobs" / "001-a" / "spec.md").write_text("# A\n")
    git_init(repo)
    return repo


def test_config_path_is_docs_factory(tmp_path):
    assert config_path(tmp_path) == tmp_path / "docs" / "factory" / "factory.yaml"


def test_validate_hints_migration_for_legacy_layout(tmp_path):
    repo = legacy_repo(tmp_path)
    res = run_cli("validate", repo)
    assert res.returncode == 1
    assert res.stdout.strip() == (
        "factory.yaml: found at factory/, run /factory:setup to migrate it to docs/factory/"
    )


def test_validate_not_found_without_any_layout(tmp_path):
    repo = bare_repo(tmp_path)
    assert run_cli("validate", repo).stdout.strip() == "factory.yaml: not found; run /factory:setup"


def test_init_creates_layout_and_ignores_work_folder(tmp_path):
    repo = bare_repo(tmp_path)
    git_init(repo)
    res = run_cli("init", repo)
    assert res.returncode == 0
    assert (repo / ".factory" / ".gitignore").read_text() == "*\n"
    assert json.loads((repo / ".factory" / "board.json").read_text()) == {"jobs": []}
    assert (repo / ".factory" / "jobs").is_dir()
    assert (repo / ".factory" / "dashboard.html").stat().st_size > 0
    assert (repo / "docs" / "factory" / "backlog.md").read_text() == "# Backlog\n"
    status = git(repo, "status", "--porcelain")
    assert ".factory" not in status
    assert "docs/" in status


def test_init_never_overwrites_gitignore_board_or_backlog(tmp_path):
    repo = bare_repo(tmp_path)
    git_init(repo)
    run_cli("init", repo)
    (repo / ".factory" / ".gitignore").write_text("*\n!events.jsonl\n")
    (repo / ".factory" / "board.json").write_text('{"jobs": [{"id": "001-a"}]}')
    (repo / "docs" / "factory" / "backlog.md").write_text("# Backlog\n- [ ] keep\n")
    (repo / ".factory" / "dashboard.html").write_text("stale")
    res = run_cli("init", repo)
    assert res.returncode == 0 and res.stdout.strip() == "ok"
    assert (repo / ".factory" / ".gitignore").read_text() == "*\n!events.jsonl\n"
    assert "001-a" in (repo / ".factory" / "board.json").read_text()
    assert "keep" in (repo / "docs" / "factory" / "backlog.md").read_text()
    assert (repo / ".factory" / "dashboard.html").read_text() != "stale"


def test_migrate_splits_tracked_legacy_folder(tmp_path):
    repo = legacy_repo(tmp_path)
    res = run_cli("migrate", repo)
    assert res.returncode == 0, res.stdout
    assert not (repo / "factory").exists()
    assert (repo / "docs" / "factory" / "factory.yaml").read_text() == MINIMAL
    assert "thing" in (repo / "docs" / "factory" / "backlog.md").read_text()
    assert (repo / ".factory" / "jobs" / "001-a" / "spec.md").exists()
    assert not (repo / ".factory" / "jobs" / ".gitkeep").exists()
    assert (repo / ".factory" / ".gitignore").read_text() == "*\n"
    assert run_cli("validate", repo).stdout.strip() == "ok"
    staged = git(repo, "status", "--porcelain")
    assert "R  factory/factory.yaml -> docs/factory/factory.yaml" in staged
    assert "D  factory/board.json" in staged
    assert ".factory" not in staged


def test_migrate_with_untracked_legacy_folder(tmp_path):
    repo = legacy_repo(tmp_path)
    git(repo, "rm", "-r", "-q", "--cached", "factory")
    git(repo, "commit", "-q", "-m", "untrack")
    res = run_cli("migrate", repo)
    assert res.returncode == 0, res.stdout
    assert (repo / "docs" / "factory" / "factory.yaml").exists()
    assert (repo / ".factory" / "board.json").exists()
    assert ".factory" not in git(repo, "status", "--porcelain")


def test_migrate_refuses_in_flight_job_and_moves_nothing(tmp_path):
    repo = legacy_repo(tmp_path)
    (repo / "factory" / "board.json").write_text(json.dumps({"jobs": [{"id": "002-b", "stage": "build"}]}))
    git(repo, "commit", "-q", "-am", "in flight")
    res = run_cli("migrate", repo)
    assert res.returncode == 1
    assert "migrate: job 002-b in flight at stage build" in res.stdout
    assert (repo / "factory" / "factory.yaml").exists()
    assert not (repo / "docs" / "factory").exists()


def test_migrate_refuses_dirty_tree_outside_factory(tmp_path):
    repo = legacy_repo(tmp_path)
    (repo / "README.md").write_text("changed\n")
    res = run_cli("migrate", repo)
    assert res.returncode == 1 and "migrate: working tree not clean" in res.stdout


def test_migrate_refuses_when_new_layout_exists(tmp_path):
    repo = legacy_repo(tmp_path)
    (repo / "docs" / "factory").mkdir(parents=True)
    (repo / "docs" / "factory" / "factory.yaml").write_text(MINIMAL)
    res = run_cli("migrate", repo)
    assert res.returncode == 1
    assert res.stdout.strip() == "migrate: docs/factory/factory.yaml already exists"


def test_migrate_without_legacy_layout(tmp_path):
    repo = bare_repo(tmp_path)
    git_init(repo)
    res = run_cli("migrate", repo)
    assert res.returncode == 1
    assert res.stdout.strip() == "migrate: no factory/factory.yaml to migrate"


def test_migrate_leaves_unknown_files_and_reports_them(tmp_path):
    repo = legacy_repo(tmp_path)
    (repo / "factory" / "notes.txt").write_text("mine\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "notes")
    res = run_cli("migrate", repo)
    assert res.returncode == 0
    assert "left in factory/: notes.txt" in res.stdout
    assert (repo / "factory" / "notes.txt").exists()


def test_migration_check_reads_board_from_work_folder(tmp_path):
    repo = bare_repo(tmp_path)
    git_init(repo)
    run_cli("init", repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "setup")
    (repo / ".factory" / "board.json").write_text(json.dumps({"jobs": [{"id": "003-c", "stage": "review"}]}))
    res = run_cli("migration-check", repo)
    assert res.returncode == 1
    assert res.stdout.strip() == "job 003-c in flight at stage review"
