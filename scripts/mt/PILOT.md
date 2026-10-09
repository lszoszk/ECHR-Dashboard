# Translation pilot (run by a Claude Code session, no API key)

The pilot translates a small set of job files so that quality and cost can be measured before the
bulk run through the API. The job files are prepared locally with `prepare.py` and committed under
`mt_pilot/jobs/` on the `mt-pilot` branch (they are public HUDOC texts, © ECHR-CEDH).

- `mt_pilot/jobs/<id>/chunk_NNN.json`: one chunk of one judgment (see `scripts/mt/TRANSLATOR.md`).
- Judgments with `reference.json` are held-out bilingual judgments. Their official English is there
  for scoring. **Do not open reference.json before translating.**

## Task for the session

1. Read `scripts/mt/TRANSLATOR.md` once and follow it exactly.
2. For every `chunk_NNN.json` without a `chunk_NNN.en.json` beside it, translate the rows and write
   `chunk_NNN.en.json` as a JSON object `{"<row id>": "<English>"}` with every row id of the chunk.
   Work through the chunks of a judgment in order, so that the terms you choose stay consistent within
   the judgment. Use the `glossary` and `examples` of each job.
3. Run `python3 scripts/mt/assemble.py --jobs mt_pilot/jobs --report mt_pilot/report.json`. For
   every row flagged `missing`, `citations` or `french`, fix the translation and run the script again.
4. Commit `chunk_*.en.json`, `translation.json` and `report.json` to the `mt-pilot` branch and push.
   Note in the commit message how many chunks were translated and the final report figures.
