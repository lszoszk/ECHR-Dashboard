# HUDOC Researcher

[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21319703.svg)](https://doi.org/10.5281/zenodo.21319703)

The judgments of the European Court of Human Rights, paragraph by paragraph: full-text and semantic search,
citation checking, Cites / Cited by and statistics.

**Live site:** https://lszoszk.github.io/ECHR-Dashboard/

This repository holds the website only (`docs/`, published by `.github/workflows/deploy-pages.yml`). The data
pipeline, the search API and the deployment tools are kept in a separate, non-public repository; how the data
was built and checked is set out in the [Methodology](https://lszoszk.github.io/ECHR-Dashboard/methodology.html).
Questions, internal documentation and access for research: l.szoszkiewicz@amu.edu.pl.

Developed by **Łukasz Szoszkiewicz** and **Sebastian Marcisz**.

## Data

The paragraph-level corpus (judgments, paragraphs with numbers and section labels, citation links) is published
on Hugging Face: [lszoszk/ecthr-judgments](https://huggingface.co/datasets/lszoszk/ecthr-judgments).

## Licensing

- Website code: PolyForm Noncommercial 1.0.0; research, education, non-profit and personal use are permitted.
  See [`LICENSE`](LICENSE).
- Curated dataset (segmentation, paragraph numbers, section labels, metadata, citation links): CC BY-NC-SA 4.0.
  See [`LICENSE-DATA`](LICENSE-DATA).
- The judgments are © Council of Europe / European Court of Human Rights, reused under the Court's terms for
  HUDOC content and not re-licensed by this project. See [`NOTICE`](NOTICE). This project is **not affiliated
  with or endorsed by** the Court, and the site is a **research aid, not legal advice**.

## Citation

> Szoszkiewicz, Ł., & Marcisz, S. (2026). *HUDOC Researcher — ECtHR Case-Law Search & RAG* [Computer software].
> Zenodo. https://doi.org/10.5281/zenodo.21319703

When citing a judgment paragraph, cite the authoritative HUDOC record and paragraph as well.
