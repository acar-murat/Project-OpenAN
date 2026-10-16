"""Shared test fixtures.

``case`` records a documented test case (id, title, LLD reference, input, expected and
actual result). When ``TEST_CASES_OUTPUT`` names a file, every recorded case is appended
to it as one JSON line with the test's outcome; ``scripts/test_report.py`` turns those
lines into ``docs/test-cases.md``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

CASES_OUTPUT_ENV = "TEST_CASES_OUTPUT"


class CaseRecord:
    def __init__(self, nodeid: str) -> None:
        self.data: dict[str, Any] = {"test": nodeid}

    def define(self, case_id: str, title: str, *, lld: str, input: Any, expected: dict[str, Any],
               suite: str) -> None:
        self.data.update(id=case_id, title=title, lld=lld, input=input, expected=expected, suite=suite)

    def check(self, actual: dict[str, Any]) -> None:
        """Record ``actual`` and assert it matches every expected key."""
        self.data["actual"] = actual
        expected = self.data["expected"]
        assert {key: actual.get(key) for key in expected} == expected


@pytest.fixture
def case(request) -> CaseRecord:
    record = CaseRecord(request.node.nodeid)
    request.node.case_record = record
    return record


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    record = getattr(item, "case_record", None)
    path = os.environ.get(CASES_OUTPUT_ENV)
    if record is None or not path or "id" not in record.data:
        return
    if report.when == "call" or (report.when == "setup" and report.failed):
        line = {**record.data, "outcome": report.outcome}
        if report.failed:
            line["failure"] = str(report.longrepr).splitlines()[-1][:500]
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
