#!/usr/bin/env python3
"""Parse BC Registries "BC Company Summary" PDFs into one row per company.

Corp searches answer what neither title nor comps can: is the owning entity healthy, and
who actually runs it. Per docs/signals.md section C, a struck or dissolving owner is one
of the strongest motivation signals available, and directors are the only authoritative
named contacts in this whole pipeline.

    python3 scripts/parse_corp_searches.py corps.pdf -o data/parsed/corps.csv

Several summaries are usually concatenated into one PDF; this splits on the
"BC Company Summary / For / <name>" header rather than on page breaks, since a summary
can run to any number of pages.

Like the LTSA title print, this is a TWO-COLUMN form: mailing address on the left,
delivery address on the right, and flat text extraction runs them together. Reading it
column-by-column off word coordinates is what makes director addresses usable — and a
first pass that treated it as flat text silently captured only the FIRST director of each
company, because the line "CANADA CANADA" (the two columns' country lines side by side)
looks exactly like an ALL-CAPS section header.

PRIVACY: director records carry personal home addresses. Treat the output as sensitive
working material — it stays under data/ (gitignored) and must not be published or shared
outside the deal team. These are registry addresses for a corporate officer, appropriate
for business correspondence about the property; they are not a mailing list.
"""

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import pdfplumber

# Only the address blocks are genuinely two-column; the company name and the field labels
# straddle the middle of the page, so a fixed split corrupts them. Read every line as flat
# text (which is what the field regexes want) and keep each line's words so an address can
# be split by column on demand. The boundary is taken from the page's own "Delivery
# Address:" label rather than hardcoded.
DEFAULT_SPLIT_X = 250
LINE_TOL = 4  # points; a label and its value sit at slightly different tops when their
              # font sizes differ, so lines are clustered on vertical CENTRE, not top

# Not every owner is a BC company. Extraprovincial registrations (Alberta, federal) come
# back on a different form with "Registration Number in BC" instead of an incorporation
# number — Costco and Lhoist in this set. Same shape otherwise, so parse both.
HEADER = re.compile(r"^(BC Company|Extraprovincial Company|Society) Summary$")
# Trailing text allowed: the officer header can read "OFFICER INFORMATION AS AT <date>".
SECTION = re.compile(
    r"^(REGISTERED OFFICE|RECORDS OFFICE|HEAD OFFICE|ATTORNEY|DIRECTOR|OFFICER) INFORMATION")
FIRM_LABEL = re.compile(r"^Corporation or Firm Name:")
NO_DIRECTORS = re.compile(r"Directors are not recorded for extraprovincial", re.I)
NO_SECTION = re.compile(r"^NO (DIRECTOR|OFFICER|RECORDS OFFICE)[A-Z ]* FILED", re.I)
PERSON_LABEL = re.compile(r"^Last Name, First Name, Middle Name:")
ADDRESS_LABEL = re.compile(r"^(Mailing|Delivery) Address:")
FOOTER = re.compile(r"Page:\s*\d+\s*of\s*\d+", re.I)

FIELDS = {
    "incorporation_number": re.compile(
        r"(?:Incorporation Number|Registration Number in BC):\s*(\S+)"),
    "business_number": re.compile(r"Business Number:\s*(\S+)"),
    "in_liquidation": re.compile(r"In Liquidation:\s*(\w+)"),
    "receiver": re.compile(r"Receiver:\s*(\w+)"),
}
STATUS = re.compile(r"\n\s*(ACTIVE|HISTORICAL|CANCELLED|DISSOLVED|STRUCK[A-Z ]*)\s*\n")
RECOGNITION = re.compile(
    r"Recognition Date and Time:\s*\n?\s*(?:Incorporated on\s*)?([A-Z][a-z]+ \d{1,2}, \d{4})")
LAST_REPORT = re.compile(r"Last Annual Report Filed:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
# The registry states this outright rather than leaving it to be inferred from the dates.
FORMED_BY = re.compile(r"as a result of an?\s+(\w+)", re.I)

# A registered office at a law or accounting firm often precedes a wind-up or estate
# process (docs/signals.md section C). Detected by name, not assumed.
PROFESSIONAL_OFFICE = re.compile(
    r"\bLLP\b|\bLAW\b|BARRISTER|SOLICITOR|NOTAR|ACCOUNT|CHARTERED|\bCPA\b", re.I)


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def page_lines(page):
    """Return [(flat_line_text, mailing_column_text)] in reading order."""
    words = page.extract_words()
    delivery = [w["x0"] for w in words if w["text"] == "Delivery"]
    split_x = min(delivery) - 5 if delivery else DEFAULT_SPLIT_X
    rows, current, last = [], [], None
    for w in sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2):
        c = (w["top"] + w["bottom"]) / 2
        if last is None or abs(c - last) <= LINE_TOL:
            current.append(w)
            last = c if last is None else last
        else:
            rows.append(current)
            current, last = [w], c
    if current:
        rows.append(current)
    out = []
    for ws in rows:
        ws = sorted(ws, key=lambda w: w["x0"])
        flat = " ".join(w["text"] for w in ws)
        left = " ".join(w["text"] for w in ws if w["x0"] < split_x)
        out.append((clean(flat), clean(left)))
    return out


def split_companies(lines):
    """Split the document into one list of lines per company summary."""
    starts = [i for i, (flat, _) in enumerate(lines) if HEADER.match(flat)]
    return [lines[a:b] for a, b in zip(starts, starts[1:] + [len(lines)])]


def read_people_and_office(lines):
    """Walk the block once, tracking which section each person belongs to.

    Returns (directors, officers, registered_office) where each person is
    {"name": ..., "address": ...} using the MAILING address (left column) — that is the
    address the registry holds for correspondence.
    """
    directors, officers, attorney = [], [], {}
    offices = {}
    section = None
    i = 0
    while i < len(lines):
        left, _mail = lines[i]
        if SECTION.match(left):
            section = SECTION.match(left).group(1)
            i += 1
            continue
        if NO_SECTION.match(left):
            section = None
            i += 1
            continue

        if section in ("REGISTERED OFFICE", "RECORDS OFFICE", "HEAD OFFICE") and \
                ADDRESS_LABEL.match(left):
            addr, i = read_address(lines, i + 1)
            offices.setdefault(section, addr)
            continue

        # An extraprovincial company files a BC attorney instead of directors — a firm or a
        # person authorised to accept service here. It is the only BC-side contact the
        # registry holds for that company, so it is worth carrying.
        if section == "ATTORNEY" and FIRM_LABEL.match(left):
            name = lines[i + 1][0] if i + 1 < len(lines) else ""
            j = i + 2
            addr = ""
            while j < len(lines) and not SECTION.match(lines[j][0]):
                if ADDRESS_LABEL.match(lines[j][0]):
                    addr, j = read_address(lines, j + 1)
                    break
                j += 1
            attorney = {"name": clean(name), "address": addr}
            i = j
            continue

        if PERSON_LABEL.match(left):
            name = ""
            j = i + 1
            while j < len(lines) and not name:
                cand = lines[j][0]
                if cand and not FOOTER.search(cand):
                    name = cand
                j += 1
            addr = ""
            while j < len(lines):
                if ADDRESS_LABEL.match(lines[j][0]):
                    addr, j = read_address(lines, j + 1)
                    break
                if PERSON_LABEL.match(lines[j][0]) or SECTION.match(lines[j][0]):
                    break
                j += 1
            rec = {"name": name, "address": addr}
            if section == "ATTORNEY":
                attorney = rec
            else:
                (officers if section == "OFFICER" else directors).append(rec)
            i = j
            continue
        i += 1
    office = offices.get("REGISTERED OFFICE") or offices.get("HEAD OFFICE") or ""
    return directors, officers, office, attorney


def read_address(lines, i):
    """Collect the mailing-address column until the block ends. Returns (address, index)."""
    parts = []
    while i < len(lines):
        flat, mailing = lines[i]
        if (not flat or FOOTER.search(flat) or PERSON_LABEL.match(flat)
                or SECTION.match(flat) or NO_SECTION.match(flat)
                or ADDRESS_LABEL.match(flat)):
            break
        parts.append(mailing or flat)
        i += 1
        if parts[-1].upper() == "CANADA":
            break
    # "CANADA" on its own tells the broker nothing they don't already assume — and it also
    # marks the end of the address block, so stop there rather than running into whatever
    # section follows.
    if "CANADA" in [p.upper() for p in parts]:
        parts = parts[:[p.upper() for p in parts].index("CANADA")]
    return clean(", ".join(parts)), i


def parse_one(lines) -> dict:
    # lines[0] is "BC Company Summary", lines[1] "For", lines[2] the company name
    text = "\n".join(flat for flat, _ in lines)
    rec = {"company_name": lines[2][0] if len(lines) > 2 else ""}
    m = STATUS.search(text)
    rec["status"] = m.group(1).strip() if m else ""
    for k, pat in FIELDS.items():
        mm = pat.search(text)
        rec[k] = mm.group(1) if mm else ""
    mm = RECOGNITION.search(text)
    rec["incorporated"] = mm.group(1) if mm else ""
    mm = LAST_REPORT.search(text)
    rec["last_annual_report"] = mm.group(1) if mm else ""
    mm = FORMED_BY.search(text)
    rec["formed_by"] = mm.group(1).title() if mm else ""
    rec["form"] = ("extraprovincial" if "Extraprovincial" in (lines[0][0] if lines else "")
                   else "bc_company")

    directors, officers, office, attorney = read_people_and_office(lines)
    rec["registered_office"] = office
    rec["bc_attorney"] = (f"{attorney['name']} — {attorney['address']}"
                          if attorney.get("name") else "")
    rec["directors_not_recorded"] = bool(NO_DIRECTORS.search(text))
    rec["office_is_professional_firm"] = bool(PROFESSIONAL_OFFICE.search(office))

    # De-dupe while preserving order; the same person is often both director and officer.
    seen, combined = set(), []
    for p in directors + officers:
        if p["name"].upper() not in seen:
            seen.add(p["name"].upper())
            combined.append(p)
    rec["directors"] = "; ".join(p["name"] for p in directors)
    rec["officers"] = "; ".join(p["name"] for p in officers)
    rec["all_people"] = "; ".join(p["name"] for p in combined)
    rec["people_count"] = len(combined)
    rec["people_addresses"] = " | ".join(
        f"{p['name']} — {p['address']}" for p in combined if p["address"])
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    rows = []
    for path in args.pdfs:
        with pdfplumber.open(str(path)) as pdf:
            lines = [ln for pg in pdf.pages for ln in page_lines(pg)]
        for block in split_companies(lines):
            r = parse_one(block)
            r["source_file"] = path.name
            rows.append(r)

    seen, deduped = set(), []
    for r in rows:
        key = (r["incorporation_number"], r["company_name"])
        if key in seen:
            print(f"  duplicate search skipped: {r['company_name']} ({r['source_file']})")
            continue
        seen.add(key)
        deduped.append(r)
    rows = deduped

    fieldnames = ["company_name", "status", "incorporation_number", "business_number",
                  "incorporated", "last_annual_report", "in_liquidation", "receiver",
                  "formed_by", "form", "registered_office", "office_is_professional_firm",
                  "bc_attorney", "directors_not_recorded",
                  "directors", "officers", "all_people", "people_count",
                  "people_addresses", "source_file"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} company summaries -> {args.out}")
    print(f"  {sum(r['people_count'] for r in rows)} named directors/officers, "
          f"{sum(1 for r in rows if r['people_addresses'])} companies with a registry address")
    bad = [r for r in rows if not r["company_name"] or not r["incorporation_number"]]
    if bad:
        print(f"  WARNING: {len(bad)} rows missing name or incorporation number")
    # Extraprovincial registrations legitimately have no directors on file; only flag the
    # ones that should have had them.
    nopeople = [r for r in rows if not r["people_count"] and not r["directors_not_recorded"]]
    if nopeople:
        print(f"  WARNING: {len(nopeople)} companies with no director or officer parsed: "
              f"{', '.join(r['company_name'] for r in nopeople[:5])}")
    extra = [r for r in rows if r["directors_not_recorded"]]
    if extra:
        print(f"  {len(extra)} extraprovincial: no directors on the BC register "
              f"({', '.join(r['company_name'] for r in extra)}); "
              f"{sum(1 for r in extra if r['bc_attorney'])} have a BC attorney on file")


if __name__ == "__main__":
    main()
