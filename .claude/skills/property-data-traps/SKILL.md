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

## Corporate searches: what they actually tell you

**Join corp searches to title by INCORPORATION NUMBER, never by company name.** Matching
the comps "purchaser" name against company names resolved 31 of 55 rows. Joining on the
incorporation number carried on title resolved 46 of 50 — because the name match silently
missed every renamed or restructured owner. `1256495 B.C. LTD.` and
`SALMONBERRY PROPERTIES INC.` are the same incorporation number, holding two adjacent
strata lots; by name they look like unrelated parties.

**The comps "purchaser" is often a trade name, not the entity on title.** 18 of 50 rows
differed: `Punjab Milk Foods` -> `1357336 B.C. LTD.`, `Applewood Kia` -> `SOUTH COAST
BRITISH COLUMBIA TRANSPORTATION AUTHORITY`. Only the entity on title can sign a listing,
and in that last case the property had already passed to a public body. Never dial the
comps name without checking title.

**ALL ACTIVE is a real result, not a parsing failure.** All 45 companies searched in the
first Surrey batch came back ACTIVE, none in liquidation, none in receivership, zero
registered offices at law or accounting firms. The struck/dissolved signal this project
weights most heavily was simply absent. Report that plainly rather than hunting for a
substitute.

**Annual-report delinquency is the usable soft signal.** The registrar may strike a company
that misses two consecutive annual reports, so an owner two or three filings behind is on
the path toward the dissolution event — visible before it happens. Note "Last Annual Report
Filed" is the *anniversary date* the report was filed for, so months-since is the
delinquency measure. In the Surrey batch: one owner 37.5 months behind (3 filings), which
happened to be the top-ranked property on the list. Weak alone — plenty of solvent
companies file late — it earns weight only on a property already ranked by other signals.

**A recognition date that disagrees with the numbered name means restructuring.**
`1367409 B.C. LTD.` registered as `BC1569621` with a recognition date of January 1, 2026 is
an amalgamation or continuation, not a new holdco. Worth a small score bump; ownership was
reorganised recently.

**No annual report is not delinquency when none is due yet.** A company recognized inside
the last year has nothing to file. Check the incorporation date before flagging.

**Public authorities score well and are never sellers.** Vancouver Fraser Port Authority
and TransLink hold industrial land as infrastructure. They pass every comps-derived signal
and have no corporate record in BC Registries. Detect them off the owner name on title and
rank them out — nothing cheaper catches this.

**Not every owner is a BC company.** `2184034 ALBERTA LTD.` and `FORMA GROUP INC.
(767084-2)` are extraprovincial or federal registrations. BC issues them a SEPARATE
registration number (Forma is `A0128362` in BC), so the incorporation number on title —
the home jurisdiction's — will not join. Fall back to a company-name match for these only.

## Parsing the corp summary PDF (three bugs, each silently wrong)

**It is a two-column form like the title print, and flat text ran the columns together.**
A first pass captured only the FIRST director of every company, because the line
`CANADA CANADA` — the two columns' country lines side by side — matches an ALL-CAPS
"next section header" pattern and terminated the section early. 45 companies came back
with ~50 directors; the corrected parser finds 126. Read addresses off word coordinates,
splitting at the page's own `Delivery Address:` label rather than a hardcoded x.

**Do NOT apply the column split to the whole page.** The company name and the field labels
straddle the middle of the page, so a fixed split shears them in half. Keep flat text for
the field regexes and use coordinates only inside address blocks.

**A label and its value sit at slightly different `top` values** when their font sizes
differ, so grouping words into lines by `top` puts `BC1423681` and `Incorporation Number:`
on separate lines — and the regex then grabs the next line instead, returning `KKBL` as an
incorporation number. Cluster on the vertical CENTRE of each word, not the top.

**`Extraprovincial Company Summary` is a different form.** Costco and Lhoist parsed to
nothing because the splitter only looked for `BC Company Summary`. That form has
`Registration Number in BC` instead of an incorporation number, a HEAD OFFICE instead of a
registered office, and states plainly that *"Directors are not recorded for extraprovincial
registration types"* — it files a **BC attorney** instead. That attorney is the only BC-side
contact the registry holds for such a company.

**The registry states amalgamation outright.** `Recognition Date and Time: ... as a result
of an Amalgamation` is better evidence than inferring restructuring from a mismatch between
a numbered name and its registration number. Read the field; keep the inference as backup.

## Contact data from the corporate register

**Registry addresses are real; emails and phones do not exist there.** BC Registries
publishes a registered office address and a mailing address for every director. It
publishes no email address and no phone number for anyone. Getting those means a directory
or a subscription source checked name by name — never inference.

**A director's registry address that equals the subject property means owner-occupier.**
Three of 50 Surrey rows matched this way. It changes the conversation completely: an
owner-occupier has to solve where the business goes before they can sell, and the person
on file is the decision maker on site rather than a passive investor.

**A registered office shared across several companies is usually the accountant or lawyer,
not a portfolio.** Check whether the address belongs to a professional firm before reading
common ownership into it.

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
