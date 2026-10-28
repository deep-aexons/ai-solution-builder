"""Pure decision logic of the verifier: no subprocess, no generated app."""

import importlib

import pytest
from asb_sidecar.verify import (
    Case,
    PytestRun,
    check_acceptance_mapping,
    check_matrix,
    check_tests,
)

from asb.model import parse_solution
from asb.plugins import CheckResult, VerifyResult
from asb.verify_report import render_report

verify_mod = importlib.import_module("asb_sidecar.verify")


def case(file, name, outcome="passed", message=""):
    return Case(f"tests.{file}", name, outcome, message)


def run(*cases, returncode=0, output="", **kw):
    return PytestRun(returncode, output, list(cases), **kw)


# tests ----------------------------------------------------------------------------------


def test_tests_pass_counts_only_non_matrix_cases():
    res = check_tests(
        run(case("test_at_01", "t"), case("test_permission_matrix", "x", "failed"))
    )
    assert res.status == "pass" and res.details.startswith("1 passed")


def test_tests_fail_on_failure_with_name_and_message():
    res = check_tests(
        run(case("test_a", "test_x", "failed", "boom\nmore"), returncode=1)
    )
    assert res.status == "fail" and "test_a::test_x: boom" in res.details


def test_tests_fail_on_warnings_summary():
    res = check_tests(run(case("test_a", "t"), output="== warnings summary ==\nx"))
    assert res.status == "fail" and "warnings in test run" in res.details


def test_tests_fail_on_timeout_and_missing_junit_and_zero_cases():
    assert check_tests(PytestRun(None, "", timed_out=True)).status == "fail"
    missing = check_tests(PytestRun(2, "collection exploded", junit_ok=False))
    assert missing.status == "fail" and "collection exploded" in missing.details
    only_matrix = check_tests(run(case("test_permission_matrix", "x")))
    assert only_matrix.status == "fail" and "no tests collected" in only_matrix.details


def test_tests_fail_when_pytest_exits_nonzero_without_failures():
    assert check_tests(run(case("test_a", "t"), returncode=2)).status == "fail"


# matrices ---------------------------------------------------------------------------------


def test_matrix_sample_incomplete_skip_fails():
    res = check_matrix(
        "permission_matrix",
        run(
            case("test_permission_matrix", "a"),
            case(
                "test_permission_matrix", "b", "skipped", "sample-incomplete: no sample"
            ),
        ),
        True,
    )
    assert res.status == "fail" and "sample-incomplete" in res.details


def test_matrix_approve_not_exercisable_is_allowed_and_listed():
    res = check_matrix(
        "permission_matrix",
        run(
            case("test_permission_matrix", "a"),
            case(
                "test_permission_matrix", "b", "skipped", "approve-not-exercisable: why"
            ),
        ),
        True,
    )
    assert res.status == "pass"
    assert "1 allowed skips" in res.details and "approve-not-exercisable" in res.details


def test_matrix_zero_executed_and_failure_and_missing_junit_fail():
    assert check_matrix("workflow_matrix", run(), True).status == "fail"
    bad = check_matrix(
        "workflow_matrix", run(case("test_workflow_matrix", "a", "error", "x")), True
    )
    assert bad.status == "fail"
    assert (
        check_matrix("reports", PytestRun(1, "", junit_ok=False), True).status == "fail"
    )
    assert (
        check_matrix("reports", PytestRun(None, "", timed_out=True), True).status
        == "fail"
    )


def test_matrix_not_expected_passes_with_reason():
    res = check_matrix("reports", run(), False)
    assert res.status == "pass" and res.details == "no reports"


# npm classifier ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "network"),
    [
        ("npm error code ENOTFOUND\nnpm error errno ENOTFOUND", True),
        ("npm ERR! code ETIMEDOUT\nnpm ERR! network request failed", True),
        ("npm error code EAI_AGAIN", True),
        ("npm error code ECONNREFUSED", True),
        ("npm error code ECONNRESET", True),
        (
            "npm error code E403\nnpm error 403 Forbidden - GET https://registry.npmjs.org/x",
            False,
        ),
        ("npm error code E404", False),
        ("npm error code ERESOLVE", False),
        ("error through a proxy, network unreachable", False),
        ("", False),
    ],
)
def test_npm_network_classifier(text, network):
    assert verify_mod.is_npm_network_failure(text) is network


# acceptance cross-check -------------------------------------------------------------------------

SOL = parse_solution(
    b"""
solution: s
version: 1
description: d
entities: [{name: a, label: A, fields: [{name: t, type: text}]}]
roles: {r: {a: [read]}}
acceptance_tests:
  - {id: AT-01, covers: [permissions], text: x}
""",
    "s.yaml",
)


def test_mapping_requires_a_passing_executed_case(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_at_01.py").write_text(
        'import pytest\n\n@pytest.mark.at("AT-01")\ndef test_one():\n    assert True\n'
    )
    ok = check_acceptance_mapping(SOL, tmp_path, run(case("test_at_01", "test_one")))
    assert ok.status == "pass"
    for outcome, word in (("skipped", "skipped"), ("failed", "failed")):
        res = check_acceptance_mapping(
            SOL, tmp_path, run(case("test_at_01", "test_one", outcome, "why"))
        )
        assert res.status == "fail" and "AT-01" in res.details and word in res.details
    none = check_acceptance_mapping(SOL, tmp_path, run())
    assert none.status == "fail" and "not collected" in none.details


# report rendering ----------------------------------------------------------------------------------


def test_report_escapes_pipes_and_uses_a_longer_fence():
    result = VerifyResult(
        [
            CheckResult("a", "pass", "ok | fine"),
            CheckResult("b", "fail", "first\n```py\ncode\n```"),
            CheckResult("c", "skipped", "no npm"),
        ]
    )
    text = render_report("sol", 2, result)
    assert text.startswith("# Verify report — sol (round 2 of 3)")
    assert "| a | pass | ok \\| fine |" in text
    assert "````\nfirst\n```py\ncode\n```\n````" in text
    assert "- c: no npm" in text and text.rstrip().endswith("Result: FAIL")
    assert "Result: PASS" in render_report(
        "s", 1, VerifyResult([CheckResult("a", "pass")])
    )


def test_ui_smoke_setup_timeout_is_a_failed_check_not_a_crash(tmp_path, monkeypatch):
    import subprocess

    ui = importlib.import_module("asb_sidecar.ui_smoke")
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend/dist").mkdir(parents=True)

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("manage.py", 1, output=b"stuck migrating")

    monkeypatch.setattr(ui, "_manage", slow)
    res = ui.check_ui_smoke(tmp_path, True)
    if res.status == "skipped":
        pytest.skip(res.details)  # no launchable browser here
    assert res.status == "fail" and "setup timed out" in res.details
    assert "stuck migrating" in res.details


def test_ui_smoke_missing_dist_is_a_failed_check(tmp_path):
    ui = importlib.import_module("asb_sidecar.ui_smoke")
    (tmp_path / "backend").mkdir()
    res = ui.check_ui_smoke(tmp_path, True)
    if res.status == "skipped":
        pytest.skip(res.details)
    assert res.status == "fail" and "cannot copy" in res.details
