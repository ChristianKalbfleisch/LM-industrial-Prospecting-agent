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

# A title's Application Received date is when the *current* owner's title was
# registered — i.e. how long they've held it. Declared Value looked like a recent-
# purchase flag on the first sample batch (both titles that had it were recent), but
# a second batch showed titles from 1999 and 2004 that still carry a Declared Value
# decades later — it's whatever was declared when that title's application was
# filed, not a signal of recency on its own. application_received is the correct
# proxy; keep declared_value only as descriptive context.
RECENT_TRANSFER_YEARS = 3
LONG_HOLD_YEARS = 20


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

    reasons = []
    latest_renewal = None
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
        if latest_renewal and datetime.fromisoformat(latest_renewal).date() < TODAY:
            reasons.append(
                "Predicted renewal date has already passed with no newer mortgage on "
                "title — either a quiet renewal/extension the lender didn't re-register, "
                "or the owner is past due and now on a higher floating rate. Worth a call "
                "regardless, and a candidate for a fresh title pull to check for a discharge "
                "or refinance we don't have on file."
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

    hold_years = holding_period_years(title["application_received"])
    is_recent_transfer = hold_years is not None and hold_years < RECENT_TRANSFER_YEARS
    is_long_hold = hold_years is not None and hold_years >= LONG_HOLD_YEARS
    if is_recent_transfer:
        reasons.append(
            f"Title registered to current owner {hold_years:.1f} years ago "
            f"({title['application_received']}) — recent purchase, suppress as a "
            "near-term seller candidate"
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
    if no_mortgage and not is_recent_transfer and title["taxation_authority"]:
        reasons.append("No mortgage currently on title — unencumbered, full equity position")

    renewal_overdue = bool(
        latest_renewal and datetime.fromisoformat(latest_renewal).date() < TODAY
    )

    priority = 0
    if distress:
        priority += 100 * len(distress)
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
    if is_recent_transfer:
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
        "has_private_lender": bool(private_mortgages),
        "is_absentee": is_absentee,
        "is_out_of_province": is_out_of_province,
        "predicted_next_renewal": latest_renewal or "",
        "renewal_overdue": renewal_overdue,
        "priority_score": priority,
        "recent_purchase_suppress": is_recent_transfer,
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
