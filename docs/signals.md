# Motivation signals

Working taxonomy for identifying industrial owners who are likely sellers before they
know it. Each signal notes the cheapest tier that can observe it — see the funnel in
`CLAUDE.md`. Treat weights as placeholders until we backtest against closed deals.

## A. Debt pressure

The strongest category, because it has a date attached.

| Signal | Tier | Notes |
|---|---|---|
| Mortgage registered 2020–2021, 5-year term | 3 (title) | Renews into a much higher rate; payment shock is the classic trigger |
| High registered charge amount vs. assessed value | 3 + 1 | Registered face amount is not the outstanding balance — treat as an upper bound |
| Multiple mortgages / second position | 3 | Secondary financing suggests constrained access to capital |
| Private or MIC lender as chargeholder | 3 | Often short-term and expensive; renewal pressure is sharper |
| Recent refinance on an otherwise static holding | 3 | Cash was needed for something |

Renewal timing is the highest-value derived field in the system: registration date
plus assumed term gives a **predicted renewal window**, which is what makes outreach
timely rather than generic.

## B. Encumbrance and distress

| Signal | Tier | Notes |
|---|---|---|
| Builders lien | 3 | Disputed construction work; often signals a stalled project |
| Judgment registered against title | 3 | Owner-level financial trouble |
| Certificate of Pending Litigation | 3 | Ownership or contract dispute; may block a clean sale |
| Tax sale / arrears indicators | 1–2 | Municipal source varies by jurisdiction |

## C. Owner-entity health

| Signal | Tier | Notes |
|---|---|---|
| Corporate owner struck or in dissolution | 2 | Strong, and cheap to detect |
| Registered office changed to a law or accounting firm | 2 | Often precedes a wind-up or estate process |
| Director aging / long-unchanged director list | 2 | Succession pressure |
| Transmission to executor, or estate on title | 3 | Property is being settled |
| Numbered company holding a single asset | 2 | Single-asset holdcos transact more cleanly |

## D. Holding-pattern signals

| Signal | Tier | Notes |
|---|---|---|
| Hold period 20+ years | 1 | Large embedded gain, aging ownership |
| Owner mailing address differs from property address | 1 | Absentee — less attached to operating the asset |
| Owner address out of province / out of country | 1 | Stronger version of the above |
| No permits or capital work in 10+ years | 1 | Disinvestment; owner is harvesting, not building |
| Assessed value growth far outpacing improvement value | 1 | Land-value play — the building is no longer the point |
| Owner holds several properties in a tight cluster | 1–2 | Portfolio owner; one conversation can surface several assets |

## E. Negative signals — suppress the pull

Just as important as positives, since every avoided pull is $14 saved.

- Sold within the last 24–36 months — new owner, fresh debt, no motivation.
- Owner-occupied by an active, growing operating business.
- Institutional, REIT, or pension-fund ownership — they do not transact off-market
  through a local broker.
- Crown, municipal, First Nation, or utility ownership.
- Property already listed, or recently expired with another brokerage.
- Strata industrial units below a size threshold, where commission does not cover
  the acquisition effort.

## Postal-code / segment scoring

Goal 2 is geographic triage, not just per-owner ranking. Score a **segment** (postal
code, submarket, or zoning band) on prior yield, then use it to gate individual pulls:

```
segment_score = hit_rate x avg_deal_value x industrial_density
```

Where `hit_rate` is measured from titles already pulled — the existing data set is the
training signal. A segment with no pull history is an exploration cost; sample it
deliberately with a small budget rather than either avoiding it or flooding it.

Track realized cost per qualified lead per segment. That single number tells the
broker where the next $1,000 of title budget should go.
