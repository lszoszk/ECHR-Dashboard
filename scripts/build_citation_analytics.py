#!/usr/bin/env python3
"""Precompute citation network analytics for the dashboard.

Builds a directed citation graph from pcr_citations/pcr_cited_by fields,
computes network metrics (PageRank, betweenness centrality), and generates
data for cross-article citation heatmaps, citation age distributions,
cross-state influence analysis, and landmark case rankings.

Output is merged into stats.json under the "citation_network" key.

References:
  - Fowler et al. (2007) "Network Analysis and the Law" (PageRank, HITS)
  - Lupu & Voeten (2012) "Precedent in International Courts" (ECHR citations)
  - Leitao et al. (2019) "Quantifying Long-Term Impact" (citation age/decay)
  - Olsen & Esmark (2019) "Needles in a Haystack" (cross-article citations)
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import networkx as nx


def parse_date(value: str):
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def is_press_release(case) -> bool:
    return "press release" in str(case.get("document_type") or "").lower()


def build_analytics(cases: list[dict]) -> dict:
    """Build all citation network analytics from the case list."""
    print("  Building case index...")

    # Index cases by case_no (application number)
    case_by_appno: dict[str, dict] = {}
    for case in cases:
        if is_press_release(case):
            continue
        case_no = str(case.get("case_no") or "").strip()
        if not case_no:
            continue
        # Use first appno if multiple
        primary_appno = case_no.split(";")[0].strip()
        if primary_appno and primary_appno not in case_by_appno:
            case_by_appno[primary_appno] = case

    print(f"  Indexed {len(case_by_appno):,} cases by appno")

    # Build directed graph
    print("  Building citation graph...")
    G = nx.DiGraph()

    for appno, case in case_by_appno.items():
        date = parse_date(str(case.get("judgment_date", "")).strip())
        violations = case.get("violation") or []
        if isinstance(violations, str):
            violations = [v.strip() for v in violations.split(";") if v.strip()]
        state = str(case.get("respondent_state") or "").strip()
        title = str(case.get("title") or "").strip()

        G.add_node(appno, date=date, violations=violations, state=state, title=title)

        # Forward citations: this case cites others
        for cited_appno in (case.get("pcr_citations") or []):
            cited_appno = str(cited_appno).strip()
            if cited_appno and cited_appno in case_by_appno:
                G.add_edge(appno, cited_appno)

    print(f"  Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

    # ── 1. Landmark cases (most-cited = highest in-degree) ────────────
    print("  Computing in-degree rankings...")
    in_degrees = dict(G.in_degree())
    out_degrees = dict(G.out_degree())

    top_cited = sorted(in_degrees.items(), key=lambda x: x[1], reverse=True)[:50]
    landmark_cases = []
    for appno, in_deg in top_cited:
        node = G.nodes[appno]
        title = node.get("title", "")
        date = node.get("date")
        year = date.year if date else None
        state = node.get("state", "")
        violations = node.get("violations", [])
        primary_article = violations[0] if violations else ""
        landmark_cases.append({
            "appno": appno,
            "title": title[:80],
            "year": year,
            "state": state,
            "article": primary_article,
            "cited_by": in_deg,
            "cites": out_degrees.get(appno, 0),
        })

    # ── 2. Citation distribution ──────────────────────────────────────
    print("  Computing citation distribution...")
    in_deg_values = [v for v in in_degrees.values() if v > 0]
    out_deg_values = [v for v in out_degrees.values() if v > 0]

    # Log-scale histogram bins for in-degree
    if in_deg_values:
        max_in = max(in_deg_values)
        bins = [0, 1, 2, 3, 5, 10, 20, 50, 100, 200, 500, 1000, max_in + 1]
        in_deg_histogram = []
        for i in range(len(bins) - 1):
            lo, hi = bins[i], bins[i + 1]
            count = sum(1 for v in in_deg_values if lo <= v < hi)
            if count > 0:
                label = f"{lo}" if hi == lo + 1 else f"{lo}-{hi - 1}"
                in_deg_histogram.append([label, count])
    else:
        in_deg_histogram = []

    # Gini coefficient
    def gini(values):
        if not values:
            return 0.0
        sorted_v = sorted(values)
        n = len(sorted_v)
        total = sum(sorted_v)
        if total == 0:
            return 0.0
        cumsum = 0
        gini_sum = 0
        for i, v in enumerate(sorted_v):
            cumsum += v
            gini_sum += (2 * (i + 1) - n - 1) * v
        return gini_sum / (n * total)

    in_deg_all = list(in_degrees.values())
    gini_coeff = round(gini(in_deg_all), 4)

    # Concentration: what % of cases account for 50%/80% of citations
    sorted_in = sorted(in_deg_all, reverse=True)
    total_citations = sum(sorted_in)
    cumsum = 0
    pct_for_50 = pct_for_80 = 0
    for i, v in enumerate(sorted_in):
        cumsum += v
        if pct_for_50 == 0 and cumsum >= total_citations * 0.5:
            pct_for_50 = round((i + 1) / len(sorted_in) * 100, 2)
        if pct_for_80 == 0 and cumsum >= total_citations * 0.8:
            pct_for_80 = round((i + 1) / len(sorted_in) * 100, 2)
            break

    # ── 3. Citation age analysis ──────────────────────────────────────
    print("  Computing citation age distribution...")
    age_gaps = []
    for u, v in G.edges():
        u_date = G.nodes[u].get("date")
        v_date = G.nodes[v].get("date")
        if u_date and v_date:
            gap_years = (u_date - v_date).days / 365.25
            if gap_years >= 0:
                age_gaps.append(gap_years)

    age_histogram = []
    if age_gaps:
        age_bins = [0, 1, 2, 3, 5, 8, 10, 15, 20, 30, 50, 100]
        for i in range(len(age_bins) - 1):
            lo, hi = age_bins[i], age_bins[i + 1]
            count = sum(1 for a in age_gaps if lo <= a < hi)
            if count > 0:
                label = f"{lo}-{hi - 1}yr" if hi - lo > 1 else f"{lo}yr"
                age_histogram.append([label, count])

    # Avg forward + backward citations by decade
    decade_stats = defaultdict(lambda: {
        "cases": 0, "total_forward": 0, "total_backward": 0,
        "total_cited_by": 0,
    })
    for appno in G.nodes():
        date = G.nodes[appno].get("date")
        if not date:
            continue
        decade = f"{date.year // 10 * 10}s"
        decade_stats[decade]["cases"] += 1
        decade_stats[decade]["total_forward"] += out_degrees.get(appno, 0)
        decade_stats[decade]["total_backward"] += in_degrees.get(appno, 0)

    citations_by_decade = []
    for decade in sorted(decade_stats.keys()):
        s = decade_stats[decade]
        n = s["cases"]
        citations_by_decade.append([
            decade,
            n,
            round(s["total_forward"] / n, 1) if n else 0,
            round(s["total_backward"] / n, 1) if n else 0,
            s["total_forward"],
            s["total_backward"],
        ])

    # ── 4. Cross-article citation heatmap ─────────────────────────────
    print("  Computing cross-article citation matrix...")
    article_citation_matrix = Counter()  # (citing_article, cited_article) -> count

    for u, v in G.edges():
        u_violations = G.nodes[u].get("violations", [])
        v_violations = G.nodes[v].get("violations", [])
        for ua in (u_violations or ["(none)"]):
            for va in (v_violations or ["(none)"]):
                article_citation_matrix[(ua, va)] += 1

    # Get top articles for the matrix
    article_freq = Counter()
    for appno in G.nodes():
        for art in (G.nodes[appno].get("violations") or []):
            article_freq[art] += 1
    top_articles = [a for a, _ in article_freq.most_common(12)]

    heatmap_data = {
        "articles": top_articles,
        "matrix": [
            [article_citation_matrix.get((a1, a2), 0) for a2 in top_articles]
            for a1 in top_articles
        ],
    }

    # ── 5. Cross-state influence ──────────────────────────────────────
    print("  Computing cross-state influence...")
    state_cite_state = Counter()  # (citing_state, cited_state) -> count
    state_total_outgoing = Counter()  # citing_state -> total outgoing citations

    for u, v in G.edges():
        u_state = G.nodes[u].get("state", "")
        v_state = G.nodes[v].get("state", "")
        if u_state and v_state:
            state_cite_state[(u_state, v_state)] += 1
            state_total_outgoing[u_state] += 1

    # Self-citation rate by country (min 50 edges)
    self_citation_rates = []
    for state, total in state_total_outgoing.most_common():
        if total < 50:
            continue
        self_count = state_cite_state.get((state, state), 0)
        rate = round(self_count / total * 100, 1)
        self_citation_rates.append([state, rate, self_count, total])
    self_citation_rates.sort(key=lambda x: x[1], reverse=True)

    # Most-cited states by other countries (excluding self-citations)
    state_cited_by_others = Counter()
    for (citing, cited), count in state_cite_state.items():
        if citing != cited:
            state_cited_by_others[cited] += count
    cross_state_most_cited = state_cited_by_others.most_common(15)

    # ── 6. PageRank ───────────────────────────────────────────────────
    print("  Computing PageRank (this may take a moment)...")
    try:
        pagerank = nx.pagerank(G, alpha=0.85, max_iter=100)
    except Exception as e:
        print(f"  WARNING: PageRank failed: {e}")
        pagerank = {}

    # Top cases by PageRank
    top_pagerank = sorted(pagerank.items(), key=lambda x: x[1], reverse=True)[:30]
    pagerank_ranking = []
    for appno, pr_score in top_pagerank:
        node = G.nodes[appno]
        title = node.get("title", "")
        date = node.get("date")
        year = date.year if date else None
        state = node.get("state", "")
        violations = node.get("violations", [])
        primary_article = violations[0] if violations else ""
        pagerank_ranking.append({
            "appno": appno,
            "title": title[:80],
            "year": year,
            "state": state,
            "article": primary_article,
            "pagerank": round(pr_score * 1_000_000, 2),  # Scale for readability
            "cited_by": in_degrees.get(appno, 0),
            "rank_by_citations": None,  # filled below
        })

    # Add citation rank for comparison
    citation_rank = {appno: rank + 1 for rank, (appno, _) in enumerate(
        sorted(in_degrees.items(), key=lambda x: x[1], reverse=True)
    )}
    for entry in pagerank_ranking:
        entry["rank_by_citations"] = citation_rank.get(entry["appno"], 0)

    # ── 7. Betweenness centrality (top nodes only for speed) ─────────
    print("  Computing betweenness centrality (approximate)...")
    try:
        # Use approximate betweenness with k=500 samples for speed
        betweenness = nx.betweenness_centrality(G, k=min(500, G.number_of_nodes()))
    except Exception as e:
        print(f"  WARNING: Betweenness failed: {e}")
        betweenness = {}

    top_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:20]
    betweenness_ranking = []
    for appno, bc_score in top_betweenness:
        node = G.nodes[appno]
        betweenness_ranking.append({
            "appno": appno,
            "title": node.get("title", "")[:80],
            "year": node.get("date").year if node.get("date") else None,
            "betweenness": round(bc_score * 1_000_000, 2),
            "cited_by": in_degrees.get(appno, 0),
        })

    # ── Summary stats ─────────────────────────────────────────────────
    summary = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "cases_with_citations": sum(1 for v in out_degrees.values() if v > 0),
        "cases_cited": sum(1 for v in in_degrees.values() if v > 0),
        "avg_forward_citations": round(sum(out_deg_values) / len(out_deg_values), 1) if out_deg_values else 0,
        "avg_backward_citations": round(sum(in_deg_values) / len(in_deg_values), 1) if in_deg_values else 0,
        "median_forward": sorted(out_deg_values)[len(out_deg_values) // 2] if out_deg_values else 0,
        "median_backward": sorted(in_deg_values)[len(in_deg_values) // 2] if in_deg_values else 0,
        "max_forward": max(out_deg_values) if out_deg_values else 0,
        "max_backward": max(in_deg_values) if in_deg_values else 0,
        "gini_coefficient": gini_coeff,
        "pct_cases_for_50pct_citations": pct_for_50,
        "pct_cases_for_80pct_citations": pct_for_80,
        "mean_citation_age_years": round(sum(age_gaps) / len(age_gaps), 1) if age_gaps else 0,
        "median_citation_age_years": round(sorted(age_gaps)[len(age_gaps) // 2], 1) if age_gaps else 0,
        "self_citation_rate_overall": round(
            sum(state_cite_state.get((s, s), 0) for s in state_total_outgoing)
            / sum(state_total_outgoing.values()) * 100, 1
        ) if state_total_outgoing else 0,
    }

    return {
        "summary": summary,
        "landmark_cases": landmark_cases[:30],
        "in_degree_histogram": in_deg_histogram,
        "citation_age_histogram": age_histogram,
        "citations_by_decade": citations_by_decade,
        "cross_article_heatmap": heatmap_data,
        "self_citation_rates": self_citation_rates[:20],
        "cross_state_most_cited": cross_state_most_cited,
        "pagerank_ranking": pagerank_ranking[:25],
        "betweenness_ranking": betweenness_ranking[:15],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="docs/data/echr_cases_enriched_final.jsonl")
    parser.add_argument("--stats", default="docs/data/stats.json",
                        help="Existing stats.json to merge citation_network into")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    def resolve(p):
        pp = Path(p).expanduser()
        return pp if pp.is_absolute() else (repo_root / pp).resolve()

    input_path = resolve(args.input)
    stats_path = resolve(args.stats)

    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading cases from {input_path} ...")
    cases = load_cases(input_path)
    print(f"  Loaded {len(cases):,} records")

    analytics = build_analytics(cases)

    # Merge into existing stats.json
    if stats_path.exists():
        print(f"\nMerging into {stats_path} ...")
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    else:
        stats = {}

    stats["citation_network"] = analytics
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Written citation_network to {stats_path}")

    # Print summary
    s = analytics["summary"]
    print()
    print("=" * 65)
    print(f"  Citation Network Summary")
    print(f"  Nodes: {s['total_nodes']:,}   Edges: {s['total_edges']:,}")
    print(f"  Avg forward: {s['avg_forward_citations']}   Avg backward: {s['avg_backward_citations']}")
    print(f"  Gini coefficient: {s['gini_coefficient']}")
    print(f"  {s['pct_cases_for_50pct_citations']}% of cases → 50% of citations")
    print(f"  {s['pct_cases_for_80pct_citations']}% of cases → 80% of citations")
    print(f"  Mean citation age: {s['mean_citation_age_years']} years")
    print(f"  Self-citation rate: {s['self_citation_rate_overall']}%")
    print(f"  Top landmark: {analytics['landmark_cases'][0]['title']}"
          f" ({analytics['landmark_cases'][0]['cited_by']} citations)")
    print("=" * 65)


if __name__ == "__main__":
    main()
