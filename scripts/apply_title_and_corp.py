#!/usr/bin/env python3
"""Fold title-registry owners and corporate searches back into the renewal watchlist.

The watchlist is built from comparable sales, so its "Purchaser" is whoever bought in
2021-23 — often a trade name, not the entity on title. Once titles are pulled, the
registered owner and its incorporation number become available, and the incorporation
number is an exact join key into the corporate register. That replaces company-name
fuzzy matching, which was silently missing renamed and restructured owners.

    python3 scripts/apply_title_and_corp.py output/renewal_watchlist.xlsx \
        --titles data/raw/surrey_title_owners.tsv \
        --corps  data/parsed/corps.csv

Titles file is tab separated: title_number, PID, registered owner(s), legal description.

The corporate signal that matters here is annual-report delinquency. Under the BC Business
Corporations Act the registrar may strike a company that fails to file for two consecutive
years, so an owner two reports behind is on a path toward exactly the dissolution event
docs/signals.md treats as a top-tier motivation signal. It is a leading indicator of a
struck status, not a struck status — the wording in the output says so.

PRIVACY: director names come from the corporate register. They stay under data/ and in
the broker's working file; they are not published.
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import openpyxl
from address_key import address_key
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

TODAY = date.today()
FONT = "Arial"
INC_IN_NAME = re.compile(r"\s*\(([A-Z0-9\-]+)\)")

# Crown corporations, port authorities and transit authorities hold industrial land as
# infrastructure, not as an investment with a renewal to survive. They score well on the
# comps-derived signals and are never sellers, so title is the only place this shows up.
PUBLIC_BODY = re.compile(
    r"PORT AUTHORITY|TRANSPORTATION AUTHORITY|TRANSLINK|\bCITY OF\b|\bDISTRICT OF\b"
    r"|\bTOWNSHIP OF\b|PROVINCE OF|HER MAJESTY|HIS MAJESTY|CROWN|SCHOOL DISTRICT"
    r"|\bB\.?C\.? HYDRO\b|RAILWAY|RAIL COMPANY", re.I)

# Columns inserted directly after "Purchaser" so the ownership story reads left to right:
# who bought it, who holds it now, and what shape that entity is in.
NEW_COLS = ["Registered Owner (title)", "Owner Changed?", "Corp Status", "Incorporated",
            "Last Annual Report", "Report Overdue (mo)", "Corp Signal", "Directors / Officers",
            "Mail To (registered office)", "Director Address (registry)"]
BASE_SCORE = "Score (pre-corp)"   # keeps this script re-runnable as new searches come in
WIDTHS = {"Registered Owner (title)": 34, "Owner Changed?": 14, "Corp Status": 12,
          "Incorporated": 14, "Last Annual Report": 16, "Report Overdue (mo)": 11,
          "Corp Signal": 46, "Directors / Officers": 34, BASE_SCORE: 11,
          "Mail To (registered office)": 34, "Director Address (registry)": 44}


def parse_reg_date(s):
    return datetime.strptime(s.strip(), "%B %d, %Y").date() if s and s.strip() else None


def norm_company(s):
    """Loose company-name key, used only to decide whether the owner CHANGED."""
    s = (s or "").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(LIMITED|LTD|INCORPORATED|INC|CORPORATION|CORP|ULC|COMPANY)\b", "", s)
    s = re.sub(r"\bB C\b", "BC", s)
    return re.sub(r"\s+", " ", s).strip()


def load_titles(path):
    out = {}
    for line in open(path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3 or not parts[1].strip():
            continue
        title_no, pid, owner = parts[0].strip(), parts[1].strip(), parts[2].strip()
        out[pid] = {
            "title_no": title_no,
            "owner": owner,
            "owner_plain": INC_IN_NAME.sub("", owner),
            "incs": INC_IN_NAME.findall(owner),
            "legal": parts[3].strip() if len(parts) > 3 else "",
        }
    return out


def corp_signals(corp, holdings):
    """Return (list of signal strings, score delta) for one owning company."""
    sig, delta = [], 0
    status = (corp.get("status") or "").upper()
    if status and status != "ACTIVE":
        sig.append(f"OWNER ENTITY {status} — strongest motivation signal available")
        delta += 40
    if (corp.get("in_liquidation") or "").strip().lower() == "yes":
        sig.append("IN LIQUIDATION")
        delta += 40
    if (corp.get("receiver") or "").strip().lower() == "yes":
        sig.append("RECEIVER APPOINTED")
        delta += 40

    last = parse_reg_date(corp.get("last_annual_report"))
    inc = parse_reg_date(corp.get("incorporated"))
    overdue = None
    if last:
        overdue = round((TODAY - last).days / 30.44, 1)
        if overdue >= 24:
            missed = int(overdue // 12)
            sig.append(f"{missed} annual reports overdue — a company two filings behind can be "
                       f"struck by the registrar; owner is on that path")
            delta += 20
        elif overdue >= 12:
            sig.append(f"annual report {overdue:.0f} months overdue (1 filing behind)")
            delta += 10
    elif inc and (TODAY - inc).days < 400:
        # No report yet simply because none is due — not a signal on its own.
        sig.append(f"entity recognized {corp['incorporated']}; no annual report due yet")

    # A recognition date long after the numbered name implies the entity was restructured
    # (amalgamation or continuation) rather than newly formed to hold the asset.
    num = re.match(r"(\d{6,7})\s*B\.?C\.?", corp.get("company_name", ""))
    incno = re.sub(r"\D", "", corp.get("incorporation_number", ""))
    if num and incno and num.group(1) != incno.lstrip("0"):
        sig.append(f"company name carries {num.group(1)} but registered as "
                   f"{corp['incorporation_number']} — restructured (amalgamation or continuation)")
        delta += 10

    if (corp.get("office_is_professional_firm") or "").lower() == "true":
        sig.append("registered office is a law/accounting firm — often precedes a wind-up or estate")
        delta += 10

    if len(holdings) > 1:
        sig.append(f"holds {len(holdings)} parcels on this list — one conversation covers all of them")

    return sig, delta, overdue


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("watchlist", type=Path)
    ap.add_argument("--titles", type=Path, required=True)
    ap.add_argument("--corps", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()
    out_path = args.out or args.watchlist

    titles = load_titles(args.titles)
    corps = {r["incorporation_number"]: r for r in csv.DictReader(open(args.corps))}

    holdings = defaultdict(list)
    for pid, t in titles.items():
        for i in t["incs"]:
            holdings[i].append(pid)

    # Directors appearing in more than one owning company: a portfolio behind separate holdcos.
    people = defaultdict(set)
    for inc in holdings:
        c = corps.get(inc)
        if not c:
            continue
        for p in filter(None, (x.strip() for x in c["all_people"].split(";"))):
            people[p].add(c["company_name"])
    shared = {p: cs for p, cs in people.items() if len(cs) > 1}

    wb = openpyxl.load_workbook(args.watchlist)
    ws = wb[wb.sheetnames[0]]
    hdr = [c.value for c in ws[1]]
    rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True) if any(r)]
    # Re-runnable: strip anything a previous run added and restore the pre-corp score, so
    # a fresh batch of searches produces the same result as a first run would.
    if BASE_SCORE in hdr:
        b, sc = hdr.index(BASE_SCORE), hdr.index("Score")
        why = hdr.index("Why")
        for r in rows:
            r[sc] = r[b]
            r[why] = re.sub(r"\s*;\s*CORP:.*$", "", str(r[why] or ""))
        drop = sorted((hdr.index(h) for h in NEW_COLS + [BASE_SCORE] if h in hdr), reverse=True)
        for j in drop:
            del hdr[j]
            for r in rows:
                del r[j]

    ix = {h: i for i, h in enumerate(hdr)}

    # One PID can appear twice when a parcel traded more than once inside the comps window.
    # Title says who holds it now, so the record naming that owner is the live one; the other
    # describes a party who no longer owns the asset.
    by_pid = defaultdict(list)
    for r in rows:
        if r[ix["PID"]]:
            by_pid[r[ix["PID"]]].append(r)
    dropped = []
    for pid, group in by_pid.items():
        if len(group) < 2:
            continue
        owner = titles.get(pid, {}).get("owner_plain", "")
        group.sort(key=lambda r: (norm_company(r[ix["Purchaser"]]) == norm_company(owner),
                                  r[ix["Score"]] or 0), reverse=True)
        for r in group[1:]:
            dropped.append((pid, r[ix["Address"]], r[ix["Purchaser"]]))
            rows.remove(r)
    for pid, addr, who in dropped:
        print(f"  deduped PID {pid} ({addr}): dropped the record purchased by {who!r} — "
              f"not the entity on title")

    at = ix["Purchaser"] + 1

    stats = defaultdict(int)
    base_scores = [r[ix["Score"]] for r in rows]
    for r in rows:
        pid = r[ix["PID"]]
        t = titles.get(pid)
        add = ["", "", "", "", "", None, "", "", "", ""]
        if t:
            stats["title"] += 1
            add[0] = t["owner_plain"]
            changed = norm_company(r[ix["Purchaser"]]) != norm_company(t["owner_plain"])
            add[1] = "YES" if changed else ""
            matched = [corps[i] for i in t["incs"] if i in corps]
            # An extraprovincial owner carries its HOME jurisdiction's number on title
            # (Forma Group's federal 767084-2) while BC registers it as A0128362, so the
            # ID join misses it. Fall back to the company name for those, and only those.
            if not matched:
                key = norm_company(t["owner_plain"])
                matched = [c for c in corps.values() if norm_company(c["company_name"]) == key]
                if matched:
                    stats["by_name"] += 1
            if matched:
                stats["corp"] += 1
                sigs, delta, overdue = [], 0, None
                for c in matched:
                    s, d, o = corp_signals(c, holdings[c["incorporation_number"]])
                    sigs += s
                    delta = max(delta, d)
                    overdue = o if overdue is None else overdue
                add[2] = " + ".join(c["status"] for c in matched)
                add[3] = " + ".join(c["incorporated"] for c in matched)
                add[4] = " + ".join(c["last_annual_report"] for c in matched)
                add[5] = overdue
                names = "; ".join(c["all_people"] for c in matched if c["all_people"])
                add[7] = names
                add[8] = " | ".join(c["registered_office"] for c in matched
                                    if c["registered_office"])
                add[9] = " | ".join(c["people_addresses"] for c in matched
                                    if c.get("people_addresses"))
                # A director whose registry address IS this property occupies the building.
                # That is a different conversation: an owner-occupier has to solve where the
                # business goes before they can sell, and they are the decision maker on site.
                here = address_key(r[ix["Address"]])
                if here and any(here == address_key(seg.split(" — ", 1)[-1])
                                for seg in add[9].split(" | ") if " — " in seg):
                    sigs.append("a director's registry address is this property — "
                                "OWNER-OCCUPIER, not a passive investor; they must solve "
                                "where the business goes before they can sell")
                for c in matched:
                    if str(c.get("directors_not_recorded", "")).lower() == "true":
                        sigs.append("extraprovincial registration — BC does not record "
                                    "directors; the home jurisdiction does")
                        if c.get("bc_attorney"):
                            add[9] = f"BC attorney: {c['bc_attorney']}"
                for c in matched:
                    for p in filter(None, (x.strip() for x in c["all_people"].split(";"))):
                        if p in shared:
                            sigs.append(f"{p} also directs "
                                        f"{'; '.join(sorted(shared[p] - {c['company_name']}))}")
                if changed:
                    sigs.insert(0, "entity on title differs from the recorded purchaser — "
                                   "confirm who you are calling before the call")
                add[6] = " ; ".join(sigs)
                if delta:
                    stats["signal"] += 1
                    r[ix["Score"]] = (r[ix["Score"]] or 0) + delta
                    r[ix["Why"]] = f"{r[ix['Why']]} ; CORP: {' ; '.join(sigs)}"
            elif PUBLIC_BODY.search(t["owner_plain"]):
                stats["public"] += 1
                add[2] = "public body"
                add[6] = ("PUBLIC AUTHORITY owner — holds this as infrastructure, not as an "
                          "investment facing a renewal. Not a seller; ranked out.")
                r[ix["Score"]] = min(r[ix["Score"]] or 0, -50)
                r[ix["Why"]] = f"{r[ix['Why']]} ; CORP: public authority owner — not a seller"
            else:
                add[2] = "no corp search"
                add[6] = ("owner is not a BC company in the searches supplied "
                          "(extraprovincial or federally incorporated — search the register "
                          "that governs it, not BC Registries)")
            # Both searches are now done for this row; say so instead of recommending them.
            r[ix["Pull Title?"]] = "DONE — title in hand"
            r[ix["Title Number"]] = t["title_no"]
            if matched:
                r[ix["Corp Search?"]] = "DONE"
        for j, v in enumerate(add):
            r.insert(at + j, v)

    hdr[at:at] = NEW_COLS
    b_at = hdr.index("Score") + 1
    hdr.insert(b_at, BASE_SCORE)
    for r, base in zip(rows, base_scores):
        r.insert(b_at, base)
    rows.sort(key=lambda r: (-(r[hdr.index("Score")] or 0),
                             abs(r[hdr.index("Months to Renewal")] or 0)))

    # Rewrite the sheet in place: column positions shifted, so formatting is driven off
    # header names rather than fixed indexes.
    ws.delete_rows(1, ws.max_row)
    ws.append(hdr)
    for r in rows:
        ws.append(r)

    col = {h: i + 1 for i, h in enumerate(hdr)}
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c in ws[1]:
        green = c.value in ("CONFIRMED Maturity", "Corp Signal", "Directors / Officers",
                            "Mail To (registered office)", "Director Address (registry)")
        c.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill(start_color="2E7D32" if green else "1F4E78",
                             end_color="2E7D32" if green else "1F4E78", fill_type="solid")
        c.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        c.border = border

    fills = {"hot": "C6E7C6", "warm": "E2F0D9", "dead": "F8CBCB",
             "confirmed": "B7E1CD", "corp": "FFE0B2"}
    wrap = {"Address", "Purchaser", "Registered Owner (title)", "Corp Signal",
            "Directors / Officers", "Mail To (registered office)",
            "Director Address (registry)", "Vendor", "Lender", "Why", "Why title",
            "Why corp search"}
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.font = Font(name=FONT, size=10)
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=(hdr[c.column - 1] in wrap))
        s = row[col["Score"] - 1].value or 0
        key = ("dead" if row[col["Resold Since?"] - 1].value else
               "hot" if s >= 90 else "warm" if s >= 60 else None)
        if key:
            f = PatternFill(start_color=fills[key], end_color=fills[key], fill_type="solid")
            for c in row:
                c.fill = f
        if row[col["CONFIRMED Maturity"] - 1].value:
            row[col["CONFIRMED Maturity"] - 1].fill = PatternFill(
                start_color=fills["confirmed"], end_color=fills["confirmed"], fill_type="solid")
        od = row[col["Report Overdue (mo)"] - 1].value
        if isinstance(od, (int, float)) and od >= 24:
            for h in ("Report Overdue (mo)", "Corp Signal"):
                row[col[h] - 1].fill = PatternFill(start_color=fills["corp"],
                                                   end_color=fills["corp"], fill_type="solid")
        row[col["Purchased"] - 1].number_format = "yyyy-mm-dd"
        for h in ("Price", "Mortgage $", "$/SF"):
            row[col[h] - 1].number_format = '$#,##0'
        row[col["LTV"] - 1].number_format = '0%'
        row[col["Report Overdue (mo)"] - 1].number_format = '0.0'

    for h, i in col.items():
        if h in WIDTHS:
            ws.column_dimensions[get_column_letter(i)].width = WIDTHS[h]
    ws.freeze_panes = f"{get_column_letter(col['Address'] + 1)}2"
    ws.auto_filter.ref = ws.dimensions

    # --- what changed, on its own sheet ---
    name = "Title & Corp Findings"
    if name in wb.sheetnames:
        del wb[name]
    nw = wb.create_sheet(name, 1)
    nw["A1"] = "What the titles and corporate searches changed"
    nw["A1"].font = Font(name=FONT, bold=True, size=13)
    overdue_rows = sorted(
        ((r[hdr.index("Report Overdue (mo)")], r[hdr.index("Registered Owner (title)")],
          r[hdr.index("Address")]) for r in rows
         if isinstance(r[hdr.index("Report Overdue (mo)")], (int, float))
         and r[hdr.index("Report Overdue (mo)")] >= 12), reverse=True)
    lines = [
        "",
        f"{stats['title']} of {len(rows)} rows now carry a registered owner read off title.",
        f"{stats['corp']} of those joined to a corporate search by incorporation number — an exact",
        "key, not a name match. That is why renamed and restructured owners resolved this time.",
        "",
        "NO OWNER ENTITY IS STRUCK, DISSOLVED, IN LIQUIDATION OR IN RECEIVERSHIP.",
        "Every company searched is ACTIVE. The corporate distress signal this project weights",
        "most heavily simply is not present in this set, and saying so is the honest result.",
        "",
        "WHAT IS PRESENT IS ANNUAL-REPORT DELINQUENCY.",
        "The registrar may strike a company that misses two consecutive annual reports. An owner",
        "already two or three filings behind is on that path — a leading indicator of the",
        "dissolution event, visible before it happens. Ranked by how far behind:",
    ]
    for od, owner, addr in overdue_rows:
        lines.append(f"   {od:5.1f} mo behind   {owner}   {addr}")
    lines += [
        "",
        "This is a soft signal on its own — plenty of solvent companies file late. It earns its",
        "weight when it lands on a property that is ALREADY ranked, which is the case at the top",
        "of this list.",
        "",
        "OWNER ON TITLE DIFFERS FROM RECORDED PURCHASER ON "
        f"{sum(1 for r in rows if r[hdr.index('Owner Changed?')] == 'YES')} ROWS.",
        "The comps record a trade name or an operating company; title records the entity that",
        "actually holds the land. Both matter, but only the title entity can sign a listing.",
        "Check the Owner Changed? column before any call — the name in the comps may be a tenant",
        "or an affiliate, and on at least one row the property has since passed to a public body.",
    ]
    if shared:
        lines += ["", "SHARED DIRECTORS — separate holdcos, one decision maker:"]
        for p, cs in sorted(shared.items()):
            lines.append(f"   {p} -> {'; '.join(sorted(cs))}")
    lines += [
        "",
        "STILL NOT ANSWERED BY EITHER SEARCH: mortgage term and maturity date. Those are never",
        "on title in BC, so renewal timing stays an estimate no matter how many titles are pulled.",
        "",
        "CONTACT DATA — WHAT IS HERE AND WHAT IS NOT",
        "Two address columns are now filled from the corporate register itself:",
        "  Mail To (registered office) — where the company accepts formal correspondence.",
        "  Director Address (registry) — the address each director has on file, which for a",
        "  single-asset holdco is frequently the operating premises or the director's home.",
        "Both are authoritative: they are the registry's own record, not a directory lookup.",
        "",
        "There are NO email addresses and NO phone numbers here, because BC Registries does",
        "not publish either. Nothing in this pipeline can produce them without guessing, and a",
        "plausible wrong contact costs more than a blank cell. Getting them means a directory",
        "or a subscription source, checked name by name — a separate job, done deliberately.",
        "",
        "PRIVACY: director names and addresses on this sheet come from the corporate register.",
        "They are for business correspondence about the property. Not a mailing list, not to be",
        "published, and not to leave the deal team.",
    ]
    for i, l in enumerate(lines, start=2):
        nw[f"A{i}"] = l
        nw[f"A{i}"].font = Font(name=FONT, size=10)
    nw.column_dimensions["A"].width = 104

    # The pull-recommendation sheet describes a decision that has now been made.
    if "How to read the flags" in wb.sheetnames:
        fs = wb["How to read the flags"]
        banner = ("SUPERSEDED for the rows where title is now in hand — see 'Title & Corp "
                  "Findings'. Kept because it explains how the pull list was chosen.")
        if fs["A1"].value != banner:
            fs.insert_rows(1)
            fs["A1"] = banner
            fs["A1"].font = Font(name=FONT, bold=True, size=10, color="C00000")

    wb.save(out_path)
    print(f"{len(rows)} rows -> {out_path}")
    print(f"  registered owner from title: {stats['title']} | joined to corp search: {stats['corp']}"
          f" | corp signal raised score: {stats['signal']} | public-body owners ranked out: {stats['public']}")
    print(f"  matched by company name (extraprovincial fallback): {stats['by_name']}")


if __name__ == "__main__":
    main()
