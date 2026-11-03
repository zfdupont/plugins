import json

import pytest
from conftest import MINIMAL, commit_file, git, git_init, make_repo, run_cli

from factory_config import glob_match, select


@pytest.mark.parametrize("pat,path,ok", [
    ("web/**", "web/app.py", True),
    ("web/**", "webapp/x.py", False),
    ("web/", "web/a/b.py", True),
    ("web/", "webapp/a.py", False),
    ("scripts/train_*", "scripts/train_cfr.py", True),
    ("scripts/train_*", "scripts/sub/train_x.py", False),
    ("**/*.cpp", "common/src/game/card.cpp", True),
    ("*.md", "docs/a.md", True),
    ("**/*.py", "setup.py", True),
    ("*.py", "src/a.py", True),
    ("web", "web/a.js", True),
    ("web", "src/web/a.js", True),
    ("web", "webapp/a.js", False),
    ("src/**/test_*.py", "src/test_a.py", True),
    ("src/**/test_*.py", "src/x/y/test_a.py", True),
    ("src/greet", "src/greet/cli.py", True),
    ("src/greet", "lib/src/greet/cli.py", False),
    ("src/?.c", "src/a.c", True),
    ("a+b.txt", "a+b.txt", True),
    ("a.txt", "abtxt", False),
])
def test_glob_match(pat, path, ok):
    assert glob_match(pat, path) is ok


def test_select_skips_unmatched_scoped_reviewers():
    cfg = {"reviewers": [{"name": "logic"}, {"name": "api", "paths": ["web/**"]}], "qa": None}
    assert select(cfg, ["cfr/a.py"]) == {"run": ["logic"], "skipped": ["api"]}


def test_select_runs_scoped_reviewer_on_match():
    cfg = {"reviewers": [{"name": "api", "paths": ["web/"]}, {"name": "logic"}], "qa": None}
    assert select(cfg, ["web/x/y.py"]) == {"run": ["api", "logic"], "skipped": []}


def test_select_qa_last():
    cfg = {"reviewers": [{"name": "logic"}], "qa": {"agent": "factory-qa"}}
    assert select(cfg, ["x"]) == {"run": ["logic", "qa"], "skipped": []}


def test_select_scoped_qa_skipped():
    cfg = {"reviewers": [{"name": "logic"}], "qa": {"agent": "factory-qa", "paths": ["ui/**"]}}
    assert select(cfg, ["x"]) == {"run": ["logic"], "skipped": ["qa"]}


def test_select_cli_uses_git_diff(tmp_path):
    text = MINIMAL + "  - {name: api, why: y, paths: ['web/**']}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic", "factory-review-api"])
    git_init(repo)
    git(repo, "checkout", "-q", "-b", "factory/001-x")
    commit_file(repo, "web/app.py")
    res = run_cli("select", repo, "main", "factory/001-x")
    assert res.returncode == 0
    assert json.loads(res.stdout) == {"run": ["logic", "api"], "skipped": []}
    commit_file(repo, "other.py")
    res = run_cli("select", repo, "factory/001-x", "HEAD")
    assert json.loads(res.stdout) == {"run": ["logic"], "skipped": ["api"]}


def test_select_cli_path_with_space(tmp_path):
    text = MINIMAL + "  - {name: docs, why: y, paths: ['my docs/**']}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic", "factory-review-docs"])
    git_init(repo)
    commit_file(repo, "my docs/a.md")
    res = run_cli("select", repo, "HEAD~1", "HEAD")
    assert json.loads(res.stdout) == {"run": ["logic", "docs"], "skipped": []}


def test_select_cli_counts_old_name_of_a_rename(tmp_path):
    text = MINIMAL + "  - {name: api, why: y, paths: ['web/']}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic", "factory-review-api"])
    git_init(repo)
    commit_file(repo, "web/api.py", "a\nb\nc\nd\n")
    git(repo, "mv", "web/api.py", "legacy.py")
    git(repo, "commit", "-q", "-m", "move")
    res = run_cli("select", repo, "HEAD~1", "HEAD")
    assert json.loads(res.stdout) == {"run": ["logic", "api"], "skipped": []}
