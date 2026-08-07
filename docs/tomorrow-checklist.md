# What to bring to the first working session

Answering these is most of Phase 1. None require writing code.

## The existing pulls

- [ ] How many titles have been pulled, roughly, and over what period?
- [ ] What format are they in — PDF, text, a spreadsheet someone keyed in by hand?
- [ ] Is there a manifest of what was pulled and when, or only the documents?
- [ ] Are the corporate searches linked to the titles, or a separate pile?
- [ ] Drop a **small sample** in first — three or four titles is enough to build the
      parser against. Do not move the whole set until the parser works.

## Ground truth

The most valuable thing in the office, and the easiest to overlook.

- [ ] Of everything pulled so far, which ones led to a conversation?
- [ ] Which led to a listing or a deal?
- [ ] Even five or ten known outcomes is enough to sanity-check whether the signals
      in `docs/signals.md` point the right way.
- [ ] If none of this was recorded — fine, that is common. The answer is to start
      recording now, not to reconstruct it.

## Access

- [ ] What property data does the brokerage already subscribe to? Check before
      buying anything — the Phase 2 universe may already be sitting in a platform
      you have a login for.
- [ ] Bulk assessment data: available, or lookup-only?
- [ ] Is title pulling done through a portal login, and does it have any bulk or
      batch capability?

## Judgment calls only you can make

- [ ] **Minimum deal size worth pursuing.** This sets the negative filter on small
      strata units and drives the whole EV calculation.
- [ ] **Geography.** Which submarkets are genuinely in scope versus nominally in
      Metro Vancouver but not somewhere you would service.
- [ ] **Capacity.** How many leads per month can actually be worked? A system that
      produces 400 leads for someone who can call 20 has not solved the problem —
      it has moved it. The ranking's job is to fill that number with the best 20.
- [ ] **Typical commercial mortgage terms** in your experience, by lender type.
      This directly sets the renewal-timing assumption in Phase 1.

## Worth thinking about tonight

If the renewal list from Phase 1 landed on your desk tomorrow with 60 names on it —
what would you actually do with it? The answer shapes the output format more than
any technical decision in this repo.
