#!/bin/bash
# W38 batch 2: arm, attacker mode, attacker model, victim, input-block semantics, max turns, seeds
cd /home/lbsuto/saster-harness
arm=$1; mode=$2; amodel=$3; victim=$4; ib=$5; maxt=$6; shift 6
for seed in "$@"; do
  W38_ATTACKER=$mode W38_ATTACKER_MODEL=$amodel W38_VICTIM=$victim W38_INPUT_BLOCK=$ib W38_MAX_TURNS=$maxt W38_SEED=$seed W38_RUN_ID=w38-${arm}-seed${seed} \
    .venv/bin/python scripts/run_beat1_clean_w38.py >> runs/w38_beat1_clean/batch_${arm}.log 2>&1
done
echo "ARM $arm DONE" >> runs/w38_beat1_clean/batch_${arm}.log
