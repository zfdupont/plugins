from conftest import commit_file, git, git_init, make_repo, run_cli, write_board


def worktree_with_base(tmp_path):
    repo = make_repo(tmp_path, None, agents=[])
    git_init(repo)
    return repo, git(repo, "rev-parse", "HEAD")


def test_builder_done_needs_commit(tmp_path):
    wt, before = worktree_with_base(tmp_path)
    build = tmp_path / "build.md"
    build.write_text("## Round 1\n")
    res = run_cli("builder-done", wt, before, build, "1")
    assert res.returncode == 1 and res.stdout.strip() == "no new commit"


def test_builder_done_needs_round_section(tmp_path):
    wt, before = worktree_with_base(tmp_path)
    commit_file(wt, "a.py")
    build = tmp_path / "build.md"
    build.write_text("## Round 0\n## Round 10\n")
    res = run_cli("builder-done", wt, before, build, "1")
    assert res.returncode == 1 and res.stdout.strip() == "build.md has no ## Round 1"


def test_builder_done_missing_build_md(tmp_path):
    wt, before = worktree_with_base(tmp_path)
    commit_file(wt, "a.py")
    res = run_cli("builder-done", wt, before, tmp_path / "nope.md", "1")
    assert res.returncode == 1 and res.stdout.strip() == "build.md has no ## Round 1"


def test_builder_done_ok(tmp_path):
    wt, before = worktree_with_base(tmp_path)
    commit_file(wt, "a.py")
    build = tmp_path / "build.md"
    build.write_text("## Round 1\nx\n## Round 2\n")
    res = run_cli("builder-done", wt, before, build, "2")
    assert res.returncode == 0 and res.stdout.strip() == "done"


def clean_repo(tmp_path, jobs):
    repo = make_repo(tmp_path, None, agents=[])
    write_board(repo, jobs)
    git_init(repo)
    return repo


def test_migration_check_flags_active_loop(tmp_path):
    repo = clean_repo(tmp_path, [])
    loop = repo / "factory" / ".claude" / "ralph-loop.local.md"
    loop.parent.mkdir(parents=True)
    loop.write_text("---\nactive: true\niteration: 3\n---\n\ngo\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "loop")
    res = run_cli("migration-check", repo, "--loop-file", "factory/.claude/ralph-loop.local.md")
    assert res.returncode == 1
    assert "loop active (factory/.claude/ralph-loop.local.md)" in res.stdout
    assert run_cli("migration-check", repo).stdout.strip() == "ok"


def test_migration_check_inactive_loop_ok(tmp_path):
    repo = clean_repo(tmp_path, [])
    loop = repo / "factory" / ".claude" / "ralph-loop.local.md"
    loop.parent.mkdir(parents=True)
    loop.write_text("---\nactive: false\n---\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "loop")
    assert run_cli("migration-check", repo, "--loop-file", "factory/.claude/ralph-loop.local.md").stdout.strip() == "ok"


def test_migration_check_flags_dirty_tree(tmp_path):
    repo = clean_repo(tmp_path, [])
    (repo / "stray.txt").write_text("x")
    res = run_cli("migration-check", repo)
    assert res.returncode == 1 and "working tree not clean" in res.stdout


def test_migration_check_flags_in_flight_job(tmp_path):
    repo = clean_repo(tmp_path, [{"id": "003-x", "stage": "review"}, {"id": "004-y", "stage": "arbitration"}])
    res = run_cli("migration-check", repo)
    assert res.returncode == 1
    assert "job 003-x in flight at stage review" in res.stdout
    assert "job 004-y in flight at stage arbitration" in res.stdout


def test_migration_check_ok_with_needs_human_and_merged(tmp_path):
    repo = clean_repo(tmp_path, [{"id": "001-a", "stage": "merged"}, {"id": "007-b", "stage": "needs-human"}])
    res = run_cli("migration-check", repo)
    assert res.returncode == 0 and res.stdout.strip() == "ok"
