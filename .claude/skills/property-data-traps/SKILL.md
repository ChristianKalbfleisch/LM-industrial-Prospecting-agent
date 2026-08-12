---
name: property-data-traps
description: Known data traps and parsing quirks in BC land titles, BC Assessment data, comparable-sales exports, and AutoProp exports. Read before parsing title PDFs, computing mortgage renewal dates, scoring prospects, or trusting a sale date or lien as a signal. Every item here produced a wrong answer before it was caught.
---

# Property data traps

Each of these was found by checking real data against real results, and each one silently
produced a *plausible but wrong* answer first. Check against this list before trusting a
new signal.

## Parsing LTSA "Title Search Print" PDFs

**It's a two-column form.** Plain text extraction (pypdf, pdftotext) reads column-by-column
and scrambles every label away from its value. Use `pdfplumber` word coordinates and
regroup words into true reading-order lines by y-position first. This is the single thing
that makes the parser work.

**Label punctuation is inconsistent.** Some fields carry a colon (`Parcel Identifier: 026-925-460`),
some don't (`Title Number CB505033`, `Taxation Authority Langley, ...`). Handle both, and
list longer labels first so `From Title Number` doesn't get eaten by `Title Number`.

**Real signals hide in the free-text "Legal Notations" section.** Not every charge appears
as a formal `Nature:` line. A Costco-owned Langley parcel carried an active
`NOTICE OF INTEREST, BUILDERS LIEN ACT (S.3(2))` filed the same week as purchase — visible
only in Legal Notations. Scan that section as free text for lien / CPL / receivership /
foreclosure / bankruptcy language, or you will miss live distress entirely.

**Titles show only CURRENT charges.** A discharged mortgage vanishes. So a mortgage still
on title is still outstanding — but the print is only accurate as of its pull date. Carry
`title_pull_date` and decay confidence with age.

## Signals that look real and aren't

**`Declared Value` does NOT mean recent sale.** It looked like a perfect recent-purchase
flag on a first batch of 4 titles — both that had it were recent. A second batch had
titles from **1999 and 2004** still carrying a Declared Value. It's whatever was declared
when that title's application was filed. Use `Application Received` for ownership recency.

**A mortgage decades overdue for renewal is not distress.** Predicted-renewal dates from
1998-2002 with nothing newer on title are almost always paid-off mortgages BC never
required the owner to formally discharge. Past ~8 years overdue, treat as unencumbered,
not as urgent debt. Otherwise stale paper outranks live leads.

**Old builders-lien notices are usually dead paper.** Two `s.3(2)` notices from 2009 sat
on otherwise-clean 2026 titles (First Nations and conservation land). But a first attempt
at a 2-year staleness cutoff mis-flagged Costco's own 2.9-year-old filing — the exact live
case the check existed to catch. 6 years is the current conservative cutoff; the true
limitation period for this filing type is unconfirmed, so don't tighten it without a legal
read.

**A registered charge amount is a face value, not an outstanding balance.** It doesn't
amortise. Any LTV computed from it is biased high. Use as a coarse band only.

**"REJECT - NOT SUITABLE FOR SALES ANALYSIS"** in BC Assessment / AutoProp sale history
means an internal transfer or reorganisation, not an arm's-length sale. Counting it as a
real ownership change creates false recent-purchase suppressions on properties that never
actually traded.

## Duplicate rows that look like separate properties

**One PID can cover several legal sub-parcels.** Surrey's property file has one row per
legal description, not per PID — 299 PIDs were duplicated, one up to 6 times, mostly Crown
lease sites (`LEASE/PERMIT/LICENCE` in the legal description). Unmerged, the same property
appears repeatedly on a ranked list as if it were several opportunities. Group by PID and
sum assessed values first.

AutoProp exports have the same shape: several civic addresses under one PID. Prefer the
sub-row that actually carries a **Title Number** — that's the one resolved to a real
registered title.

## Lender classification (drives every renewal date)

Two misses that changed scoring:

- **`\bTD\b` never matches "THE TORONTO-DOMINION BANK"** — 17 mortgages went unclassified.
- **Life insurers register as "<X> LIFE ASSURANCE COMPANY", not "LIFE INSURANCE"** —
  Imperial Life, Mutual Life, National Life and Manufacturers Life all defaulted to a
  5-year term when the observed term for that class is ~10. A five-year error in the class
  with the longest term. One property's predicted renewal moved 2026 → 2031 once fixed.

**Don't over-correct.** A broad "anything ending in LTD/INC/CORP is a private lender"
pattern swept in Laurentian Trust, a church extension fund and a listed REIT and handed
them 1-year terms — inventing renewal urgency. Match only genuine numbered companies
(`^\d{6,7} B.C. LTD`); let named corporations keep the conservative 5-year default.
**Over-calling a renewal wastes a broker's afternoon; under-calling one costs nothing.**

## Mortgage term evidence (n=7, from real maturity dates)

| Class | Observed | Assumption | Status |
|---|---|---|---|
| MIC / private | 0.30, 0.44, 1.16 yr | 1 yr | Confirmed |
| Life insurance | 10.01 yr | 10 yr | Confirmed |
| Chartered bank | 3.05 yr (n=1) | 5 yr | Looks long — unresolved |
| Numbered company | 5.06 yr (n=1) | 1 yr | Looks short — unresolved |

The two n=1 rows are deliberately **not** tuned — fitting to a sample of one is worse than
an honest guess. More maturity dates settle them.

**Bigger caveat:** 36 of 44 mortgages in a Surrey comps set were `Subsequent - Demand
Debenture`, not fixed-term mortgages. Demand debentures are payable on demand with no
clean renewal date. If that mix is typical, renewal timing applies to less of this market
than assumed, and distress signals deserve more weight. Unresolved — worth testing.

## Contact data: what exists and what doesn't

Tested, not assumed:
- Business directories (Yellowpages/Canpages/BBB) reliably give a **main switchboard number**.
- They do **not** give named senior contacts or email addresses for private industrial firms.
- Municipal licence data has no personal names or emails anywhere.
- The only authoritative source for a named senior person is a **BC Registries corporate
  search** (directors and officers).

**Never pattern-guess an email or infer a contact name.** A broker will dial these. A
plausible wrong contact costs a call, a misdirected email, and credibility with a prospect
they get one shot at. A blank cell is the correct output.
