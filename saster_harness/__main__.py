"""Command-line entrypoint: ``python -m saster_harness`` or ``saster-harness``.

The CLI is intentionally minimal in v0.1: it loads a Python config file
that constructs a :class:`MonitoringConfig` (and optionally a custom
adapter), then runs the harness in blocking mode. Practitioners who need
richer lifecycle control should embed :class:`MonitoringHarness` directly.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import click

from .adapters import HttpJsonAdapter
from .config import HarnessMode, MonitoringConfig
from .harness import MonitoringHarness


@click.command()
@click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a Python file exposing a top-level `config` MonitoringConfig.",
)
@click.option(
    "--mode",
    type=click.Choice([m.value for m in HarnessMode], case_sensitive=False),
    default=None,
    help="Override the config's mode (observe / probe / induce).",
)
@click.option(
    "--allow-induce",
    is_flag=True,
    help="Required when --mode=induce. Active adversarial probing is off by default.",
)
@click.option("-v", "--verbose", count=True, help="Increase logging verbosity (-v, -vv).")
def cli(config_path: Path, mode: str | None, allow_induce: bool, verbose: int) -> None:
    """Run saster-harness with the given configuration file."""
    level = logging.WARNING - (verbose * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = _load_config(config_path)
    if mode is not None:
        config.mode = HarnessMode(mode)

    harness = MonitoringHarness(config, adapter=HttpJsonAdapter(), allow_induce=allow_induce)
    harness.start(block=True)


def _load_config(path: Path) -> MonitoringConfig:
    spec = importlib.util.spec_from_file_location("user_config", path)
    if spec is None or spec.loader is None:
        raise click.UsageError(f"could not load config file {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = getattr(module, "config", None)
    if not isinstance(config, MonitoringConfig):
        raise click.UsageError(
            f"config file {path} must define a top-level `config` of type MonitoringConfig"
        )
    return config


if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
    sys.exit(0)
