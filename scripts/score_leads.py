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
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

TODAY = date.today()

PRIVATE_LENDER_TYPES = {"mic_private", "numbered_co_private"}
DISTRESS_TYPES = {"CERTIFICATE OF PENDING LITIGATION", "JUDGMENT", "BUILDERS LIEN"}

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

    is_recent_transfer = bool(title["declared_value"])
    if is_recent_transfer:
        reasons.append(
            f"Declared value ${title['declared_value']} present — likely a recent purchase, "
            "suppress as a near-term seller candidate"
        )

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
    if is_recent_transfer:
        priority -= 200  # negative signal per docs/signals.md section E

    return {
        "pid": pid,
        "title_number": title["title_number"],
        "registered_owner": title["registered_owner"],
        "taxation_authority": title["taxation_authority"],
        "mortgage_count": len(mortgages),
        "distress_charge_count": len(distress),
        "has_private_lender": bool(private_mortgages),
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
