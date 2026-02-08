# ECHR Dashboard

This folder now contains two deployable outputs:

- Flask app (interactive search + case view): `echr_dashboard/`
- Static GitHub Pages analytics dashboard: `docs/`

## Local Flask app

```bash
cd echr_dashboard
python3 app.py
```

Open: `http://127.0.0.1:5001`

## Build static GitHub Pages dashboard

```bash
python3 scripts/build_pages_dashboard.py
```

This regenerates:

- `docs/data/stats.json`

## GitHub Pages deployment

Workflow file:

- `.github/workflows/deploy-pages.yml`

On each push to `main`/`master`, it:

1. builds `docs/data/stats.json`
2. uploads `docs/`
3. deploys to GitHub Pages

You need to enable Pages in the repository settings:

- Settings → Pages → Source: **GitHub Actions**

