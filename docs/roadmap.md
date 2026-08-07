# Build roadmap

Sequenced so that something useful ships before anything sophisticated does.

## Guiding principle

The existing pulls are the asset. Every phase below either extracts more value from
titles already paid for, or avoids paying for new ones. Do not build a scoring engine
before there is a parsed table to score.

---

## Phase 1 — Ship the renewal list

**Goal: a call list, from data already on hand, with no new spend.**

Parse the existing title pulls into one row per charge and filter to mortgages
registered in the low-rate vintage. Sort by registration date. That is a rolling
12-month call list, and it is the single highest-signal artifact in this system
because it has a *date* attached — it tells the broker not just who, but when.

Everything else in this repo is an optimization on top of this list.

Minimum viable table, one row per charge:

| Field | Source | Notes |
|---|---|---|
| `pid` | title | join key |
| `civic_address`, `postal_code` | title / BCA | |
| `registered_owner` | title | person or corporate entity |
| `owner_mailing_address` | title | absentee signal when it differs from civic |
| `charge_type` | title | MORTGAGE, BUILDERS LIEN, JUDGMENT, CPL, ... |
| `charge_reg_date` | title | **the anchor for renewal timing** |
| `charge_reg_number` | title | |
| `chargeholder` | title | lender name — see lender-type note below |
| `face_amount` | title | upper bound, not outstanding balance |
| `title_pull_date` | our records | staleness — see below |

Then: `predicted_renewal = charge_reg_date + assumed_term`.

**Make `assumed_term` a parameter, not a constant.** Commercial terms are not
uniformly five years, and the chargeholder is a usable proxy for term length —
chartered banks and credit unions cluster shorter, life insurance companies write
long, and MICs and private lenders write very short at high cost. Bucket lenders by
type and assign a term per bucket. Sharpening this one assumption improves timing
accuracy more than any other tuning available in Phase 1.

### Two data-quality traps to handle here

**Staleness.** A title reflects charges current *as of the pull date*. A pull from
2023 will not show a discharge, a refinance, or a lien registered since. Carry
`title_pull_date` on every row and decay confidence with age. The re-pull decision is
itself a $14 question — re-pull only where the lead is otherwise strong.

**Face amount is not balance.** The registered amount is what the charge secures, not
what is owed. It is an upper bound and it does not amortize. If loan-to-value has been
computed from it anywhere, that ratio is biased high across the entire dataset. Use it
as a coarse band, never as a precise LTV.

---

## Phase 2 — Build the candidate universe

**Goal: know every industrial property in the region, so ranking has something to
rank.** Titles already pulled are a biased sample of wherever attention happened to
go; the universe is what makes coverage measurable.

Assemble from free and low-cost sources — assessment data for parcels, classification
and assessed values; municipal open data for zoning, permits, and business licences;
regional land-use layers for industrial designation. Confirm what is actually
obtainable in bulk versus only lookup-by-lookup, and check what the brokerage already
subscribes to before buying anything.

Output: a parcel table for industrial Metro Vancouver, joinable to Phase 1 on `pid`.

---

## Phase 3 — Score, rank, and gate the spend

Apply `docs/signals.md`. Two outputs, both required:

1. **Owner ranking** — leads with reasons attached, never a bare score.
2. **Segment ranking** — postal codes and submarkets worth spending pulls on, and
   the ones to skip. This is the second stated goal and it is where the $14 is saved.

Run negative signals as a hard filter *before* scoring, not as a penalty inside it.
Recently sold, institutionally owned, and owner-occupied-and-growing should never
reach the ranked list at all.

Hold back a small exploration budget for segments with no pull history. A segment that
has never been sampled looks identical to a bad one, and pure exploitation will
quietly write off territory that was never tested.

---

## Phase 4 — Close the loop

Without outcome labels this stays a well-organized guess. Every pull should record:

```
pid | pull_date | reason_pulled | signals_present | contact_made | response | listing | closed
```

This is the only way to answer the question the whole system exists to answer —
**cost per qualified lead, by segment and by signal.** It is also the input that makes
Phase 3 improve rather than merely persist.

Start recording from the very first pull. Retrofitting labels onto past pulls from
memory produces exactly the bias the system is meant to remove.

---

## Compliance constraints worth designing around

Not blockers, but cheaper to build around now than to retrofit:

- Title and registry data carries personal information, and the source licence
  restricts redistribution. Keep raw extracts out of version control and out of
  anything shared externally.
- Provincial and federal private-sector privacy law governs use of personal
  information for marketing.
- Anti-spam law governs electronic outreach; direct mail and phone sit under
  different regimes than email.

Confirm the specifics with the brokerage's own compliance guidance — the design
implication is simply that outreach channel and consent state should be fields in the
system, not afterthoughts.
