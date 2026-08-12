# LM Industrial Prospecting Agent

Off-market seller identification for **industrial property in Greater Vancouver, BC**.

## What this project is for

We hold bulk land title pulls and corporate registry searches. The goal is to find
landlords who are **not yet aware they are sellers** — owners whose situation is about
to force a decision (mortgage renewal at a materially higher rate, a lien or judgment
on title, a dissolving corporate owner, an estate in transition).

Two deliverables drive every design decision:

1. **Rank owners by motivation** — surface the ones likely to transact in the next
   6–18 months, before they call a broker.
2. **Decide where to spend title pulls** — output addresses / postal codes worth a
   `$14` title search, and just as importantly, the ones that aren't.

The user is an industrial broker. Output should be usable by a broker, not a data
scientist: ranked lists with the *reason* attached, not opaque scores.

## The economic constraint that shapes everything

A title pull costs **$14** — but measured against real deals, that is not the binding
constraint. A comps set of 55 Surrey industrial transactions puts the **median deal at
$9.0M**, which at 1.5% is roughly **$135,000 gross commission — about 9,600 title pulls.**
One closed deal funds more pulls than a broker will make in years.

So the real scarce input is **broker attention, not the $14**. Be more liberal about
pulling title than the $14 framing suggests, and ruthless about which leads earn a phone
call. A rule producing many weak-but-positive leads is worse than one producing few strong
ones — not because the pulls cost too much, but because the follow-up does.

Design the pipeline as a funnel — cheap signals gate expensive ones:

| Tier | Source | Cost | Role |
|---|---|---|---|
| 0 | Data we already hold (prior pulls, corp searches) | free | baseline, training signal |
| 1 | BC Assessment, mapping, permits, zoning | free / cheap | build the candidate universe |
| 2 | Corporate registry lookups | low | owner-entity health |
| 3 | **Title pull** | **$14** | confirm charges, only on ranked candidates |

Never propose a design that pulls title to *discover* candidates. Title confirms a
hypothesis that cheaper tiers already raised.

When you evaluate a targeting rule, express it as expected value, not accuracy:

```
EV = P(motivated) x P(we win the listing) x expected_commission  -  $14
```

Real inputs for that equation, from 55 Surrey industrial comps (2021-23): median price
$9.0M, median $560/sq ft, price range $4.0M-$178M. Commission rate is the broker's to
supply — 1.5% is used above only as an illustration, not a known figure.

## Domain notes

Verify specifics against source docs before relying on them in code — these are
orientation, not gospel.

- **LTSA** — Land Title and Survey Authority, the BC land title registry. Titles are
  keyed by **PID** (9-digit Parcel Identifier). Charges on title include mortgages,
  builders liens, judgments, and Certificates of Pending Litigation (CPL).
- **BC Assessment** — assessed value, property classification, and folio/roll number.
  Industrial generally falls in Class 4 (Major Industry) and Class 5 (Light Industry);
  Class 6 (Business/Other) catches a lot of flex and mixed industrial-office.
- **BC Registries / Corporate Registry** — company status (active, struck, dissolved),
  directors, registered office. A struck or dissolving owner entity is a strong signal.
- **LOTR** — Land Owner Transparency Registry, beneficial ownership behind corporate
  and trust title holders.
- A **mortgage registration date** is the anchor for renewal timing: a 5-year term
  registered in the 2020–2021 low-rate vintage renews into a materially higher payment.

Signal taxonomy lives in `docs/signals.md` — read it when working on scoring.

## Conventions

- **Never commit raw title or registry data.** It carries personal information and
  comes with source licensing restrictions. `data/` is gitignored; commit schemas,
  transformations, and aggregates instead.
- Keep the ranked-output format explainable: every lead carries the signals that
  put it there.
- Geography is Greater Vancouver / Metro Vancouver unless stated otherwise.

## What's built, and where the knowledge lives

Pipeline (all in `scripts/`, run in this order):

| Script | Does |
|---|---|
| `parse_titles.py` | LTSA Title Search Print PDFs -> one row per charge |
| `score_leads.py` | charges -> ranked leads, reasons attached (CONFIRMED tier) |
| `score_tier1_candidates.py` | municipal open data -> candidate universe (ESTIMATED tier) |
| `merge_autoprop_export.py` | AutoProp exports -> title numbers, real sale history |
| `build_renewal_watchlist.py` | comps -> dated mortgage-renewal watchlist |
| `build_contact_worksheet.py` | address list -> businesses at each address |

Two skills load automatically when relevant — read them rather than rediscovering:

- **`bc-municipal-data`** — which BC municipalities publish what (they differ enormously:
  Surrey has everything, Richmond has nothing), and how to find a new city's portal.
- **`property-data-traps`** — every parsing quirk and false signal found the hard way.
  Check it before trusting a new signal. Each entry produced a plausible wrong answer first.

## Standing rules learned from real mistakes

- **Never fabricate contact data.** No guessed emails, no inferred names. A broker dials
  these; a plausible wrong contact costs more than a blank cell. Blank is a valid answer.
- **Keep CONFIRMED and ESTIMATED in separate columns**, never blended. A real maturity date
  is evidence; purchase date plus an assumed term is arithmetic.
- **Prefer the conservative default when a classification is ambiguous.** Over-calling a
  renewal wastes broker time; under-calling one costs nothing.
- **Deduplicate by PID before ranking.** One PID can cover several legal sub-parcels.

## Adding new knowledge to this repo

See `.claude/skills/README.md` — that's the drop-in folder for anything new you build
for Claude Code. Broad, always-relevant context goes here in CLAUDE.md; specialized
procedures go in a skill so they only load when relevant.
