#!/usr/bin/env python3
"""Turn a comparable-sales export into a mortgage-renewal watchlist.

Premise (the broker's, and it holds up): a property bought in 2021-23 was almost
certainly financed at the same time, so purchase date + term = a predicted renewal date.
Deals financed in the 2021 / early-2022 low-rate window renew into a materially different
rate environment, which is the clearest dated motivation signal available.

    python3 scripts/build_renewal_watchlist.py comps.xlsx -o output/renewal_watchlist.xlsx

Renewal date is an ESTIMATE unless the export carried a real maturity date — the two are
kept in separate columns and never blended, because one is evidence and one is arithmetic.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).parent))
from parse_titles import classify_lender  # noqa: E402
from score_leads import ASSUMED_TERM_YEARS  # noqa: E402
from address_key import address_key  # noqa: E402

TODAY = date.today()
FONT = "Arial"

# The Bank of Canada policy rate sat at 0.25% until March 2022, then rose through that
# year. Money borrowed before the hikes renews into a different world than money borrowed
# after them. Deliberately expressed as a vintage label, not a rate spread — quoting a
# specific renewal rate would be inventing precision this data does not contain.
def rate_vintage(d: date) -> str:
    if d < date(2022, 3, 1):
        return "Pre-hike (cheapest money)"
    if d < date(2022, 9, 1):
        return "Mid-hike"
    return "Post-hike"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comps_xlsx", type=Path)
    ap.add_argument("--autoprop", type=Path, default=None,
                    help="merge_autoprop_export.py output, to catch comps that have since resold")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    # A comps record is a snapshot of one transaction. If the property has traded AGAIN
    # since, the renewal thesis is dead for it — there is a new owner on new financing.
    # Without this check the top-ranked lead on the first build was a property that had
    # already resold four months earlier.
    resold = {}
    if args.autoprop and args.autoprop.exists():
        import csv as _csv
        for r in _csv.DictReader(open(args.autoprop)):
            d = r.get("most_recent_sale_date")
            if not d:
                continue
            y, m, dd = (int(x) for x in d.split("-"))
            resold.setdefault(address_key(r.get("civic_address")), []).append(
                (date(y, m, dd), r.get("most_recent_sale_type", "")))

    wb_in = openpyxl.load_workbook(args.comps_xlsx, data_only=True)
    ws_in = wb_in.active
    hdr = [c.value for c in ws_in[1]]
    src = [dict(zip(hdr, r)) for r in ws_in.iter_rows(min_row=2, values_only=True) if any(r)]

    recs = []
    for r in src:
        td = r.get("Transaction date")
        if not td:
            continue
        td = td.date() if hasattr(td, "date") else td
        lender = r.get("First mortgage lender") or ""
        lclass = classify_lender(lender) if lender else ""
        term = ASSUMED_TERM_YEARS.get(lclass, 5)

        real_maturity = r.get("First mortgage maturity date")
        real_maturity = real_maturity.date() if hasattr(real_maturity, "date") else real_maturity

        est_renewal = td + timedelta(days=int(term * 365.25))
        effective = real_maturity or est_renewal
        months_out = (effective - TODAY).days / 30.44

        price = r.get("Price") or 0
        mortgage = r.get("First mortgage amount") or 0
        ltv = (mortgage / price) if (price and mortgage) else None

        reasons = []
        if real_maturity:
            reasons.append(f"CONFIRMED maturity {real_maturity} (from the export, not estimated)")
        else:
            reasons.append(f"Estimated: bought {td} + {term}yr assumed term for {lclass or 'unknown lender'}")

        if -6 <= months_out <= 18:
            reasons.append("Renewal falls inside the 6-18 month action window")
        elif months_out < -6:
            reasons.append(f"Renewal window passed ~{abs(months_out)/12:.1f} yrs ago — may already have renewed or refinanced")

        vintage = rate_vintage(td)
        if vintage == "Pre-hike (cheapest money)":
            reasons.append("Financed before the 2022 rate hikes — largest payment step-up on renewal")

        if ltv:
            if ltv > 1.0:
                reasons.append(f"Mortgage EXCEEDS purchase price ({ltv*100:.0f}%) — cross-collateralized or includes build-out; highly rate-sensitive")
            elif ltv >= 0.8:
                reasons.append(f"High leverage ({ltv*100:.0f}% of price) — little equity cushion at renewal")

        # supersede check
        later = [(d, t) for d, t in resold.get(address_key(r.get("Address")), []) if d > td]
        superseded = max(later)[0] if later else None
        if superseded:
            reasons.insert(0, f"SUPERSEDED — resold {superseded}, after this transaction. "
                              "New owner on new financing; the renewal thesis no longer applies.")

        score = 0
        if -6 <= months_out <= 18:
            score += 50
        elif 18 < months_out <= 30:
            score += 25
        if vintage == "Pre-hike (cheapest money)":
            score += 25
        elif vintage == "Mid-hike":
            score += 10
        if ltv and ltv > 1.0:
            score += 25
        elif ltv and ltv >= 0.8:
            score += 15
        if real_maturity:
            score += 10  # evidence beats estimate

        if superseded:
            score = -100  # drop below everything rather than silently rank a dead lead

        recs.append({
            "score": score,
            "superseded_by_resale": superseded.isoformat() if superseded else "",
            "address": r.get("Address"),
            "municipality": r.get("Municipality"),
            "purchase_date": td,
            "price": price,
            "psf": r.get("Price/sq.ft."),
            "building_sf": r.get("Building size (sq.ft.)"),
            "year_built": r.get("Construction year"),
            "purchaser": r.get("First purchaser"),
            "vendor": r.get("First vendor"),
            "signing_officer": r.get("Purchaser signing officer"),
            "officer_position": r.get("Purchaser signing officer position"),
            "lender": lender,
            "lender_class": lclass,
            "mortgage_amt": mortgage or None,
            "ltv": round(ltv, 3) if ltv else None,
            "assumed_term": term if not real_maturity else "",
            "confirmed_maturity": real_maturity.isoformat() if real_maturity else "",
            "estimated_renewal": "" if real_maturity else est_renewal.isoformat(),
            "months_to_renewal": round(months_out, 1),
            "rate_vintage": vintage,
            "reasons": " ; ".join(reasons),
        })

    recs.sort(key=lambda x: (-x["score"], abs(x["months_to_renewal"])))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Renewal Watchlist"
    headers = ["Score", "Resold Since?", "Address", "City", "Purchased", "Price", "$/SF", "Bldg SF", "Built",
               "Purchaser", "Signing Officer", "Position", "Vendor",
               "Lender", "Lender Class", "Mortgage $", "LTV",
               "CONFIRMED Maturity", "Estimated Renewal", "Assumed Term (yr)",
               "Months to Renewal", "Rate Vintage", "Why"]
    ws.append(headers)
    for r in recs:
        ws.append([
            r["score"], r["superseded_by_resale"], r["address"], r["municipality"], r["purchase_date"], r["price"],
            r["psf"], r["building_sf"], r["year_built"], r["purchaser"],
            r["signing_officer"], r["officer_position"], r["vendor"],
            r["lender"], r["lender_class"], r["mortgage_amt"], r["ltv"],
            r["confirmed_maturity"], r["estimated_renewal"], r["assumed_term"],
            r["months_to_renewal"], r["rate_vintage"], r["reasons"],
        ])

    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for i, c in enumerate(ws[1], start=1):
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill(start_color="2E7D32" if i == 18 else "1F4E78",
                             end_color="2E7D32" if i == 18 else "1F4E78", fill_type="solid")
        c.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        c.border = border

    hot = PatternFill(start_color="C6E7C6", end_color="C6E7C6", fill_type="solid")
    warm = PatternFill(start_color="E2F0D9", end_color="E2F0D9", fill_type="solid")
    confirmed = PatternFill(start_color="B7E1CD", end_color="B7E1CD", fill_type="solid")

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.font = Font(name=FONT, size=10)
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=(c.column_letter in ("C", "J", "M", "N", "W")))
        s = row[0].value
        if row[1].value:
            for c in row:
                c.fill = PatternFill(start_color="F8CBCB", end_color="F8CBCB", fill_type="solid")
        elif s >= 90:
            for c in row:
                c.fill = hot
        elif s >= 60:
            for c in row:
                c.fill = warm
        if row[17].value:
            row[17].fill = confirmed
        row[4].number_format = "yyyy-mm-dd"
        for i in (5, 15):
            row[i].number_format = '$#,##0'
        row[6].number_format = '$#,##0'
        row[16].number_format = '0%'

    widths = [7, 14, 28, 11, 12, 14, 8, 10, 8, 26, 22, 10, 26, 30, 18, 14, 8, 17, 16, 12, 12, 22, 74]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions

    # --- notes ---
    n = Font(name=FONT, size=10)
    nw = wb.create_sheet("Notes & What To Pull Next")
    nw["A1"] = "Renewal Watchlist — built from your 2021-23 comparable sales"
    nw["A1"].font = Font(name=FONT, bold=True, size=13)

    in_window = [r for r in recs if -6 <= r["months_to_renewal"] <= 18]
    prehike = [r for r in recs if r["rate_vintage"].startswith("Pre-hike")]
    confirmed_n = [r for r in recs if r["confirmed_maturity"]]
    highltv = [r for r in recs if r["ltv"] and r["ltv"] >= 0.8]

    lines = [
        "",
        f"{len(recs)} transactions. {len(in_window)} have a renewal falling inside the 6-18 month",
        f"action window. {len(prehike)} were financed before the March 2022 rate hikes.",
        f"{len(confirmed_n)} carry a CONFIRMED maturity date (green column) — the rest are estimated.",
        f"{len(highltv)} carry 80%+ leverage against purchase price.",
        "",
        "YOUR PREMISE CHECKS OUT, WITH ONE REFINEMENT:",
        "Choosing 2021-23 on a 5-year term was the right instinct. Working it through:",
        "  2021 purchases -> renew ~2026 (happening now)",
        "  2022 purchases -> renew ~2027 (6-18 months out — the action window)",
        "  2023 purchases -> renew ~2028 (still early to call)",
        "The 2022 cohort is the bullseye, and it is where most of this file sits. The refinement:",
        "the rate STEP-UP matters more than the renewal itself. A deal financed before March 2022",
        "(policy rate 0.25%) renews into a very different payment than one financed in late 2023",
        "after the hikes — even though both are 'a renewal'. That's the Rate Vintage column.",
        "",
        "CONFIRMED vs ESTIMATED is kept in two separate columns on purpose. A real maturity date",
        "is evidence; purchase date plus an assumed term is arithmetic. Blending them into one",
        "column would hide which rows you can actually trust.",
        "",
        "=== WHAT TO PULL NEXT, IN ORDER OF VALUE ===",
        "",
        "1. MORTGAGE MATURITY DATE — by far the highest value field.",
        "   Only 7 of 55 records here carried it. It removes the term assumption entirely, which",
        "   is the single largest source of error in this whole model. If your comps provider can",
        "   export it more completely, or if it can be requested, ask for that field specifically.",
        "",
        "2. EARLIER VINTAGES: 2019-2021 sales.",
        "   You picked 2021-23, which finds renewals landing 2026-28. But 2019-20 purchases on",
        "   5-year terms already renewed in 2024-25 — those owners have ALREADY absorbed the",
        "   payment shock and have been living with it. That is arguably a warmer lead than",
        "   someone facing a renewal they haven't felt yet. Worth pulling as a second cohort.",
        "",
        "3. MORTGAGE AMOUNT on every record (you have it on 31 of 55).",
        "   Combined with price it gives LTV, and leverage is what turns a renewal into pressure.",
        "   The 8 records here where the mortgage EXCEEDS the purchase price are the most",
        "   rate-sensitive owners in the file.",
        "",
        "4. INTEREST RATE and RATE TYPE (fixed/floating) if the provider carries them.",
        "   A floating-rate borrower already felt every hike; a fixed borrower feels it all at once",
        "   on renewal. Completely different conversations, and different timing.",
        "",
        "5. CAP RATE — zero of 55 records had it populated.",
        "   Useful for sizing the deal and for the conversation itself, less so for timing.",
        "",
        "6. VENDOR/PURCHASER ENTITY across a wider date range.",
        "   Repeat entity names reveal portfolio owners — one conversation covering several assets.",
        "",
        "7. A SMALL SET OF KNOWN OUTCOMES.",
        "   Still the biggest gap in this whole project. If you can mark even 10-20 past leads as",
        "   'called / listed / closed / went nowhere', the scoring stops being a reasoned guess and",
        "   starts being measured. Nothing else on this list improves accuracy as much.",
        "",
        "=== ONE FINDING THAT CUTS AGAINST THE RENEWAL THESIS ===",
        "36 of the 44 mortgages in this file are recorded as 'Subsequent - Demand Debenture',",
        "not conventional fixed-term mortgages. A demand debenture is payable on demand and has",
        "no clean renewal date, so the 5-year renewal clock may apply to less of this market than",
        "assumed. You will know better than I do whether that is typical for industrial here — but",
        "if it is, distress signals (liens, CPLs, judgments) deserve more weight than renewal timing,",
        "and this is worth testing before leaning too hard on renewal dates alone.",
        "",
        "Also unused so far: every record carries a named purchaser signing officer and position.",
        "Those are real names from a transaction record, not directory guesses — the best contact",
        "data anywhere in this project so far.",
    ]
    for i, l in enumerate(lines, start=2):
        nw[f"A{i}"] = l
        nw[f"A{i}"].font = n
    nw.column_dimensions["A"].width = 100

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)
    print(f"{len(recs)} transactions -> {args.out}")
    print(f"  in 6-18mo window: {len(in_window)} | pre-hike: {len(prehike)} | confirmed maturity: {len(confirmed_n)}")


if __name__ == "__main__":
    main()
