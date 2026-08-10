#!/usr/bin/env python3
"""Score a Tier 1 candidate universe from free municipal open data (docs/roadmap.md Phase 2).

Unlike scripts/score_leads.py (which scores confirmed title data), this works from public
property records with no title pulled yet — no charges, no mortgage dates, no liens. Scores
here are deliberately on a lower, separate scale and every row is marked TIER1_ESTIMATE, per
the CONFIRMED/ESTIMATED distinction in docs/signals.md: this narrows where to spend a $14
title pull, it is not a substitute for one.

Input: a municipal property-detail CSV with at minimum PID, OWNER_TYPE, ZONE_DESCRIPTION,
GROSS_LAND, GROSS_IMPROVEMENTS, GROSS_ASSESSMENT, LOT_SIZE, HOUSE, STREET columns — this is
the shape City of Surrey's ArcGIS Hub "Property Detail List" dataset comes in.

    python3 scripts/score_tier1_candidates.py surrey_property_detail.csv \
        --industrial-zones "Light Impact Industrial Zone" "Highway Commercial Industrial Zone" \
        --existing-leads data/parsed/leads.csv \
        -o data/parsed/surrey_tier1_candidates.csv
"""

import argparse
import csv
import re
from pathlib import Path

UNDERBUILT_RATIO = 0.3
LARGE_LOT_SQFT = 43_560  # 1 acre

CROWN_OWNER_TYPES = {
    "City Land", "Park - City Purchased", "Transit", "CN Rail", "BC Hydro",
    "Provincial", "BC Gas", "Harbour Board", "Park - Regional",
    "Park - City Dedicated", "Metro Vancouver", "Road - City", "School",
}

LOT_SIZE_SQFT = re.compile(r"\(([\d,]+)\s*sq\.?\s*feet\)", re.I)


def parse_lot_sqft(lot_size_text: str):
    if not lot_size_text:
        return None
    m = LOT_SIZE_SQFT.search(lot_size_text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def load_existing_pids(path: Path) -> dict:
    if not path or not path.exists():
        return {}
    with open(path, newline="") as f:
        return {row["pid"]: row for row in csv.DictReader(f)}


def score_row(row: dict, existing: dict) -> dict:
    pid = row["PID"]
    land = float(row["GROSS_LAND"] or 0)
    improvements = float(row["GROSS_IMPROVEMENTS"] or 0)
    lot_sqft = parse_lot_sqft(row["LOT_SIZE"])

    reasons = []
    score = 0

    if land > 0:
        ratio = improvements / land
        if improvements == 0:
            reasons.append(
                f"Improvements assessed at $0 on ${land:,.0f} of land — vacant or fully "
                "depreciated structure on a valuable lot, classic redevelopment/land-value profile"
            )
            score += 40
        elif ratio < UNDERBUILT_RATIO:
            reasons.append(
                f"Improvements (${improvements:,.0f}) are only {ratio:.0%} of land value "
                f"(${land:,.0f}) — underbuilt for the site, may be worth more redeveloped "
                "than operated as-is"
            )
            score += 25

    if lot_sqft and lot_sqft >= LARGE_LOT_SQFT:
        reasons.append(f"Large lot ({lot_sqft:,} sq ft, ~{lot_sqft/43560:.1f} acres)")
        score += 10

    already_pulled = pid in existing
    if already_pulled:
        ex = existing[pid]
        reasons.append(
            f"Title already pulled — confirmed score {ex['priority_score']} "
            f"(owner: {ex['registered_owner']}). See the confirmed leads sheet for full detail."
        )

    return {
        "tier": "CONFIRMED (see leads sheet)" if already_pulled else "TIER1_ESTIMATE",
        "pid": pid,
        "address": f"{row['HOUSE']} {row['STREET']}".strip(),
        "zone": row["ZONE_DESCRIPTION"],
        "owner_type": row["OWNER_TYPE"],
        "lot_size_text": row["LOT_SIZE"],
        "gross_land": land,
        "gross_improvements": improvements,
        "gross_assessment": float(row["GROSS_ASSESSMENT"] or 0),
        "improvement_to_land_ratio": round(improvements / land, 3) if land > 0 else "",
        "tier1_score": score,
        "already_have_title": already_pulled,
        "reasons": " ; ".join(reasons) if reasons else "No Tier 1 signal from this dataset alone",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--industrial-zones", nargs="+", required=True,
                     help="Exact ZONE_DESCRIPTION values to treat as industrial")
    ap.add_argument("--existing-leads", type=Path, default=None,
                     help="scripts/score_leads.py output, to mark PIDs already confirmed")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    existing = load_existing_pids(args.existing_leads)
    zones = set(args.industrial_zones)

    # Some PIDs cover several legal sub-parcels — found on 10619 Timberland Rd, which
    # showed up 4 times with different land values because the source file has one row
    # per legal description (often LEASE/PERMIT/LICENCE sub-parcels of a Crown lease
    # site), not one row per PID. Group by PID first and sum assessed values, so a
    # multi-parcel site becomes one candidate with its true total value, not several
    # near-duplicate rows that look like separate opportunities.
    by_pid = {}
    with open(args.csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["ZONE_DESCRIPTION"] not in zones:
                continue
            if row["OWNER_TYPE"] in CROWN_OWNER_TYPES:
                continue
            if not row["PID"]:
                continue
            by_pid.setdefault(row["PID"], []).append(row)

    rows = []
    for pid, subrows in by_pid.items():
        if len(subrows) == 1:
            rows.append(score_row(subrows[0], existing))
            continue
        merged = dict(subrows[0])
        merged["GROSS_LAND"] = str(sum(float(r["GROSS_LAND"] or 0) for r in subrows))
        merged["GROSS_IMPROVEMENTS"] = str(sum(float(r["GROSS_IMPROVEMENTS"] or 0) for r in subrows))
        merged["GROSS_ASSESSMENT"] = str(sum(float(r["GROSS_ASSESSMENT"] or 0) for r in subrows))
        scored = score_row(merged, existing)
        scored["reasons"] = (
            f"Multi-parcel PID ({len(subrows)} legal sub-parcels summed — often a Crown "
            f"lease site, verify before pulling title) ; " + scored["reasons"]
        )
        rows.append(scored)

    rows.sort(key=lambda r: r["tier1_score"], reverse=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    already = sum(1 for r in rows if r["already_have_title"])
    print(f"{len(rows)} private industrial parcels -> {args.out}")
    print(f"  {already} already have a title pulled (see confirmed leads)")
    print(f"  {len(rows) - already} are new Tier 1 candidates")


if __name__ == "__main__":
    main()
