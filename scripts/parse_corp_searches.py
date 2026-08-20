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

PRIVACY: director records carry personal home addresses. Treat the output as sensitive
working material — it stays under data/ (gitignored) and must not be published or shared
outside the deal team.
"""

import argparse
import csv
import re
from pathlib import Path

import pdfplumber

SUMMARY_SPLIT = re.compile(r"BC Company Summary\s*\n\s*For\s*\n", re.I)
STATUS = re.compile(r"\n\s*(ACTIVE|HISTORICAL|CANCELLED|DISSOLVED|STRUCK[A-Z ]*)\s*\n")
FIELDS = {
    "incorporation_number": re.compile(r"Incorporation Number:\s*(\S+)"),
    "business_number": re.compile(r"Business Number:\s*(\S+)"),
    "in_liquidation": re.compile(r"In Liquidation:\s*(\w+)"),
    "receiver": re.compile(r"Receiver:\s*(\w+)"),
}
RECOGNITION = re.compile(r"Recognition Date and Time:\s*\n?\s*(?:Incorporated on\s*)?([A-Z][a-z]+ \d{1,2}, \d{4})")
LAST_REPORT = re.compile(r"Last Annual Report Filed:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
# Director/officer blocks list a person as "Last, First Middle" under a NAME header.
PERSON = re.compile(r"Last Name, First Name, Middle Name:\s*\n\s*([^\n]+)")
DIRECTOR_SECTION = re.compile(r"DIRECTOR INFORMATION(.*?)(?=\n[A-Z][A-Z ]{6,}\n|\Z)", re.S)
OFFICER_SECTION = re.compile(r"OFFICER INFORMATION(.*?)(?=\n[A-Z][A-Z ]{6,}\n|\Z)", re.S)
REG_OFFICE = re.compile(r"REGISTERED OFFICE INFORMATION.*?Delivery Address:\s*\n(.*?)(?=\nRECORDS OFFICE|\n[A-Z][A-Z ]{6,}\n)", re.S)

# A registered office at a law or accounting firm often precedes a wind-up or estate
# process (docs/signals.md section C). Detected by name, not assumed.
PROFESSIONAL_OFFICE = re.compile(
    r"\bLLP\b|\bLAW\b|BARRISTER|SOLICITOR|NOTAR|ACCOUNT|CHARTERED|\bCPA\b", re.I)


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse_one(block: str) -> dict:
    name = clean(block.split("\n", 1)[0])
    rec = {"company_name": name}
    m = STATUS.search(block)
    rec["status"] = m.group(1).strip() if m else ""
    for k, pat in FIELDS.items():
        mm = pat.search(block)
        rec[k] = mm.group(1) if mm else ""
    mm = RECOGNITION.search(block)
    rec["incorporated"] = mm.group(1) if mm else ""
    mm = LAST_REPORT.search(block)
    rec["last_annual_report"] = mm.group(1) if mm else ""

    office = ""
    mm = REG_OFFICE.search(block)
    if mm:
        office = clean(" ".join(mm.group(1).split("\n")[:3]))
    rec["registered_office"] = office
    rec["office_is_professional_firm"] = bool(PROFESSIONAL_OFFICE.search(office))

    def people(section_re):
        sm = section_re.search(block)
        if not sm:
            return []
        return [clean(p) for p in PERSON.findall(sm.group(1))]

    directors = people(DIRECTOR_SECTION)
    officers = people(OFFICER_SECTION)
    # de-dupe while preserving order; the same person is often both
    seen, combined = set(), []
    for p in directors + officers:
        if p.upper() not in seen:
            seen.add(p.upper())
            combined.append(p)
    rec["directors"] = "; ".join(directors)
    rec["officers"] = "; ".join(officers)
    rec["all_people"] = "; ".join(combined)
    rec["people_count"] = len(combined)
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    rows = []
    for path in args.pdfs:
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        blocks = SUMMARY_SPLIT.split(text)[1:]  # first chunk is the letterhead
        for b in blocks:
            r = parse_one(b)
            r["source_file"] = path.name
            rows.append(r)

    fieldnames = ["company_name", "status", "incorporation_number", "business_number",
                  "incorporated", "last_annual_report", "in_liquidation", "receiver",
                  "registered_office", "office_is_professional_firm",
                  "directors", "officers", "all_people", "people_count", "source_file"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} company summaries -> {args.out}")
    bad = [r for r in rows if not r["company_name"] or not r["incorporation_number"]]
    if bad:
        print(f"  WARNING: {len(bad)} rows missing name or incorporation number")


if __name__ == "__main__":
    main()
