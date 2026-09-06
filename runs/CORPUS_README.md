# The GrrCON corpus — index (generated)

Citable total after AMENDMENT 19: **162 cells, 810 records** — the sweep (96 cells: w24b with w24c replacing its 34 lost cells), the §P arm (30) and the §R arm (36). Every record passed `carl_ops_trajectory.citable` (`runs/w25_stage5/citable_reload.json`).

| run root | cells with records | records | why it exists |
|---|---|---|---|
| w24_sweep_ministral | 2 | 10 | first Stage 4 launch; halted by the operator after two cells per victim when D12 showed in the readback; kept as evidence, not analysed |
| w24_sweep_qwen3 | 3 | 15 | first Stage 4 launch; halted by the operator after two cells per victim when D12 showed in the readback; kept as evidence, not analysed |
| w24b_sweep_ministral | 48 | 217 | the full 48-cell matrix per victim; 34 cells short on D13/D14, replaced by w24c in the analysed corpus |
| w24b_sweep_qwen3 | 44 | 140 | the full 48-cell matrix per victim; 34 cells short on D13/D14, replaced by w24c in the analysed corpus |
| w24c_sweep_ministral | 14 | 70 | re-run of the 34 cells w24b lost, new run id, same paired seeds |
| w24c_sweep_qwen3 | 20 | 100 | re-run of the 34 cells w24b lost, new run id, same paired seeds |
| w25p_sweep_qwen3 | 30 | 150 | addendum §P arm: Qwen under tool_choice required on the 30 cells where Ministral breached |
| w26r_sweep_ministral | 18 | 90 | addendum §R arm: R6 on l2, all and vendor-shaped, both families |
| w26r_sweep_qwen3 | 18 | 90 | addendum §R arm: R6 on l2, all and vendor-shaped, both families |

The sweep's three run ids: `w24` (halted first launch, evidence only), `w24b` (the matrix), `w24c` (the 34-cell re-run). Each is a new run id because a re-run is a new result beside the old, never an overwrite.
