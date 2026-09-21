"""HalCTF agent scaffold.

A data-generation instrument for the AI Village agentic CTF. The deliverable is
trajectory telemetry: labeled (declared_intent, action) pairs emitted at volume.
Solving challenges is a means to that end, not the goal.

Design invariants (do not weaken without deliberate review):
  * The scope guard is enforced in code between the model's decision and the
    tool handler. It cannot be bypassed by prompting.
  * Telemetry is append-only JSONL, flushed+fsynced per write.
  * The loop shape is explicit and framework-free so it is fully observable.
  * Stdlib only. Nothing to `pip install` at build or run time.
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "halctf.trajectory.v1"
