#!/bin/bash
# W38 batch: arm name, attacker mode, attacker model, seeds
cd /home/lbsuto/saster-harness
arm=$1; mode=$2; amodel=$3; shift 3
for seed in "$@"; do
  W38_ATTACKER=$mode W38_ATTACKER_MODEL=$amodel W38_MAX_TURNS=14 W38_SEED=$seed W38_RUN_ID=w38-${arm}-seed${seed} \
    .venv/bin/python scripts/run_beat1_clean_w38.py >> runs/w38_beat1_clean/batch_${arm}.log 2>&1
done
echo "ARM $arm DONE" >> runs/w38_beat1_clean/batch_${arm}.log
