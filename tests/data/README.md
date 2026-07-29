# Vendored taxonomy — `tests/data/SASTER.md`

`SASTER.md` is a **pinned copy** of the SASTER taxonomy, vendored here so
the taxonomy-sync CI guard (`tests/test_taxonomy_sync.py`) runs
hermetically without a network fetch or a second checked-out repo.

- **Upstream:** <https://github.com/agentsattack/saster> — `SASTER.md`
- **Pinned upstream commit:** `d98a0c7` (SASTER v1.1 + Phase 2.3 prior-art fields, 32 patterns,
  SASTER-32 reserved)
- **Integrity:** `SASTER.md.sha256` holds the SHA-256 of the vendored
  file. `test_taxonomy_sync.py` verifies the file against it on every
  run, so an accidental edit to the vendored copy fails loudly rather
  than silently changing what the detectors are validated against.

## Refresh procedure

When the upstream taxonomy changes and the harness should track it:

1. Copy the new file in:

   ```bash
   cp /path/to/saster/SASTER.md tests/data/SASTER.md
   ```

2. Re-pin the checksum:

   ```bash
   sha256sum tests/data/SASTER.md | awk '{print $1}' > tests/data/SASTER.md.sha256
   ```

3. Update the "Pinned upstream commit" line above to the new upstream
   commit hash.

4. Run the guard and reconcile any drift it reports (a renamed pattern,
   a changed definition, a new/removed number):

   ```bash
   pytest tests/test_taxonomy_sync.py -q
   ```

   The guard failing after a refresh is the intended signal: it means a
   detector's declared id/name/tier or its quoted canonical block no
   longer matches upstream. Fix the detector (or the README count), then
   commit the refreshed copy, checksum, and detector changes together.
