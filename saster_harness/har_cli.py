"""``saster-har`` — command-line HAR import for offline audit.

Reads a HAR file, runs the full saster-harness detector chain against
every chat-shape entry, and emits a structured JSON report. This is
the no-MITM audit path: practitioners with a browser-accessible agent
can export a HAR after a session and get a SASTER report without
running mitmproxy or wiring the harness into live traffic.

Typical usage::

    saster-har session.har                       # report to stdout
    saster-har session.har -o report.json        # report to a file
    saster-har session.har --detectors SASTER-26,SASTER-31
    saster-har session.har --no-redact           # disable default redaction
                                                 # (a warning fires)
    saster-har session.har --session-strategy "header:X-Session-Id"

The report shape is stable across patch releases:

    {
      "har_path": "session.har",
      "harness_version": "0.1.0",
      "summary": {
        "turns_captured": N,
        "events_emitted": M,
        "by_pattern": {"SASTER-26": 3, "SASTER-31": 1, ...}
      },
      "events": [DetectionEvent.to_dict(), ...]
    }
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import click

from . import __version__
from .adapters.har_adapter import HARAdapter
from .detector import SasterDetector
from .detectors import (
    saster_18,
    saster_24,
    saster_26,
    saster_27,
    saster_28,
    saster_31,
    saster_33,
)
from .event import DetectionEvent

# Detector lookup table keyed by canonical SASTER id. Used to resolve
# the ``--detectors`` filter on the command line.
_DETECTOR_REGISTRY: dict[str, SasterDetector] = {
    "SASTER-18": saster_18.DETECTOR,
    "SASTER-24": saster_24.DETECTOR,
    "SASTER-26": saster_26.DETECTOR,
    "SASTER-27": saster_27.DETECTOR,
    "SASTER-28": saster_28.DETECTOR,
    "SASTER-31": saster_31.DETECTOR,
    "SASTER-33": saster_33.DETECTOR,
}


@click.command(name="saster-har")
@click.argument("har_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o", "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the JSON report to this file instead of stdout.",
)
@click.option(
    "--detectors", "-d", "detector_filter",
    default=None,
    help=(
        "Comma-separated list of SASTER ids to run. Default: all seven "
        "passive detectors. Example: --detectors SASTER-26,SASTER-31"
    ),
)
@click.option(
    "--session-strategy", "session_strategy",
    default="auto",
    show_default=True,
    help=(
        "Session-id derivation: 'auto', 'cookie', 'time', or "
        "'header:NAME'. See docs/har_import.md."
    ),
)
@click.option(
    "--time-window", "time_window_seconds",
    type=int, default=30, show_default=True,
    help="Time-window correlator window size, in seconds.",
)
@click.option(
    "--no-redact", "no_redact",
    is_flag=True, default=False,
    help=(
        "Disable the default redaction pass. Sensitive headers and "
        "body fields will flow to detectors and event sinks. Only use "
        "on HARs you've already scrubbed."
    ),
)
@click.option(
    "-v", "--verbose", count=True,
    help="Increase logging verbosity (-v info, -vv debug).",
)
def main(
    har_path: Path,
    output: Path | None,
    detector_filter: str | None,
    session_strategy: str,
    time_window_seconds: int,
    no_redact: bool,
    verbose: int,
) -> None:
    """Audit a HAR file with the saster-harness detector chain."""
    _configure_logging(verbose)

    detectors = _resolve_detectors(detector_filter)
    adapter = HARAdapter(
        session_id_strategy=session_strategy,
        redact=not no_redact,
        time_window_seconds=time_window_seconds,
    )

    turns_captured = 0
    events: list[DetectionEvent] = []
    for turn in adapter.read_file(har_path):
        turns_captured += 1
        for detector in detectors:
            try:
                event = detector.evaluate(turn)
            except NotImplementedError:
                continue
            except Exception:  # pragma: no cover — defensive
                logging.exception(
                    "Detector %s crashed on turn %s/%d",
                    detector.saster_id, turn.session_id, turn.turn_idx,
                )
                continue
            if event is not None:
                if not event.agent_name:
                    event.agent_name = f"har:{har_path.name}"
                events.append(event)

    report = _build_report(har_path, turns_captured, events)
    serialised = json.dumps(report, indent=2, sort_keys=True)
    if output is None:
        click.echo(serialised)
    else:
        output.write_text(serialised + "\n", encoding="utf-8")
        click.echo(
            f"Wrote {len(events)} event(s) across {turns_captured} captured "
            f"turn(s) to {output}",
            err=True,
        )


def _resolve_detectors(detector_filter: str | None) -> list[SasterDetector]:
    if detector_filter is None:
        return list(_DETECTOR_REGISTRY.values())
    requested = [
        token.strip().upper() for token in detector_filter.split(",") if token.strip()
    ]
    unknown = [pid for pid in requested if pid not in _DETECTOR_REGISTRY]
    if unknown:
        raise click.BadParameter(
            f"Unknown detector id(s): {unknown}. Choose from "
            f"{sorted(_DETECTOR_REGISTRY)}."
        )
    return [_DETECTOR_REGISTRY[pid] for pid in requested]


def _build_report(
    har_path: Path,
    turns_captured: int,
    events: Iterable[DetectionEvent],
) -> dict[str, object]:
    events_list = list(events)
    by_pattern = Counter(event.saster_id for event in events_list)
    return {
        "har_path": str(har_path),
        "harness_version": __version__,
        "summary": {
            "turns_captured": turns_captured,
            "events_emitted": len(events_list),
            "by_pattern": dict(sorted(by_pattern.items())),
        },
        "events": [event.to_dict() for event in events_list],
    }


def _configure_logging(verbose: int) -> None:
    level = max(logging.DEBUG, logging.WARNING - verbose * 10)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


if __name__ == "__main__":
    main()  # pragma: no cover
