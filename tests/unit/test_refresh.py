from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from pipelines import refresh
from pipelines.scheduler import next_run

NOW = datetime(2026, 10, 13, 12, 0)


def test_first_run_is_immediate() -> None:
    assert next_run(None, 3, "03:00", NOW) == NOW


def test_next_run_is_n_days_after_last_success_at_fixed_time() -> None:
    assert next_run(datetime(2026, 10, 12, 3, 5), 3, "03:00", NOW) == datetime(2026, 10, 15, 3, 0)


def test_overdue_run_starts_now() -> None:
    assert next_run(datetime(2026, 10, 1, 3, 0), 3, "03:00", NOW) == NOW


def test_fingerprints_detect_changed_datasets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh, "RAW", tmp_path)
    (tmp_path / "246.meta.json").write_text(json.dumps({"sha256": "aaa"}), encoding="utf-8")
    before = refresh.fingerprints([246, 248])
    assert before == {246: "aaa", 248: None}
    (tmp_path / "246.meta.json").write_text(json.dumps({"sha256": "bbb"}), encoding="utf-8")
    after = refresh.fingerprints([246, 248])
    assert [i for i in (246, 248) if after[i] and after[i] != before[i]] == [246]


def test_lock_prevents_parallel_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refresh, "LOCK", tmp_path / "refresh.lock")
    assert refresh.acquire_lock() is True
    assert refresh.acquire_lock() is False


def test_mapped_ids_come_from_indicator_map() -> None:
    ids = refresh.mapped_ids()
    assert 246 in ids and 307 in ids and ids == sorted(set(ids))
