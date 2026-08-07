# Scripts

Phase 1 of `docs/roadmap.md`: turn title pulls already on hand into a ranked call
list, no new spend required.

## Pipeline

```
data/samples/titles/*.pdf          (raw LTSA Title Search Print PDFs — gitignored)
        │
        ▼  parse_titles.py
data/parsed/charges.csv            (one row per charge — gitignored)
        │
        ▼  score_leads.py
data/parsed/leads.csv              (one row per PID, ranked, reasons attached)
```

```bash
pip install pdfplumber

python3 scripts/parse_titles.py data/samples/titles/*.pdf -o data/parsed/charges.csv
python3 scripts/score_leads.py data/parsed/charges.csv -o data/parsed/leads.csv
```

Both output CSVs land under `data/`, which is gitignored — they carry names and
addresses. Only the parser and scorer are committed.

## parse_titles.py

Reads the LTSA "Title Search Print" PDF format and emits one row per charge
(mortgage, covenant, easement, lien, judgment, CPL, ...), each carrying its parent
title's owner and property fields.

**Why pdfplumber and not plain text extraction.** LTSA prints this as a two-column
form. Naive text extraction (pypdf, `pdftotext`) reads down one column then the
other, scrambling every label away from its value — e.g. all the labels on a page
come out first, then all the values, in an order that doesn't line up. This script
uses pdfplumber's word coordinates to regroup words into true left-to-right,
top-to-bottom reading order before parsing a single field. If LTSA ever changes
their print layout, that's the assumption most likely to break.

**Colon inconsistency.** Some labels render with a trailing colon in this form
(`Parcel Identifier: 026-925-460`) and some don't (`Title Number CB505033`,
`Taxation Authority Langley, ...`). Both are handled — see `NO_COLON_LABELS` in the
script — but a new label LTSA adds later may need adding to one list or the other.

## score_leads.py

Rolls charges up to one row per PID and applies the debt-pressure and distress
signals from `docs/signals.md` (sections A and B — the ones observable straight off
title, no BC Assessment or corporate registry join needed yet). Every lead carries
its `reasons` as text, never a bare score, per CLAUDE.md's explainability rule.

Current signal set:

- Mortgage registration date → predicted renewal window, using a per-lender-type
  assumed term (`ASSUMED_TERM_YEARS`). **These term assumptions are placeholders**
  — replace with real figures once someone who underwrites these deals weighs in.
  This is the single highest-leverage number to correct, per `docs/roadmap.md`.
- A predicted renewal window that has already passed with no newer mortgage
  registered — flagged as `renewal_overdue`, and scored *higher* than a
  still-pending renewal, not lower. It means the owner is likely already on a
  higher floating rate, or the print is stale and the file is a re-pull candidate.
- Multiple mortgages on title (secondary financing).
- Private / MIC lender mortgages, via `lender_type` name-matching
  (`LENDER_TYPE_PATTERNS`) — coarse, and worth widening once there's more lender
  name variety to test against.
- CPL, judgment, builders lien — each adds distress weight directly.
- Recent purchase (current owner's `Application Received` date within the last 3
  years) → suppress as a negative signal, per `docs/signals.md` section E.
  **Correction from the first sample batch:** `Declared Value` initially looked
  like the right recent-purchase flag, since both titles that had it were recent
  transfers. A second batch broke that — two titles from 1999 and 2004 still carry
  a `Declared Value` decades later, because it's whatever was declared when that
  title's application was filed, not a marker of recency. `application_received`
  is the correct proxy for how long the current owner has held title; `Declared
  Value` is kept as descriptive context only.
- Long hold (20+ years on title) and absentee ownership (mailing address outside
  the property's municipality, with an extra weight if it's out of province) —
  the holding-pattern signals from `docs/signals.md` section D. Both are cheap
  string comparisons already available on every parsed title, no BC Assessment
  join needed.
- No mortgage currently on title, on an owner who isn't a recent purchase —
  informational for now (full-equity position), not weighted into the score. On
  its own it's ambiguous: could mean paid off and ripe to sell, or could mean the
  owner never needed to borrow. Worth revisiting once outcome data exists to test
  which reading holds.

**Not yet implemented, all noted in `docs/signals.md`:** owner-entity health (needs
a BC Registries corporate-search join), holding-pattern signals (needs BC
Assessment), and the postal-code / segment rollup (needs Phase 2's parcel
universe). `taxation_authority` here is the municipality, not a postal code —
useful for now, but not the same granularity the roadmap's segment scoring wants.

## Validated against

Eight real title pulls across two batches (see `docs/tomorrow-checklist.md` for
what to bring for a bigger one). Worth knowing about:

- A PID with two stacked private-lender mortgages, a Certificate of Pending
  Litigation filed by the first lender, and a municipal judgment — correctly
  ranks at the top.
- A title acquired mid-2024 with a same-day mortgage, and a second acquired in
  early 2026 with no mortgage at all — both correctly suppressed as recent
  purchases rather than ranked as leads.
- Two titles held by the same owner for 22 and 27 years respectively, fully
  unencumbered — one with an out-of-province (Calgary) mailing address on a
  Burnaby property. These surfaced the `declared_value` bug above and, once
  fixed, correctly rank as long-hold/absentee candidates rather than getting
  swept up in the recent-purchase suppression they don't belong in.
