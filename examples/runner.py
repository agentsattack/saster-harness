"""Example runner — the 90-line quickstart from slide 18 of the LayerOne talk.

Run this against your own agent by:

1. Editing ``agent_endpoint`` to point at your agent's chat endpoint.
2. Setting ``authorized_tools`` to the tool names you've vetted.
3. Pasting your Slack / Teams incoming-webhook URL into ``alert_webhook``
   (or set to ``None`` while you're calibrating).
4. Pointing your agent at ``http://localhost:8888`` as its HTTP proxy
   (mitmproxy will intercept, the harness will detect).
5. Running ``python examples/runner.py``.

Detection events stream to stdout and to your webhook in real time.
Tune ``max_drift_score`` and ``max_autonomous_hits`` against a few days
of baseline traffic before opening the alert valve fully — practitioner
calibration matters more than detector defaults.
"""

from __future__ import annotations

import logging

from saster_harness import MonitoringConfig, MonitoringHarness
from saster_harness.adapters import HttpJsonAdapter


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = MonitoringConfig(
        agent_name="support-prod",
        agent_endpoint="http://your-agent/chat",
        authorized_tools=["search_kb", "create_ticket"],
        max_drift_score=25,
        max_autonomous_hits=2,
        probe_interval_hours=24,
        alert_webhook="https://hooks.slack.com/...",
    )

    harness = MonitoringHarness(config, adapter=HttpJsonAdapter())
    harness.start()


if __name__ == "__main__":
    main()
