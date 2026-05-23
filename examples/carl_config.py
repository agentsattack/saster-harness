"""Wire-mode example: harness config for capturing traffic from Carl.

Intended for the optional wire-mode quickstart documented in
``carl/README.md``. In v0.1 the recommended end-to-end check is the
standalone scenario runners (``python -m carl.run_recon``); this config
file exists so the slide-18 / README quickstart command line works as
advertised::

    python -m saster_harness --config examples/carl_config.py

The harness will start on port 8888 in OBSERVE mode with all seven
v0.1 detectors loaded.
"""

from __future__ import annotations

from saster_harness import HarnessMode, MonitoringConfig

config = MonitoringConfig(
    agent_name="carl-demo",
    # Carl's default port is 8801 (carl/server.py:93). Override at
    # Carl-server start via CARL_PORT=<port> if you need a different one.
    agent_endpoint="http://localhost:8801/chat",
    # Host fragments, NOT tool names — matched against turn.target_host
    # with case-insensitive bidirectional substring. "localhost" covers
    # both Carl's own endpoint and an upstream LLM running on the same
    # box; see SKILL.md's DECLARED allow-list section for the footguns.
    authorized_tools=["localhost"],
    max_drift_score=25,
    max_autonomous_hits=2,
    probe_interval_hours=0,  # no probing in OBSERVE
    alert_webhook=None,      # logs only — no external webhook
    listen_port=8888,
    baseline_turns=3,        # short baseline for demo runs
    mode=HarnessMode.OBSERVE,
)
