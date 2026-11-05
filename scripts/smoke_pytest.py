"""pytest plugin of `devbox run smoke` (platform-owned: /shared:update-service refreshes it).

Loaded with `-p scripts.smoke_pytest`. It registers the `smoke` marker, provides the
`smoke_base_url` fixture, skips smoke tests when SMOKE_BASE_URL is empty (so `devbox run test`
and `ci` never reach a deployment) and, with `--smoke-report`, prints one
`PASS|FAIL|SKIP  <nodeid>` line per smoke test and a summary line (spec 091).
"""

from __future__ import annotations

import os

import pytest

_RESULTS: dict[str, str] = {}
_EXIT: list[int] = []


def _base_url() -> str:
    return os.environ.get("SMOKE_BASE_URL", "").strip().rstrip("/")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--smoke-report",
        action="store_true",
        default=False,
        help="print one PASS/FAIL/SKIP line per smoke test and a summary line",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "smoke: runs against a deployment (SMOKE_BASE_URL)")


@pytest.fixture()
def smoke_base_url() -> str:
    """The base URL of the deployment under test, without a trailing slash."""
    url = _base_url()
    if not url:
        pytest.skip("SMOKE_BASE_URL is not set")
    return url


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _base_url():
        return
    skip = pytest.mark.skip(reason="SMOKE_BASE_URL is not set")
    for item in items:
        if item.get_closest_marker("smoke") is not None:
            item.add_marker(skip)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.failed:
        _RESULTS[report.nodeid] = "FAIL"
    elif report.skipped:
        _RESULTS.setdefault(report.nodeid, "SKIP")
    elif report.when == "call":
        _RESULTS.setdefault(report.nodeid, "PASS")


def pytest_unconfigure(config: pytest.Config) -> None:
    """Runs after pytest's own summary line, so the result lines are the last thing printed."""
    if not config.getoption("--smoke-report", default=False):
        return
    if _EXIT and _EXIT[0] not in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED):
        # the runner itself broke: there are no reliable result lines
        print("FAIL  (smoke recipe)", flush=True)
        return
    if not _RESULTS:
        print("0 smoke tests", flush=True)
        return
    for nodeid, result in _RESULTS.items():
        print(f"{result}  {nodeid}")
    counts = {r: sum(1 for v in _RESULTS.values() if v == r) for r in ("PASS", "FAIL", "SKIP")}
    p, f, k = counts["PASS"], counts["FAIL"], counts["SKIP"]
    print(f"smoke: {p} passed, {f} failed, {k} skipped", flush=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    no_tests = exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED
    if session.config.getoption("--smoke-report") and no_tests:
        session.exitstatus = pytest.ExitCode.OK
    _EXIT.append(int(session.exitstatus))
