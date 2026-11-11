import json

import pytest
from conftest import MINIMAL, commit_file, git, git_init, make_repo, run_cli

from factory_config import escalate_hit, lane, load, validate

AGENTS = ["factory-review-logic"]
LANES = "lanes:\n  trivial: {paths: ['*.md', 'test/**'], max_changed_lines: 10, skip: [spec, approval]}\n"


def errors(tmp_path, extra):
    return validate(make_repo(tmp_path, MINIMAL + extra, agents=AGENTS))


def test_lanes_default_empty(tmp_path):
    assert load(make_repo(tmp_path, MINIMAL, agents=AGENTS))["lanes"] == {}


def test_valid_lanes(tmp_path):
    assert errors(tmp_path, LANES) == []


@pytest.mark.parametrize("extra,msg", [
    ("lanes: {big: {paths: [a]}}\n", "factory.yaml: unknown key 'lanes.big'"),
    ("lanes: {trivial: {paths: [a], x: 1}}\n", "factory.yaml: unknown key 'lanes.trivial.x'"),
    ("lanes: {trivial: {}}\n", "factory.yaml: lanes.trivial.paths must be a non-empty list of strings"),
    ("lanes: {trivial: {paths: [a], max_changed_lines: -1}}\n", "factory.yaml: lanes.trivial.max_changed_lines must be a whole number"),
    ("lanes: {trivial: {paths: [a], skip: [review]}}\n", "factory.yaml: lanes.trivial.skip must be a list of spec, approval"),
    ("lanes: [x]\n", "factory.yaml: lanes must be a mapping"),
])
def test_bad_lanes(tmp_path, extra, msg):
    assert msg in errors(tmp_path, extra)


def test_escalate_object_form(tmp_path):
    assert errors(tmp_path, "escalate:\n  - plain prose\n  - {when: core, paths: [src/main.ts]}\n") == []


@pytest.mark.parametrize("extra,msg", [
    ("escalate: [{paths: [a]}]\n", "factory.yaml: escalate[0] needs a when"),
    ("escalate: [{when: x, paths: []}]\n", "factory.yaml: escalate[0] paths must be a non-empty list of strings"),
    ("escalate: [{when: x, y: 1}]\n", "factory.yaml: unknown key 'escalate[0].y'"),
    ("escalate: [3]\n", "factory.yaml: escalate[0] must be a string or a mapping with when and paths"),
    ("escalate: x\n", "factory.yaml: escalate must be a list"),
])
def test_bad_escalate(tmp_path, extra, msg):
    assert msg in errors(tmp_path, extra)


def cfg(**kw):
    base = {"lanes": {"trivial": {"paths": ["*.md", "test/**"], "max_changed_lines": 10, "skip": ["spec"]}},
            "escalate": [], "tests": "ok"}
    return {**base, **kw}


def test_lane_trivial():
    res = lane(cfg(), ["README.md", "test/a.ts"], 10)
    assert res["lane"] == "trivial" and res["skip"] == ["spec"]


@pytest.mark.parametrize("changed,lines,why", [
    (["README.md", "src/a.ts"], 1, "outside lane paths: src/a.ts"),
    (["README.md"], 11, "11 changed lines exceeds 10"),
    ([], 0, "no changed files"),
])
def test_lane_full(changed, lines, why):
    res = lane(cfg(), changed, lines)
    assert res["lane"] == "full" and why in res["why"]


def test_lane_full_without_config():
    assert lane(cfg(lanes={}), ["README.md"], 1)["lane"] == "full"


def test_lane_escalate_path_beats_lane():
    c = cfg(escalate=[{"when": "docs gate", "paths": ["README.md"]}])
    res = lane(c, ["README.md"], 1)
    assert res["lane"] == "full" and "docs gate" in res["why"]


def test_escalate_hit():
    c = cfg(escalate=["prose", {"when": "main", "paths": ["src/main.ts"]}, {"when": "env", "paths": [".env.example"]}])
    res = escalate_hit(c, ["src/main.ts", "README.md"])
    assert res == {"hit": [{"when": "main", "files": ["src/main.ts"]}], "unchecked": ["prose"]}


def test_escalate_hit_thin_tests():
    res = escalate_hit(cfg(tests="thin"), ["scripts/x.mjs", "README.md"])
    assert res["hit"][0]["files"] == ["scripts/x.mjs"]
    assert escalate_hit(cfg(tests="thin"), ["README.md"])["hit"] == []
    assert escalate_hit(cfg(tests="ok"), ["scripts/x.mjs"])["hit"] == []


def test_lane_and_escalate_hit_cli(tmp_path):
    text = MINIMAL + LANES + "escalate:\n  - {when: pkg, paths: [package.json]}\n"
    repo = make_repo(tmp_path, text, agents=AGENTS)
    git_init(repo)
    git(repo, "checkout", "-q", "-b", "factory/001-x")
    commit_file(repo, "README.md", "a\nb\n")
    res = run_cli("lane", repo, "main", "factory/001-x")
    assert res.returncode == 0 and json.loads(res.stdout)["lane"] == "trivial"
    assert json.loads(run_cli("escalate-hit", repo, "main", "factory/001-x").stdout) == {"hit": [], "unchecked": []}
    commit_file(repo, "package.json", "{}\n")
    out = json.loads(run_cli("lane", repo, "main", "factory/001-x").stdout)
    assert out["lane"] == "full"
    hit = json.loads(run_cli("escalate-hit", repo, "main", "factory/001-x").stdout)["hit"]
    assert hit == [{"when": "pkg", "files": ["package.json"]}]


def test_lane_cli_counts_lines(tmp_path):
    repo = make_repo(tmp_path, MINIMAL + LANES, agents=AGENTS)
    git_init(repo)
    commit_file(repo, "README.md", "x\n" * 11)
    out = json.loads(run_cli("lane", repo, "HEAD~1", "HEAD").stdout)
    assert out["lane"] == "full" and "11 changed lines" in out["why"]


def test_triage_model_role(tmp_path):
    assert errors(tmp_path, "models: {triage: haiku}\n") == []
