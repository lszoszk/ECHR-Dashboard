"""Conservative identity matching and bilingual edge-deduplication tests."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_judgment_citations import JudgmentIndex, applications, build_graph, reference_dates, write_audit
from hudoc_fixtures import document, fixture


def judgment(cid="001-1", **extra):
    row = document(cid, ecli="ECLI:" + cid)
    row.update(docname="CASE OF SAMPLE v. POLAND", appno="12345/58", scl="")
    row.update(extra)
    return row


class CitationTests(unittest.TestCase):
    def test_application_years_and_numeric_dates(self):
        self.assertEqual(applications("nos. 00123/1958 and 999/58, 01/02/1959"), {"123/58", "999/58"})
        self.assertEqual(reference_dates("1er fevrier 1959; 1 February 1959"), {"1959-02-01"})
        self.assertEqual(reference_dates("01/02/1959 and 1959-02-01"), {"1959-02-01"})
        self.assertEqual(reference_dates("1.2.1959"), {"1959-02-01"})

    def test_bilingual_versions_and_reference_repetitions_count_once(self):
        target = judgment()
        target_fr = dict(target, itemid="001-2", languageisocode="FRE", doctype="HFJUD", docname="AFFAIRE SAMPLE c. POLOGNE")
        source = judgment("001-3", appno="456/58", kpdate="1959-03-01T00:00:00", scl="Sample v. Poland, no. 12345/58;Sample v. Poland, no. 12345/58, \u00a7 12")
        source_fr = dict(source, itemid="001-4", languageisocode="FRE", doctype="HFJUD", scl="Sample c. Pologne, n\u00b0 12345/58, 1 janvier 1959")
        result, index, observations, edges = build_graph(fixture([target, target_fr, source, source_fr], ("ENG", "FRE")))
        self.assertEqual(len(index.nodes), 2)
        self.assertEqual(len(edges), 1)
        self.assertEqual(len(observations), 3)
        self.assertEqual(result["ranking"][0]["cited_by_count"], 1)
        self.assertEqual(result["coverage"]["judgments_with_metadata"], 1)
        self.assertEqual(result["coverage"]["by_status"], {"resolved": 3})

    def test_same_application_different_judgments_not_merged(self):
        rows = [judgment(), judgment("001-2", kpdate="1959-02-01T00:00:00", docname="CASE OF SAMPLE v. POLAND (ARTICLE 41)"),
                judgment("001-3", appno="999/58", kpdate="1959-12-01T00:00:00")]
        index = JudgmentIndex(rows)
        source = "ECLI:001-3"
        self.assertEqual(index.resolve("Sample v. Poland, no. 12345/58", source)["status"], "ambiguous")
        self.assertEqual(index.resolve("Sample v. Poland, no. 12345/58, 1 February 1959", source)["target_id"], "ECLI:001-2")
        self.assertEqual(index.resolve("Sample v. Poland (just satisfaction), no. 12345/58", source)["target_id"], "ECLI:001-2")

    def test_direct_language_id_and_conflicting_identifiers(self):
        target = judgment()
        fre = dict(target, itemid="001-2", languageisocode="FRE", doctype="HFJUD")
        source = judgment("001-3", appno="999/58", kpdate="1959-12-01T00:00:00")
        index = JudgmentIndex([target, fre, source])
        self.assertEqual(index.resolve("https://hudoc.echr.coe.int/fre?i=001-2", "ECLI:001-3")["target_id"], "ECLI:001-1")
        self.assertEqual(index.resolve("001-1 and 001-3", "ECLI:001-3")["status"], "unresolved")

    def test_unknown_identifier_does_not_fall_back_to_name(self):
        index = JudgmentIndex([judgment(), judgment("001-3", appno="999/58")])
        result = index.resolve("Sample v. Poland, no. 12345/58, 001-unknown ECLI:CE:ECHR:1959:0101JUD009999958", "ECLI:001-3")
        self.assertEqual(result["status"], "unresolved")

    def test_decisions_unknown_names_and_self_references_are_not_edges(self):
        source = judgment("001-3", appno="999/58")
        index = JudgmentIndex([judgment(), source])
        self.assertEqual(index.resolve("Sample v. Poland (dec.), no. 12345/58", "ECLI:001-3")["status"], "excluded_document_type")
        self.assertEqual(index.resolve("Unknown v. Poland, no. 12345/58", "ECLI:001-3")["status"], "unresolved")
        self.assertEqual(index.resolve("001-3", "ECLI:001-3")["status"], "self_reference")
        self.assertEqual(index.resolve("Sample v. Poland", "ECLI:001-3")["status"], "unresolved")

    def test_future_and_conflicting_reference_dates_are_not_edges(self):
        index = JudgmentIndex([judgment(kpdate="1959-02-01T00:00:00"), judgment("001-3", appno="999/58")])
        self.assertEqual(index.resolve("001-1", "ECLI:001-3")["status"], "chronology_conflict")
        self.assertEqual(index.resolve("Sample v. Poland, no. 12345/58, 1 January 1959 and 1 February 1959", "ECLI:001-3")["status"], "ambiguous")

    def test_joined_applications_use_all_numbers(self):
        index = JudgmentIndex([judgment(appno="12345/58;23456/58"), judgment("001-2", appno="12345/58"),
                               judgment("001-3", appno="999/58")])
        result = index.resolve("Sample v. Poland, nos. 12345/58 and 23456/58", "ECLI:001-3")
        self.assertEqual(result["target_id"], "ECLI:001-1")

    def test_missing_ecli_and_french_orphan_are_not_silently_merged(self):
        eng = judgment(ecli="")
        fre = dict(eng, itemid="001-2", ecli="ECLI:different", languageisocode="FRE", doctype="HFJUD")
        index = JudgmentIndex([eng, fre])
        self.assertEqual(len(index.nodes), 1)
        self.assertNotIn("001-2", index.aliases)
        self.assertEqual({r["reason"] for r in index.issues}, {"missing_ecli_unpaired", "unpaired_french_identity"})

    def test_conflicting_bilingual_dates_fail_closed(self):
        eng = judgment()
        fre = dict(eng, itemid="001-2", languageisocode="FRE", doctype="HFJUD", kpdate="1959-02-01T00:00:00")
        index = JudgmentIndex([eng, fre])
        self.assertFalse(index.nodes)
        self.assertEqual(index.issues[0]["reason"], "conflicting_identity")

    def test_ambiguous_same_language_ecli_fails_closed(self):
        index = JudgmentIndex([judgment(), judgment("001-2", ecli="ECLI:001-1")])
        self.assertFalse(index.nodes)

    def test_title_and_date_match_without_application_number(self):
        index = JudgmentIndex([judgment(), judgment("001-3", appno="999/58", docname="CASE OF OTHER v. POLAND")])
        result = index.resolve("Sample v. Poland, 1 January 1959, Series A", "ECLI:001-3")
        self.assertEqual(result["method"], "title_date")
        self.assertEqual(result["status"], "resolved")

    def test_french_legacy_reference_and_exact_date_with_unknown_stage(self):
        target = judgment(docname="CASE OF SAMPLE v. POLAND")
        fre = dict(target, itemid="001-2", languageisocode="FRE", doctype="HFJUD", docname="AFFAIRE SAMPLE c. POLOGNE")
        index = JudgmentIndex([target, fre, judgment("001-3", appno="999/58")])
        for raw in ["Arr\u00eat Sample c. Pologne du 1er janvier 1959, s\u00e9rie A", "Sample c. Pologne, arr\u00eat du 1 janvier 1959, Recueil", "Sample v. Poland (just satisfaction), no. 12345/58, 1 January 1959"]:
            self.assertEqual(index.resolve(raw, "ECLI:001-3")["target_id"], "ECLI:001-1")

    def test_disagreeing_application_aliases_do_not_inflate_secondary_matches(self):
        target = judgment(appno="12345/58;23456/58")
        fre = dict(target, itemid="001-2", languageisocode="FRE", doctype="HFJUD", appno="12345/58")
        index = JudgmentIndex([target, fre, judgment("001-3", appno="999/58")])
        self.assertNotIn("23456/58", index.appnos)
        self.assertEqual(index.resolve("001-2", "ECLI:001-3")["status"], "resolved")

    def test_graph_is_deterministic_and_audit_is_queryable(self):
        rows = [judgment(), judgment("001-3", appno="999/58", scl="001-1")]
        data = fixture(rows, ("ENG", "FRE"))
        original = copy.deepcopy(data)
        result, index, observations, edges = build_graph(data)
        self.assertEqual(data, original)
        second = build_graph(data)[0]
        self.assertEqual(result["edges_sha256"], second["edges_sha256"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite"
            write_audit(path, index, observations, edges)
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM edges").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT status FROM observations").fetchone()[0], "resolved")

    def test_title_conflicting_with_application_date_is_not_resolved(self):
        index = JudgmentIndex([judgment(), judgment("001-3", appno="999/58", docname="CASE OF OTHER v. POLAND")])
        result = index.resolve("Other v. Poland, no. 12345/58, 1 January 1959", "ECLI:001-3")
        self.assertEqual(result["status"], "identifier_conflict")

    def test_null_metadata_and_empty_graph_are_supported(self):
        result = build_graph(fixture([judgment(scl=None)], ("ENG", "FRE")))[0]
        self.assertEqual(result["coverage"]["reference_observations"], 0)
        self.assertEqual(result["ranking"], [])
        self.assertFalse(result["citing_judgments"])

    def test_direct_ecli_and_case_insensitive_language_group(self):
        ecli = "ECLI:CE:ECHR:1959:0101JUD001234558"
        target = judgment(ecli=ecli)
        fre = dict(target, itemid="001-2", languageisocode="FRE", doctype="HFJUD", ecli=ecli.lower())
        source = judgment("001-3", appno="999/58", docname="CASE OF OTHER v. POLAND")
        index = JudgmentIndex([target, fre, source])
        self.assertEqual(len(index.nodes), 2)
        result = index.resolve(ecli.lower(), "ECLI:001-3")
        self.assertEqual(result["target_id"], ecli)
        self.assertEqual(result["method"], "direct_identifier")

    def test_revision_is_not_confused_with_interpretation(self):
        index = JudgmentIndex([judgment(docname="CASE OF SAMPLE v. POLAND (INTERPRETATION)"), judgment("001-3", appno="999/58")])
        self.assertEqual(index.resolve("Sample v. Poland (revision), no. 12345/58", "ECLI:001-3")["status"], "unresolved")


class ExtractedApplicationTests(unittest.TestCase):
    """Application numbers HUDOC extracted from the text: separate evidence, resolved only when unambiguous."""

    def rows(self):
        target = judgment("001-1", appno="111/58")                                    # 1959-01-01
        stage = judgment("001-2", appno="222/58", kpdate="1959-02-01T00:00:00")       # two judgments, one application
        stage2 = judgment("001-3", appno="222/58", kpdate="1959-03-01T00:00:00")
        later = judgment("001-4", appno="333/58", kpdate="1959-12-01T00:00:00")
        source = judgment("001-5", appno="444/58", kpdate="1959-06-01T00:00:00")
        return [target, stage, stage2, later, source]

    def graph(self, extracted):
        return build_graph(fixture(self.rows(), ("ENG", "FRE")), extracted)

    def test_without_extracted_numbers_the_snapshot_has_no_extra_block(self):
        result, *_ = self.graph(None)
        self.assertNotIn("with_extracted_appno", result)

    def test_unique_earlier_application_resolves_and_is_kept_apart_from_the_curated_edges(self):
        result, index, observations, edges = self.graph({"001-5": "111/58"})
        block = result["with_extracted_appno"]
        self.assertEqual(result["coverage"]["unique_edges"], 0)                      # the curated numbers are unchanged
        self.assertEqual(block["coverage"]["edges_from_extracted_application"], 1)
        self.assertEqual(block["ranking"][0]["case_id"], "001-1")
        self.assertEqual((block["ranking"][0]["cited_by_curated_list"], block["ranking"][0]["cited_by_extracted_application"]), (0, 1))
        self.assertEqual(block["citing_by_target"]["001-1"], ["001-5"])
        self.assertEqual({o["origin"] for o in observations}, {"hudoc_extractedappno"})
        self.assertEqual(len(edges), 1)

    def test_several_judgments_of_one_application_stay_ambiguous(self):
        block = self.graph({"001-5": "222/58"})[0]["with_extracted_appno"]
        self.assertEqual(block["coverage"]["by_status"], {"ambiguous": 1})
        self.assertEqual(block["coverage"]["unique_edges"], 0)

    def test_later_judgments_own_numbers_and_unknown_numbers_are_not_edges(self):
        block = self.graph({"001-5": "333/58;444/58;999/58"})[0]["with_extracted_appno"]
        self.assertEqual(block["coverage"]["by_status"], {"chronology_conflict": 1, "self_reference": 1, "unresolved": 1})
        self.assertEqual(block["coverage"]["unique_edges"], 0)

    def test_curated_and_extracted_evidence_for_one_pair_count_once(self):
        rows = self.rows()
        rows[4]["scl"] = "Sample v. Poland, no. 111/58"
        result, *_ = build_graph(fixture(rows, ("ENG", "FRE")), {"001-5": "111/58"})
        block = result["with_extracted_appno"]
        self.assertEqual(result["coverage"]["unique_edges"], 1)
        self.assertEqual((block["coverage"]["unique_edges"], block["coverage"]["edges_in_both"]), (1, 1))
        self.assertEqual(block["ranking"][0]["cited_by_count"], 1)


if __name__ == "__main__":
    unittest.main()
