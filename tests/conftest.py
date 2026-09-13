# tests/conftest.py

"""Shared pytest fixtures for Cy-TH tests."""

# === Imports ===

from __future__ import annotations
from pathlib import Path
import pytest

from tests.factories.usaspending import (
    ensure_prime_txn_csv,
    group_rows_by_award,
    load_prime_txn_rows,
)


# === CLI ===

def pytest_addoption(parser: pytest.Parser) -> None:
    """Register suite options.

    #### Options:
        - `--offline` — use only local cache / TEMP extracts (no USASpending download)
    """

    parser.addoption(
        "--offline",
        action="store_true",
        default=False,
        help="Do not download from USASpending; require cache or TEMP research CSV.",
    )


# === Fixtures ===

@pytest.fixture(scope="session")
def allow_network(pytestconfig: pytest.Config) -> bool:
    """Whether fixtures may hit the USASpending network."""

    return not bool(pytestconfig.getoption("--offline"))

@pytest.fixture(scope="session")
def prime_txn_csv_path(allow_network: bool) -> Path:
    """Session-scoped path to a projected prime-transactions CSV (real USASpending)."""

    return ensure_prime_txn_csv(allow_network=allow_network)

@pytest.fixture(scope="session")
def prime_txn_rows(prime_txn_csv_path: Path) -> list[dict[str, str]]:
    """All rows from the cached / downloaded prime-txn extract."""

    rows = load_prime_txn_rows(prime_txn_csv_path)
    assert rows, "expected at least one prime transaction row in test extract"
    return rows

@pytest.fixture(scope="session")
def prime_txn_sample(prime_txn_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Smaller sample for fast tests (first 2k rows, or all if fewer)."""

    return prime_txn_rows[:2000]

@pytest.fixture(scope="session")
def awards_by_id(prime_txn_rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Award → transaction rows for the full extract."""

    grouped = group_rows_by_award(prime_txn_rows)
    assert grouped, "expected at least one award group"
    return grouped
