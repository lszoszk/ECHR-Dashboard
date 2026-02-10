# ECHR Dashboard

This repository includes a full ECHR dashboard project with:

- Flask app (interactive paragraph-level case search): `echr_dashboard/`
- Static GitHub Pages analytics dashboard: `docs/`
- Sample JSONL dataset for testing: `data/echr_decisions_sample.jsonl`

## Quick start (local)

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Launch the app:

```bash
bash echr_dashboard/run.sh
```

Open: `http://127.0.0.1:5001`

## Dataset selection

The app resolves dataset files in this order:

1. `ECHR_DATA_FILE` (if set)
2. `data/echr_decisions_sample.jsonl`
3. `echr_cases_optionB.jsonl`
4. `echr_cases_20260207_121847.jsonl`

Example with a custom dataset:

```bash
ECHR_DATA_FILE=/absolute/path/to/your_cases.jsonl python3 echr_dashboard/app.py
```

## Build static GitHub Pages dashboard

```bash
python3 scripts/build_pages_dashboard.py
```

This regenerates `docs/data/stats.json` from the selected JSONL dataset.

## GitHub Pages deployment

Workflow file: `.github/workflows/deploy-pages.yml`

On each push to `main`/`master`, GitHub Actions:

1. Builds `docs/data/stats.json`
2. Uploads `docs/`
3. Deploys to GitHub Pages

Enable Pages in repository settings:

- Settings → Pages → Source: **GitHub Actions**
