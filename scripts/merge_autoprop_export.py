#!/usr/bin/env python3
"""Merge an AutoProp property export into the Tier 1 candidate scoring.

AutoProp (a paid BC property research tool) gives what free municipal open data can't:
title number, partial owner name, and real sale/transaction history per PID. This is the
sale-date signal Phase 1/2 flagged as unavailable in bulk for free — it isn't free here
either (AutoProp is a subscription), but if the user already has access, it's worth folding
in rather than re-deriving from public data.

    python3 scripts/merge_autoprop_export.py autoprop_export.xlsx \
        --tier1-csv data/parsed/surrey_tier1_candidates_with_business.csv \
        -o data/parsed/surrey_top50_enriched.csv

AutoProp sheet columns expected: PID, Civic Address, Municipality, Zone Code,
Zone Description, Registered Owner, Title Number, Address, Lot Size, Gross Taxes,
Sales History, Year Constructed, 2026 Assessed Land Value, 2026 Assessed Improvement
Value, 2026 Assessed Total Value, Legal Description.
"""

import argparse
import csv
import re
from datetime import date
from pathlib import Path

import openpyxl

TODAY = date.today()

SALE_ENTRY = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})\s+\$([\d,]+)\s+Type:\s*([^;]+)"
)

# Sale records AutoProp/BC Assessment marks as not a genuine arm's-length transaction —
# internal reorganizations, nominal transfers, etc. Don't treat these as a real
# ownership-change date; they'd produce false "recent purchase" signals.
NON_ARMS_LENGTH = "REJECT - NOT SUITABLE FOR SALES ANALYSIS"


def parse_sales_history(text: str):
    """Return list of dicts, most recent first, as AutoProp orders them."""
    if not text or text == "-":
        return []
    return [
        {
            "date": date(int(y), int(mo), int(d)),
            "price": int(price.replace(",", "")),
            "type": type_.strip(),
        }
        for d, mo, y, price, type_ in SALE_ENTRY.findall(text)
    ]


def load_autoprop_xlsx(path: Path) -> list:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    headers = [c.value for c in ws[1]]
    return [dict(zip(headers, r)) for r in ws.iter_rows(min_row=2, values_only=True)]


def load_autoprop_csv(path: Path) -> list:
    # AutoProp's CSV export repeats the "Municipality" column and includes a BOM;
    # utf-8-sig strips the BOM, and DictReader keeps the last value for a repeated
    # header, which is fine here since both copies hold the same value.
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_autoprop(paths: list) -> dict:
    by_pid = {}
    for path in paths:
        records = load_autoprop_csv(path) if path.suffix.lower() == ".csv" else load_autoprop_xlsx(path)
        for rec in records:
            pid = rec.get("PID")
            if not pid:
                continue
            by_pid.setdefault(pid, []).append(rec)
    return by_pid


def pick_primary(records: list) -> dict:
    """Multiple civic addresses can share one PID (legal sub-parcels). Prefer the
    record that actually carries a Title Number — that's the one AutoProp resolved
    to a real registered title, not a partial/placeholder row."""
    with_title = [r for r in records if r.get("Title Number")]
    return with_title[0] if with_title else records[0]


def num(v):
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return None


def summarize_sale(sales: list) -> dict:
    if not sales:
        return {"most_recent_sale_date": "", "most_recent_sale_price": "",
                "most_recent_sale_type": "", "sale_is_arms_length": "",
                "years_since_sale": ""}
    most_recent = sales[0]
    is_al = most_recent["type"] != NON_ARMS_LENGTH
    years = (TODAY - most_recent["date"]).days / 365.25
    return {
        "most_recent_sale_date": most_recent["date"].isoformat(),
        "most_recent_sale_price": most_recent["price"],
        "most_recent_sale_type": most_recent["type"],
        "sale_is_arms_length": is_al,
        "years_since_sale": round(years, 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("autoprop_files", type=Path, nargs="+",
                     help="One or more AutoProp exports (.xlsx or .csv) to merge together")
    ap.add_argument("--tier1-csv", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    autoprop = load_autoprop(args.autoprop_files)

    with open(args.tier1_csv) as f:
        tier1 = {r["pid"]: r for r in csv.DictReader(f)}

    out_rows = []
    for pid, records in autoprop.items():
        primary = pick_primary(records)
        sales = parse_sales_history(primary.get("Sales History"))
        sale_info = summarize_sale(sales)

        t1 = tier1.get(pid, {})

        land = num(primary.get("2026 Assessed Land Value"))
        improve = num(primary.get("2026 Assessed Improvement Value"))

        reasons = []
        if land and improve is not None:
            if improve == 0:
                reasons.append(f"2026 assessment: ${land:,.0f} land, $0 improvements")
            elif land:
                ratio = improve / land
                if ratio < 0.3:
                    reasons.append(f"2026 assessment: improvements only {ratio:.0%} of land value")

        if sale_info["most_recent_sale_date"]:
            yrs = sale_info["years_since_sale"]
            if sale_info["sale_is_arms_length"]:
                if yrs < 3:
                    reasons.append(
                        f"Sold {sale_info['most_recent_sale_date']} (${sale_info['most_recent_sale_price']:,}) "
                        f"— {yrs:.1f} years ago, recent arm's-length purchase, likely not a near-term seller"
                    )
                elif yrs >= 20:
                    reasons.append(
                        f"Last arm's-length sale {sale_info['most_recent_sale_date']} "
                        f"({yrs:.0f} years ago) — long hold, aging ownership"
                    )
                else:
                    reasons.append(
                        f"Last arm's-length sale {sale_info['most_recent_sale_date']} "
                        f"({yrs:.1f} years ago, ${sale_info['most_recent_sale_price']:,})"
                    )
            else:
                reasons.append(
                    f"Most recent record ({sale_info['most_recent_sale_date']}) is marked "
                    f"'{sale_info['most_recent_sale_type']}' — not a real arm's-length sale "
                    "(internal transfer/reorg), doesn't reset ownership-recency read"
                )
        else:
            reasons.append("No sale history on file — likely a very long hold")

        if t1.get("known_businesses"):
            reasons.append(f"Business licence on file: {t1['known_businesses']}")

        out_rows.append({
            "pid": pid,
            "civic_address": primary.get("Civic Address"),
            "title_number": primary.get("Title Number") or "",
            "owner_initials": primary.get("Registered Owner") or "",
            "zone_code": primary.get("Zone Code"),
            "assessed_land_2026": land or "",
            "assessed_improvement_2026": improve or "",
            "assessed_total_2026": num(primary.get("2026 Assessed Total Value")) or "",
            "year_constructed": primary.get("Year Constructed") or "",
            **sale_info,
            "known_businesses": t1.get("known_businesses", ""),
            "single_tenant": t1.get("likely_owner_occupied_single_tenant", ""),
            "tier1_score_prior": t1.get("tier1_score", ""),
            "reasons": " ; ".join(reasons),
        })

    fieldnames = list(out_rows[0].keys()) if out_rows else []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print(f"{len(out_rows)} unique PIDs merged -> {args.out}")


if __name__ == "__main__":
    main()
