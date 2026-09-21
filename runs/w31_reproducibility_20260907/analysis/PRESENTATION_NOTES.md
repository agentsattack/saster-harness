# Presentation use

Recommended headline:

> A fixed seed reproduced the Qwen action path, but not the Ministral path.

Defensible spoken result:

> In a targeted 64-trial stress test, all 64 trials completed. The two exact repeats agreed on breach outcome in 30 of 32 matched pairs, but reproduced the exact action sequence in only 21 of 32. Qwen reproduced its action sequence in all 16 pairs; Ministral did so in 5 of 16. Two identical-seed Ministral/L1 pairs split on whether a breach occurred, both under concurrent serving. That makes the fixed application seed an experiment label, not proof of deterministic replay.

Authorization result:

> Across the selected Ministral strata, L1 alone produced unauthorized actions in 5 of 8 attack trials and 5 of 8 ordinary-support controls. Adding explicit authorization produced 0 of 8 in each, while all eight authorization controls still completed the permitted lookup. These are selected stress-test seeds, not a population risk estimate.

Do not claim that concurrency caused the instability. Sequential breach agreement was 16/16 pairs and concurrent agreement was 14/16, but the paired exact test is `p=0.5` because only two strata were discordant. The result establishes observed fixed-seed non-reproducibility, not a concurrency effect.

Do not pool W31 into the 810-record core corpus or W30 denominators. Label it as a preregistered, targeted reproducibility arm with two selected seeds per condition and two repeats per schedule.
