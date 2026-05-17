"""Tests for the ``saster-har`` CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from saster_harness.har_cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "har" / "sample_chat.har"


def test_cli_emits_json_report_to_stdout() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [str(FIXTURE)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["harness_version"] == "0.1.0"
    assert report["summary"]["turns_captured"] >= 4
    # The fixture should fire at least SASTER-26 (recon question) and
    # SASTER-31 (record-list POST with sensitive fields).
    assert "SASTER-26" in report["summary"]["by_pattern"]
    assert "SASTER-31" in report["summary"]["by_pattern"]


def test_cli_writes_output_file(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "report.json"
    result = runner.invoke(main, [str(FIXTURE), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    report = json.loads(out.read_text())
    assert "events" in report


def test_cli_filters_by_detector_list() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [str(FIXTURE), "--detectors", "SASTER-31"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    # With only SASTER-31 enabled, SASTER-26 should not appear in the
    # by_pattern summary.
    assert "SASTER-26" not in report["summary"]["by_pattern"]
    assert "SASTER-31" in report["summary"]["by_pattern"]


def test_cli_rejects_unknown_detector_id() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [str(FIXTURE), "--detectors", "SASTER-999"])
    assert result.exit_code != 0
    assert "Unknown detector" in result.output


def test_cli_rejects_missing_har_file(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = tmp_path / "absent.har"
    result = runner.invoke(main, [str(missing)])
    assert result.exit_code != 0


def test_cli_event_structure_is_serialisable() -> None:
    """Every event in the report round-trips through JSON without loss."""
    runner = CliRunner()
    result = runner.invoke(main, [str(FIXTURE)])
    assert result.exit_code == 0
    report = json.loads(result.output)
    for event in report["events"]:
        for required in ("saster_id", "pattern_name", "tier", "evidence"):
            assert required in event
