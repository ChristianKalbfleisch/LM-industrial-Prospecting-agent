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

A title pull costs **$14**. That makes this a **precision problem, not a recall
problem**. Missing a lead costs nothing measurable; pulling 500 titles on a bad
segment costs $7,000 and a week of wasted follow-up.

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

The broker's time is the scarcer input than the $14 — a rule that produces many
weak-but-positive leads is worse than one that produces few strong ones.

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

## Adding new knowledge to this repo

See `.claude/skills/README.md` — that's the drop-in folder for anything new you build
for Claude Code. Broad, always-relevant context goes here in CLAUDE.md; specialized
procedures go in a skill so they only load when relevant.
