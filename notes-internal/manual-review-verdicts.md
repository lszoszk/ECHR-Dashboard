# Manual Review Verdicts

**Reviewer:** _____________________
**Date completed:** _____________________

Companion to [`manual-review-tasks.md`](manual-review-tasks.md). Fill in
each line as you complete a task. Free-text comment is optional but useful
for any DISPUTED verdicts.

---

## Task M1 — LLM-flagged "incorrect" relabels (7 items)

```
1.1 [ ] WRONG-relabel  [ ] DEFENSIBLE  Comment: ________
1.2 [ ] WRONG-relabel  [ ] DEFENSIBLE  Comment: ________
1.3 [ ] WRONG-relabel  [ ] DEFENSIBLE  Comment: ________
1.4 [ ] WRONG-relabel  [ ] DEFENSIBLE  Comment: ________
1.5 [ ] WRONG-relabel  [ ] DEFENSIBLE  Comment: ________
1.6 [ ] WRONG-relabel  [ ] DEFENSIBLE  Comment: ________
1.7 [ ] WRONG-relabel  [ ] DEFENSIBLE  Comment: ________
```

**Summary:**
- Items confirmed as wrong: ___ / 7
- Items LLM over-flagged (actually defensible): ___ / 7
- Adjusted P1-P7 precision estimate: _______ %

---

## Task M2 — Merits sub-typing schema (10 items)

```
2.1  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.2  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.3  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.4  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.5  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.6  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.7  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.8  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.9  [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
2.10 [ ] CORRECT  [ ] WRONG  [ ] DEFENSIBLE-BUT-MARGINAL  Comment: ________
```

**Summary:**
- Schema agreement: ___ / 10 CORRECT, ___ marginal, ___ WRONG
- Notes on schema refinement: ________

---

## Task M3 — Population A structural validation (5 items)

```
3.1 (McCallum v. UK 1990)        [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
3.2 (De Cubber v. Belgium 1984)  [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
3.3 (Kefalas v. Greece 1995)     [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
3.4 (Sporrong Art. 50, 1984)     [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
3.5 (Niemietz v. Germany 1992)   [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
```

**Summary:**
- Cases confirmed: ___ / 5
- Disputes (segmentation issues found): ________

---

## Task M4 — Worked-example validation (4 items)

```
4.1 (Wainwright v. UK)               [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
4.2 (Liatukas v. Lithuania)          [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
4.3 (Murdalovy v. Russia)            [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
4.4 (Popova "Privileged Pensioners") [ ] CONFIRMED  [ ] DISPUTED  Comment: ________
```

---

## Task M5 — Population C Introduction content (3 items)

```
5.1 (Çetin and Others v. Türkiye)    [ ] APPLICANT TABLE  [ ] PROCEDURAL HISTORY  [ ] MIXED  Comment: ________
5.2 (Grechek and Others v. Russia)   [ ] APPLICANT TABLE  [ ] PROCEDURAL HISTORY  [ ] MIXED  Comment: ________
5.3 (Israilovy and Others v. Russia) [ ] APPLICANT TABLE  [ ] PROCEDURAL HISTORY  [ ] MIXED  Comment: ________
```

---

## Task M6 — Backup integrity SQL spot-check

```
6.1 [ ] CONFIRMED  [ ] BACKUP INVALID  Comment: ________
```

---

## Overall Methodology Updates Triggered

After completion, the following methodology claims will be added to or updated in the public docs:

- [ ] Section 2 of `precision-audit.md`: "97.6% precision (LLM-audited; M1: ___ / 7 incorrect flags confirmed by human expert)"
- [ ] Section 6 of `merits-subtyping-pilot.md`: "Schema validated by human review on 10 samples (M2: ___ / 10 agreement)"
- [ ] Section 2.1 of `data-cleaning-full.md`: "Population A precision validated on 5 random pre-1998 cases (M3: ___ / 5 confirmed)"
- [ ] Section 5 of `data-cleaning-full.md`: "Worked examples (4 cases) verified by hand against HUDOC source (M4: ___ / 4 confirmed)"
- [ ] Section 9.3 of `data-cleaning-full.md`: "Population C `Introduction` table-content claim validated on 3 mass cases (M5: ___ / 3 confirmed)"
- [ ] Section 7 of `data-cleaning-full.md`: "Backup integrity verified by SQL inspection on `_p1_backup` (M6: confirmed/invalid)"
