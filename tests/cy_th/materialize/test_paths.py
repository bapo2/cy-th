# tests/cy_th/materialize/test_paths.py

"""Tests for materialization path + run-ID helpers."""

# === Imports ===

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest

from cy_th.materialize.paths import (
    DEFAULT_DATA_ROOT,
    is_run_id,
    new_run_id,
    read_current,
    resolve_data_root,
    set_dir,
    staging_db_path,
    tmp_set_dir,
    write_current_atomic,
)


# === Run IDs ===

def test_new_run_id_form_and_optional_suffix() -> None:
    when = datetime(2026, 9, 14, 2, 15, 30, tzinfo=timezone.utc)
    rid = new_run_id(when=when, suffix="a1b2c3")
    assert rid == "20260914T021530Z_a1b2c3"
    assert is_run_id(rid)
    assert not is_run_id("nope")

def test_new_run_id_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        new_run_id(when=datetime(2026, 1, 1, 0, 0, 0))

def test_new_run_id_rejects_bad_suffix() -> None:
    with pytest.raises(ValueError, match="suffix"):
        new_run_id(suffix="ZZZZZZ")


# === Layout / CURRENT ===

def test_resolve_data_root_defaults() -> None:
    assert resolve_data_root() == DEFAULT_DATA_ROOT
    assert resolve_data_root("custom") == Path("custom")

def test_set_and_staging_paths_validate_run_id(tmp_path: Path) -> None:
    rid = "20260914T021530Z_abcdef"
    assert set_dir(tmp_path, rid) == tmp_path / "sets" / rid
    assert staging_db_path(tmp_path, rid) == tmp_path / ".staging" / f"{rid}.duckdb"
    assert tmp_set_dir(tmp_path, rid) == tmp_path / f".tmp-{rid}"
    with pytest.raises(ValueError, match="invalid run_id"):
        set_dir(tmp_path, "bad")

def test_write_current_atomic_roundtrip(tmp_path: Path) -> None:
    rid = "20260914T021530Z_abcdef"
    assert read_current(tmp_path) is None
    write_current_atomic(tmp_path, rid)
    assert read_current(tmp_path) == rid
