# Local database backups

Local-only snapshots of the production database (`echr_search.db` on the VM,
`~/echr/data/` → mounted at `/data/` in the `echr-api` container). The `.db`
files themselves are **git-ignored** (global `*.db` rule) and live only on this
machine — they are deliberately NOT stored on the VM to avoid filling its disk.

| file | taken | size | sha256 | reason |
|---|---|---|---|---|
| `echr_search.pre-p60.2026-07-02.db` | 2026-07-02, before P60 apply | 4,157,751,296 B | *(see CHECKSUMS)* | Full pre-image of the DB before the P60 boilerplate relabelling (~70k rows `row_role` changes; see below) |

Checksums are recorded in `CHECKSUMS.sha256` next to the files
(`shasum -a 256 -c CHECKSUMS.sha256` to verify).

## What P60 changed (why this backup exists)

`scripts/p60_heal_boilerplate.py` relabelled 89,519 rows (three batches: 70,139 + 14,984 + 4,396) that were stored as
`row_role='paragraph'` but are not citable body text (all of them **without** a
HUDOC ¶ number, length ≤ 90 chars):

- → `metadata` (~82k): procedural formulae, court-composition/appearance lines,
  "Having deliberated…", elision rows;
- → `signature` (~1.4k): "Signed: …", bare President/Registrar lines;
- → `heading_h4` (~0.8k): sub-headings ("Pecuniary damage", "The Court's assessment");
- → `quote` (~0.8k): quoted Convention/statute lines.

Method: curated template rules + LLM-judge (Sonnet) over distinct texts;
numbered paragraphs were never touched. Judge artifacts (batches, verdicts,
`verdict_map.json`) live in `/tmp/echr_seg_heal/` (ephemeral, not committed).

## How to restore

**Preferred — surgical (no file swap, instant):** every change was recorded in
the `role_backup_p60` table inside the live DB itself:

```bash
docker exec echr-api python3 /tmp/p60_heal_boilerplate.py --restore
# (script also in repo: scripts/p60_heal_boilerplate.py)
```

**Full-file restore (nuclear option):**

```bash
# 1. stop the API
ssh amuvmuser@150.254.115.204 'cd ~/echr && docker compose stop echr-api'
# 2. push the snapshot back (from this machine)
scp backups/echr_search.pre-p60.2026-07-02.db \
    amuvmuser@150.254.115.204:~/echr/data/echr_search.db
# 3. remove stale WAL/SHM and restart
ssh amuvmuser@150.254.115.204 'rm -f ~/echr/data/echr_search.db-wal ~/echr/data/echr_search.db-shm && cd ~/echr && docker compose up -d echr-api'
```

Note: the snapshot was taken after `PRAGMA wal_checkpoint(TRUNCATE)`, so the
single `.db` file is complete and self-consistent (no `-wal` needed).
