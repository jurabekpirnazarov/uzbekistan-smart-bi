"""Guards the verified SIAT parser (pipelines/siat_ingest.py) against regressions."""

from __future__ import annotations

from pipelines import siat_ingest


def test_selftest_passes() -> None:
    assert siat_ingest.selftest() == 0


def test_parse_number_handles_local_formats() -> None:
    assert siat_ingest.parse_number("1 234,5") == 1234.5
    assert siat_ingest.parse_number("35,648.1") == 35648.1
    assert siat_ingest.parse_number("…") is None


def test_district_code_maps_to_region() -> None:
    assert siat_ingest.classify_territory("1730212", "") == ("district", "1730")
