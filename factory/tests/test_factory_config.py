from conftest import MINIMAL, make_repo, run_cli

from factory_config import load, validate


def test_valid_minimal_config(tmp_path):
    repo = make_repo(tmp_path, MINIMAL, agents=["factory-review-logic"])
    assert validate(repo) == []
    cfg = load(repo)
    assert cfg["max_rework"] == 2 and cfg["max_arbiter_rework"] == 1
    assert cfg["merge_gate"] == ["test"]
    assert cfg["builder"] == {"runtime": "claude", "resume": "session"}
    assert cfg["worktrees"] == "../repo-factory"


def test_unknown_key_named(tmp_path):
    repo = make_repo(tmp_path, MINIMAL + "reviewrs: []\n", agents=["factory-review-logic"])
    assert "factory.yaml: unknown key 'reviewrs'" in validate(repo)


def test_reviewer_without_agent_file(tmp_path):
    repo = make_repo(tmp_path, MINIMAL, agents=[])
    assert (
        "factory.yaml: reviewer 'logic' has no .claude/agents/factory-review-logic.md"
        in validate(repo)
    )


def test_merge_gate_names_missing_command(tmp_path):
    repo = make_repo(tmp_path, MINIMAL + "merge_gate: [lint]\n", agents=["factory-review-logic"])
    assert "factory.yaml: merge_gate 'lint' is not in commands" in validate(repo)


def test_command_runtime_needs_prompt_placeholder(tmp_path):
    text = MINIMAL + "builder: {runtime: command, command: run.sh}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic"])
    assert "factory.yaml: builder.command must contain {prompt_file}" in validate(repo)


def test_bad_runtime(tmp_path):
    repo = make_repo(tmp_path, MINIMAL + "builder: {runtime: docker}\n", agents=["factory-review-logic"])
    assert "factory.yaml: builder.runtime must be claude or command" in validate(repo)


def test_no_test_command_gives_empty_merge_gate(tmp_path):
    text = "version: 1\nbase: main\ncommands: {build: make}\nreviewers:\n  - {name: logic, why: x}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic"])
    assert validate(repo) == []
    assert load(repo)["merge_gate"] == []


def test_duplicate_and_bad_reviewer_names(tmp_path):
    text = (
        "version: 1\nbase: main\ncommands: {test: t}\nreviewers:\n"
        "  - {name: logic, why: x}\n  - {name: logic, why: y}\n  - {name: Bad_Name, why: z}\n"
    )
    repo = make_repo(tmp_path, text, agents=["factory-review-logic", "factory-review-Bad_Name"])
    errors = validate(repo)
    assert "factory.yaml: reviewer 'logic' appears twice" in errors
    assert "factory.yaml: reviewer name 'Bad_Name' must match ^[a-z][a-z0-9-]*$" in errors


def test_reviewer_needs_why(tmp_path):
    text = "version: 1\nbase: main\ncommands: {test: t}\nreviewers:\n  - {name: logic}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic"])
    assert "factory.yaml: reviewer 'logic' needs a why" in validate(repo)


def test_qa_agent_must_exist(tmp_path):
    repo = make_repo(tmp_path, MINIMAL + "qa: {agent: factory-qa}\n", agents=["factory-review-logic"])
    assert "factory.yaml: qa agent 'factory-qa' has no .claude/agents/factory-qa.md" in validate(repo)


def test_bad_model_value(tmp_path):
    repo = make_repo(tmp_path, MINIMAL + "models: {builder: gpt5 high}\n", agents=["factory-review-logic"])
    assert "factory.yaml: models.builder 'gpt5 high' must be '<model> [effort]'" in validate(repo)


def test_missing_required_keys_and_version(tmp_path):
    repo = make_repo(tmp_path, "version: 2\n", agents=[])
    errors = validate(repo)
    assert "factory.yaml: version must be 1" in errors
    assert "factory.yaml: base is required" in errors
    assert "factory.yaml: commands is required" in errors
    assert "factory.yaml: reviewers must be a non-empty list" in errors


def test_not_a_mapping(tmp_path):
    repo = make_repo(tmp_path, "- a\n- b\n", agents=[])
    assert validate(repo) == ["factory.yaml: must be a mapping"]


def test_invalid_yaml(tmp_path):
    repo = make_repo(tmp_path, "base: [unclosed\n", agents=[])
    errors = validate(repo)
    assert len(errors) == 1 and errors[0].startswith("factory.yaml: invalid YAML")


def test_missing_file(tmp_path):
    repo = make_repo(tmp_path, None, agents=[])
    assert validate(repo) == ["factory.yaml: not found; run /factory:setup"]


def test_validate_cli(tmp_path):
    repo = make_repo(tmp_path, MINIMAL, agents=["factory-review-logic"])
    ok = run_cli("validate", repo)
    assert ok.returncode == 0 and ok.stdout == "ok\n"
    bad = make_repo(tmp_path / "b", MINIMAL, agents=[])
    res = run_cli("validate", bad)
    assert res.returncode == 1 and res.stdout.startswith("factory.yaml: reviewer 'logic'")


def test_get_cli_prints_json(tmp_path):
    repo = make_repo(tmp_path, MINIMAL, agents=["factory-review-logic"])
    assert run_cli("get", repo, "builder.runtime").stdout == '"claude"\n'
    assert run_cli("get", repo, "commands").stdout == '{"test": "pytest"}\n'
    assert run_cli("get", repo, "nope").stdout == "null\n"
    assert run_cli("get", repo, "commands.test.deeper").stdout == "null\n"


def test_reviewer_entry_not_a_mapping(tmp_path):
    text = "version: 1\nbase: main\ncommands: {test: t}\nreviewers: [logic]\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic"])
    assert "factory.yaml: each reviewer must be a mapping with name and why" in validate(repo)


# Final review I1: wrong types and typos are named, never a traceback.
import pytest


@pytest.mark.parametrize("extra,message", [
    ("builder: claude\n", "factory.yaml: builder must be a mapping"),
    ("models: [a]\n", "factory.yaml: models must be a mapping"),
    ("merge_gate: test\n", "factory.yaml: merge_gate must be a list"),
    ("merge_gate: 5\n", "factory.yaml: merge_gate must be a list"),
    ("max_rework: two\n", "factory.yaml: max_rework must be a whole number"),
    ("models: {reviewr: sonnet}\n", "factory.yaml: unknown key 'models.reviewr'"),
    ("builder: {comand: x}\n", "factory.yaml: unknown key 'builder.comand'"),
    ("scout: {todo_path: [a]}\n", "factory.yaml: unknown key 'scout.todo_path'"),
    ("qa: {agent: factory-review-logic, paths: web/}\n", "factory.yaml: qa paths must be a non-empty list of strings"),
    ("tests: maybe\n", "factory.yaml: tests must be none, thin or ok"),
])
def test_bad_types_and_nested_typos(tmp_path, extra, message):
    repo = make_repo(tmp_path, MINIMAL + extra, agents=["factory-review-logic"])
    assert message in validate(repo)


def test_reviewer_unknown_field_and_bad_model(tmp_path):
    text = "version: 1\nbase: main\ncommands: {test: t}\nreviewers:\n  - {name: logic, why: x, path: [web/], model: gpt}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic"])
    errors = validate(repo)
    assert "factory.yaml: unknown key 'reviewers.logic.path'" in errors
    assert "factory.yaml: reviewer 'logic' model 'gpt' must be '<model> [effort]'" in errors


def test_reviewer_named_qa_reserved(tmp_path):
    text = "version: 1\nbase: main\ncommands: {test: t}\nreviewers:\n  - {name: logic, why: x}\n  - {name: qa, why: y}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic", "factory-review-qa"])
    assert "factory.yaml: reviewer name 'qa' is reserved for QA" in validate(repo)


# Final review I2: a round can never have zero reviewers.
def test_needs_an_always_on_reviewer(tmp_path):
    text = "version: 1\nbase: main\ncommands: {test: t}\nreviewers:\n  - {name: api, why: x, paths: [web/]}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-api"])
    assert "factory.yaml: at least one reviewer must run every round (no paths)" in validate(repo)


def test_empty_paths_rejected(tmp_path):
    text = MINIMAL + "  - {name: api, why: y, paths: []}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic", "factory-review-api"])
    assert "factory.yaml: reviewer 'api' paths must be a non-empty list of strings" in validate(repo)


# Final review I5: test-suite state is explicit.
def test_tests_default_from_commands(tmp_path):
    repo = make_repo(tmp_path, MINIMAL, agents=["factory-review-logic"])
    assert load(repo)["tests"] == "ok"
    text = "version: 1\nbase: main\ncommands: {build: make}\nreviewers:\n  - {name: logic, why: x}\n"
    repo2 = make_repo(tmp_path / "b", text, agents=["factory-review-logic"])
    assert load(repo2)["tests"] == "none"


def test_empty_commands_allowed_when_no_tests(tmp_path):
    text = "version: 1\nbase: main\ntests: none\ncommands: {}\nreviewers:\n  - {name: logic, why: x}\n"
    repo = make_repo(tmp_path, text, agents=["factory-review-logic"])
    assert validate(repo) == []
