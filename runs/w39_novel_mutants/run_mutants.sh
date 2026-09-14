#!/usr/bin/env bash
# Each blind patch on its own branch in a worktree; both suite tiers; kill = any failed or xpassed test.
set -u
REPO=/home/lbsuto/saster-harness; PY=$REPO/.venv/bin/python; OUT=$REPO/runs/w39_novel_mutants; BASE=$(git -C $REPO rev-parse HEAD)
echo "base $BASE"
for N in 1 2 3 4 5 6 7 8; do
  WT=/home/lbsuto/mutant_wt/novel-$N
  git -C $REPO worktree add -q -b mutant/novel-$N $WT $BASE || { echo "[$N] worktree failed"; continue; }
  ( cd $WT && patch -p1 --forward < $OUT/mutant_$N.patch > $OUT/novel-$N.patch.log 2>&1 && git add -A && git -c user.name='Larry Suto' -c user.email='larry.suto@gmail.com' commit -q -m "novel mutant $N (blind-authored patch, runs/w39_novel_mutants/mutant_$N.patch)" ) || { echo "[$N] patch failed"; cat $OUT/novel-$N.patch.log; continue; }
  ( cd $WT && PYTHONPATH=$WT timeout 1200 $PY -m pytest -q --no-header -p no:cacheprovider -rfX > $OUT/novel-$N.default.log 2>&1; echo "default exit $?" >> $OUT/novel-$N.default.log )
  ( cd $WT && PYTHONPATH=$WT W9_HEADS_10_HOST='[fd00:200::7]' timeout 600 $PY -m pytest -q --no-header -p no:cacheprovider -m cluster -rfX > $OUT/novel-$N.cluster.log 2>&1; echo "cluster exit $?" >> $OUT/novel-$N.cluster.log )
  echo "[$N] $(tail -2 $OUT/novel-$N.default.log | head -1) | $(tail -2 $OUT/novel-$N.cluster.log | head -1)"
done
echo "all done $(date -u +%H:%M:%SZ)"
