#!/usr/bin/env python3
"""Roll parsed charges (scripts/parse_titles.py output) up to one ranked row per PID.

Signals implemented here are the debt-pressure and distress groups from
docs/signals.md (sections A and B) — the ones observable straight off title, no
BC Assessment or corporate registry join needed yet. Every row carries the reasons
that put it there, per CLAUDE.md's "ranked lists with the reason attached" rule —
this deliberately does not collapse to a single opaque score.

    python3 scripts/score_leads.py data/parsed/charges.csv -o data/parsed/leads.csv
"""

import argparse
import csv
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

TODAY = date.today()

PRIVATE_LENDER_TYPES = {"mic_private", "numbered_co_private"}
DISTRESS_TYPES = {"CERTIFICATE OF PENDING LITIGATION", "JUDGMENT", "BUILDERS LIEN"}

# Some real distress signals never appear as a formal "Nature:" charge line — LTSA
# sometimes files them as free text in the "Legal Notations" section instead. Found
# by checking a Costco-owned parcel that carries an active Builders Lien Act notice
# of interest there and nowhere else on the formally structured part of the title.
# Each pattern captures its own "NOTICE OF INTEREST, BUILDERS LIEN ACT (S.3(2))"-style
# phrase whole, rather than a separate generic "NOTICE OF INTEREST" pattern — every
# occurrence of that generic phrase in this dataset turned out to be part of the same
# builders-lien notice, so a second pattern just double-counted the identical text.
NOTATION_DISTRESS_PATTERNS = [
    (r"NOTICE\s+OF\s+INTEREST,?\s+BUILDERS?\s+LIEN\s+ACT", "Builders Lien Act notice of interest"),
    (r"CERTIFICATE\s+OF\s+PENDING\s+LITIGATION", "Certificate of Pending Litigation referenced"),
    (r"\bRECEIVER(SHIP)?\b", "Receivership referenced"),
    (r"\bFORECLOSURE\b", "Foreclosure referenced"),
    (r"\bBANKRUPTCY\b", "Bankruptcy referenced"),
]

# A first pass used a 2-year cutoff based on the general BC builders-lien limitation
# period, but that mis-flagged Costco's own 2023 filing (~2.9yr old) as stale — the
# exact case this whole check exists to catch. The s.3(2) notices seen on First
# Nations/conservation land (Tsawwassen, Ducks Unlimited, both ~2009, 17yrs old) may
# be a different substitute-security mechanism than an ordinary private-lot lien, so
# the true limitation period for this specific filing type isn't confirmed here.
# Widened to be conservative: this only needs to catch clearly-ancient filings, not
# draw a precise legal line — a real lawyer's read on the s.3(2) limitation period
# would let this be tightened again.
NOTATION_STALE_YEARS = 6


def scan_notation_distress(legal_notations: str) -> list:
    """Return (label, is_stale) for each distress phrase found in the free text."""
    if not legal_notations:
        return []
    upper = legal_notations.upper()
    hits = []
    for pattern, label in NOTATION_DISTRESS_PATTERNS:
        for m in re.finditer(pattern, upper):
            # look for a "FILED YYYY-MM-DD" within the next ~60 chars of this match
            window = upper[m.end(): m.end() + 60]
            date_m = re.search(r"FILED\s+(\d{4})-(\d{2})-(\d{2})", window)
            is_stale = False
            filed_date = None
            if date_m:
                y, mo, d = (int(x) for x in date_m.groups())
                try:
                    filed_date = date(y, mo, d)
                    age_years = (TODAY - filed_date).days / 365.25
                    is_stale = age_years > NOTATION_STALE_YEARS
                except ValueError:
                    pass
            hits.append((label, is_stale, filed_date.isoformat() if filed_date else None))
    return hits

# A title's Application Received date is when the *current* owner's title was
# registered — i.e. how long they've held it. Declared Value looked like a recent-
# purchase flag on the first sample batch (both titles that had it were recent), but
# a second batch showed titles from 1999 and 2004 that still carry a Declared Value
# decades later — it's whatever was declared when that title's application was
# filed, not a signal of recency on its own. application_received is the correct
# proxy; keep declared_value only as descriptive context.
RECENT_TRANSFER_YEARS = 3
LONG_HOLD_YEARS = 20
# Past this many years overdue, a "renewal" is more likely a paid-off mortgage that
# was never formally discharged from title (common in BC) than a live debt problem.
STALE_MORTGAGE_YEARS = 8


def holding_period_years(application_received: str):
    if not application_received:
        return None
    y, m, d = (int(x) for x in application_received.split("-"))
    try:
        received = date(y, m, d)
    except ValueError:
        return None
    return (TODAY - received).days / 365.25


def municipality_name(taxation_authority: str) -> str:
    if not taxation_authority:
        return ""
    return taxation_authority.split(",")[0].strip().upper()

# Placeholder terms by lender type, per docs/roadmap.md Phase 1 — replace with real
# figures once someone who underwrites these deals gives better numbers.
ASSUMED_TERM_YEARS = {
    "chartered_bank": 5,
    "credit_union": 5,
    "life_insurance": 10,
    "mic_private": 1,
    "numbered_co_private": 1,
    "other": 5,
    "": 5,
}


def load_charges(path: Path) -> dict:
    by_pid = defaultdict(list)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            by_pid[row["pid"]].append(row)
    return by_pid


def score_pid(pid: str, charges: list) -> dict:
    title = charges[0]
    mortgages = [c for c in charges if c["charge_type"] == "MORTGAGE"]
    mortgages.sort(key=lambda c: c["charge_reg_date"] or "")
    distress = [c for c in charges if c["charge_type"] in DISTRESS_TYPES]
    notation_hits = scan_notation_distress(title.get("legal_notations"))
    notation_distress = [(label, filed) for label, stale, filed in notation_hits if not stale]
    notation_stale = [(label, filed) for label, stale, filed in notation_hits if stale]

    reasons = []
    latest_renewal = None
    years_overdue = None
    latest_mortgage = mortgages[-1] if mortgages else None

    if latest_mortgage:
        lender_type = latest_mortgage["lender_type"] or "other"
        term = ASSUMED_TERM_YEARS.get(lender_type, 5)
        reg_date = latest_mortgage["charge_reg_date"]
        if reg_date:
            y, m, d = (int(x) for x in reg_date.split("-"))
            try:
                latest_renewal = date(y + term, m, d).isoformat()
            except ValueError:
                latest_renewal = date(y + term, m, 28).isoformat()
        reasons.append(
            f"Mortgage registered {reg_date} ({lender_type}, assumed {term}yr term) "
            f"-> predicted renewal ~{latest_renewal}"
        )
        years_overdue = None
        if latest_renewal and datetime.fromisoformat(latest_renewal).date() < TODAY:
            years_overdue = (TODAY - datetime.fromisoformat(latest_renewal).date()).days / 365.25
            if years_overdue <= STALE_MORTGAGE_YEARS:
                reasons.append(
                    "Predicted renewal date has already passed with no newer mortgage on "
                    "title — either a quiet renewal/extension the lender didn't re-register, "
                    "or the owner is past due and now on a higher floating rate. Worth a call "
                    "regardless, and a candidate for a fresh title pull to check for a discharge "
                    "or refinance we don't have on file."
                )
            else:
                reasons.append(
                    f"Renewal window passed {years_overdue:.0f} years ago with nothing newer on "
                    "title — at this age it's much more likely a paid-off mortgage that was "
                    "never formally discharged than a live renewal problem. Treating as roughly "
                    "unencumbered, not as urgent debt pressure."
                )

    if len(mortgages) >= 2:
        reasons.append(f"{len(mortgages)} mortgages registered — secondary financing in place")

    private_mortgages = [m for m in mortgages if m["lender_type"] in PRIVATE_LENDER_TYPES]
    if private_mortgages:
        reasons.append(
            f"{len(private_mortgages)} mortgage(s) from a private/MIC lender — "
            "short term, higher cost, sharper renewal pressure"
        )

    for c in distress:
        reasons.append(f"{c['charge_type']} registered {c['charge_reg_date']} by {c['chargeholder']}")

    for label, filed in notation_distress:
        filed_note = f", filed {filed}" if filed else ""
        reasons.append(
            f"{label}{filed_note} — found in the Legal Notations free text (not a formal "
            "charge line — confirm on a fresh title pull, but don't discount it for that reason)"
        )
    for label, filed in notation_stale:
        reasons.append(
            f"{label} filed {filed} — over {NOTATION_STALE_YEARS} years ago with nothing newer "
            "on title. Likely expired/administrative paper rather than a live dispute, but the "
            "exact limitation period for this filing type isn't confirmed here — worth a legal "
            "read if this parcel is otherwise interesting. Not counted toward the score."
        )

    hold_years = holding_period_years(title["application_received"])
    is_recent_transfer = hold_years is not None and hold_years < RECENT_TRANSFER_YEARS
    # A recent purchase is a negative signal (docs/signals.md section E) because a new
    # owner usually has no reason to sell yet. That reasoning doesn't hold when there's
    # an active distress signal on the same title — e.g. a Builders Lien Act notice
    # filed the same week as the purchase is a real problem regardless of how new the
    # ownership is. Found by checking a Costco parcel our scorer was suppressing
    # despite it carrying exactly this notice.
    has_any_distress = bool(distress) or bool(notation_distress)
    suppress_as_recent_transfer = is_recent_transfer and not has_any_distress
    is_long_hold = hold_years is not None and hold_years >= LONG_HOLD_YEARS
    if suppress_as_recent_transfer:
        reasons.append(
            f"Title registered to current owner {hold_years:.1f} years ago "
            f"({title['application_received']}) — recent purchase, suppress as a "
            "near-term seller candidate"
        )
    elif is_recent_transfer and has_any_distress:
        reasons.append(
            f"Title registered to current owner {hold_years:.1f} years ago "
            f"({title['application_received']}) — normally a recent-purchase suppression, "
            "but overridden here by the distress signal(s) above: those are real regardless "
            "of how new the ownership is."
        )
    elif is_long_hold:
        reasons.append(
            f"Current owner has held title {hold_years:.0f} years "
            f"(since {title['application_received']}) — long hold, aging ownership"
        )

    municipality = municipality_name(title["taxation_authority"])
    mailing = (title["owner_mailing_address"] or "").upper()
    mailing_tokens = re.findall(r"[A-Z]+", mailing)
    is_absentee = bool(municipality) and municipality not in mailing
    is_out_of_province = is_absentee and bool(mailing_tokens) and "BC" not in mailing_tokens
    if is_out_of_province:
        reasons.append(
            f"Owner mailing address is out of province, property is in {municipality.title()} "
            "— absentee owner, less attached to operating the asset"
        )
    elif is_absentee:
        reasons.append(
            f"Owner mailing address is outside {municipality.title()}, where the property "
            "sits — mild absentee signal"
        )

    no_mortgage = len(mortgages) == 0
    if no_mortgage and not suppress_as_recent_transfer and title["taxation_authority"]:
        reasons.append("No mortgage currently on title — unencumbered, full equity position")

    renewal_overdue = bool(
        years_overdue is not None and years_overdue <= STALE_MORTGAGE_YEARS
    )
    mortgage_likely_stale = bool(
        years_overdue is not None and years_overdue > STALE_MORTGAGE_YEARS
    )

    priority = 0
    if distress:
        priority += 100 * len(distress)
    if notation_distress:
        priority += 90 * len(notation_distress)
    if private_mortgages:
        priority += 20 * len(private_mortgages)
    if len(mortgages) >= 2:
        priority += 10
    if renewal_overdue:
        priority += 30
    if is_out_of_province:
        priority += 15
    elif is_absentee:
        priority += 5
    if is_long_hold:
        priority += 10
    if suppress_as_recent_transfer:
        priority -= 200  # negative signal per docs/signals.md section E

    return {
        "pid": pid,
        "title_number": title["title_number"],
        "registered_owner": title["registered_owner"],
        "taxation_authority": title["taxation_authority"],
        "owner_mailing_address": title["owner_mailing_address"],
        "holding_period_years": round(hold_years, 1) if hold_years is not None else "",
        "mortgage_count": len(mortgages),
        "distress_charge_count": len(distress),
        "notation_distress_signals": "; ".join(f"{label} ({filed})" if filed else label for label, filed in notation_distress),
        "notation_distress_stale": "; ".join(f"{label} ({filed})" if filed else label for label, filed in notation_stale),
        "has_private_lender": bool(private_mortgages),
        "is_absentee": is_absentee,
        "is_out_of_province": is_out_of_province,
        "predicted_next_renewal": latest_renewal or "",
        "renewal_overdue": renewal_overdue,
        "mortgage_likely_stale": mortgage_likely_stale,
        "priority_score": priority,
        "recent_purchase_suppress": suppress_as_recent_transfer,
        "reasons": " ; ".join(reasons) if reasons else "No debt or distress charges on title",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("charges_csv", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("data/parsed/leads.csv"))
    args = ap.parse_args()

    by_pid = load_charges(args.charges_csv)
    leads = [score_pid(pid, charges) for pid, charges in by_pid.items()]
    leads.sort(key=lambda r: r["priority_score"], reverse=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(leads[0].keys()) if leads else []
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)

    print(f"Scored {len(leads)} PID(s) -> {args.out}")
    for lead in leads:
        flag = " [SUPPRESS: recent purchase]" if lead["recent_purchase_suppress"] else ""
        print(f"  {lead['priority_score']:4d}  {lead['pid']}  {lead['registered_owner'][:35]:35s}{flag}")


if __name__ == "__main__":
    main()
