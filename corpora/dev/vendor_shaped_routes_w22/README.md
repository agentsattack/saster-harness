# vendor_shaped_routes_w22 (dev — diagnostic, not records)

Written 2026-09-05 by `scripts/vendor_shaped_routes_w22.py` with
`W22_ROUTE_SET=reference`: the vendor-shaped configuration (allow-list
scope lock under real OPA + per-action judge through the affinity router,
temperature 0, no history, no reasoning shown) run over the fixture's
ten-step reference divergence route (`carl_ops_state.fixture
.divergence_path()`, the grant route) and the four-call in-network
firewall route, once per judge:

- `reference_route_ministral_judge.json` — judge mistralai/Ministral-8B-Instruct-2410 (the assignment for a Qwen victim)
- `reference_route_qwen_judge.json` — judge Qwen/Qwen3-8B (for comparison; the pre-assignment judge)

No trajectory record is produced and nothing here is a corpus. P17 is not
edited on the strength of this; it is context for reading the pilot's
result. The earlier four-call report with the Qwen judge is
`runs/w22_vendor_shaped_routes.json`.
