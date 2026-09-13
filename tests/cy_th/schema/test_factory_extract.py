# tests/cy_th/schema/test_factory_extract.py

"""Tests for the real USASpending extract factory / cache."""

# === Imports ===

from pathlib import Path

from cy_th.schema.projection import TRANSACTION_DOWNLOAD_COLUMNS
from tests.factories.usaspending import ensure_prime_txn_csv, load_prime_txn_rows


# === Cache ===

def test_ensure_prime_txn_csv_returns_nonempty_projected_file(
    allow_network: bool,
) -> None:
    path = ensure_prime_txn_csv(allow_network=allow_network)
    assert path.is_file()
    rows = load_prime_txn_rows(path, limit=5)
    assert rows
    assert set(rows[0]).issuperset(TRANSACTION_DOWNLOAD_COLUMNS)
    assert "tests" in path.parts and ".cache" in path.parts  # Cached under tests/.cache

def test_fixture_path_matches_factory(
    prime_txn_csv_path: Path,
    allow_network: bool,
) -> None:
    assert Path(prime_txn_csv_path) == ensure_prime_txn_csv(allow_network=allow_network)
