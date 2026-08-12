#!/usr/bin/env python3
"""Parse LTSA "Title Search Print" PDFs into the Phase 1 charge-level table.

See docs/roadmap.md (Phase 1) for the target schema and docs/signals.md for how the
output fields feed the motivation signals.

    python3 scripts/parse_titles.py data/samples/titles/*.pdf -o data/parsed/charges.csv

Raw PDFs and parsed output both live under data/, which is gitignored — this script
and its schema are the committed artifact, never the title data itself.

Implementation note: LTSA prints this as a two-column form. Plain text extraction
(pypdf, pdftotext) reads column-by-column, scrambling label/value order. This parser
uses pdfplumber word coordinates to regroup words into true reading-order lines by
row (y-position) before parsing, which is what makes "Label: value" reliable.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import pdfplumber

FIELD_LINE = re.compile(r"^([A-Za-z][A-Za-z /]+?):\s*(.*)$")

KNOWN_LABELS = {
    "Registered Owner/Mailing Address",
    "Parcel Identifier",
    "Legal Description",
    "Nature",
    "Registration Number",
    "Registration Date and Time",
    "Registered Owner",
    "Remarks",
}

# LTSA renders these labels without a trailing colon in the two-column form, unlike
# the fields above — "Title Number CB505033" vs "Parcel Identifier: 031-936-482".
# Longer labels are listed first so "From Title Number" doesn't fall through as a
# value tail of the shorter alternative.
NO_COLON_LABELS = [
    "From Title Number",
    "Title Number",
    "Application Received",
    "Application Entered",
    "Taxation Authority",
    "Declared Value",
]
NO_COLON_LINE = re.compile(r"^(" + "|".join(re.escape(l) for l in NO_COLON_LABELS) + r")\s+(.*)$")

NOISE_PREFIXES = (
    "TITLE SEARCH PRINT",
    "File Reference",
    "Title Number:",
    "**CURRENT INFORMATION",
)


def pdf_to_lines(pdf_path: Path) -> list:
    """Reconstruct reading-order lines from word coordinates, across all pages."""
    lines = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            rows = {}
            for w in words:
                key = round(w["top"])
                # merge rows within 2pt of an existing key (rounding jitter)
                match = next((k for k in rows if abs(k - key) <= 2), key)
                rows.setdefault(match, []).append(w)
            for top in sorted(rows):
                ws = sorted(rows[top], key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in ws).strip()
                if text and not any(text.startswith(p) for p in NOISE_PREFIXES) \
                        and not re.match(r"^Page \d+ of \d+$", text) \
                        and "TITLE SEARCH PRINT" not in text:
                    lines.append(text)
    return lines


def parse_title(lines: list, source_file: str) -> tuple:
    title = {
        "source_file": source_file,
        "title_number": None,
        "pid": None,
        "legal_description": None,
        "registered_owner": None,
        "owner_incorporation_no": None,
        "owner_mailing_address": [],
        "taxation_authority": None,
        "application_received": None,
        "declared_value": None,
        "legal_notations": None,
    }
    charges = []
    current = None
    mode = None  # "owner_address" | None

    def flush_charge():
        nonlocal current
        if current is not None:
            charges.append(current)
        current = None

    for line in lines:
        # "Legal Notations" is a free-text section — no "Nature:" charge line, so a
        # real signal can live here instead (e.g. a Builders Lien Act notice of
        # interest). Capture it as its own field so the scorer can scan it, rather
        # than letting it silently glom onto legal_description as before.
        stripped = line.strip()
        if stripped == "Legal Notations":
            mode = "legal_notations"
            title["legal_notations"] = title["legal_notations"] or ""
            continue
        if stripped == "Charges, Liens and Interests":
            mode = None
            continue

        # A line can contain multiple "Label value" pairs packed together
        # (e.g. "Land Title District NEW WESTMINSTER") — only fields with an
        # explicit colon are structured data we act on; the rest is descriptive
        # boilerplate (district names) we don't need for Phase 1.
        fm = FIELD_LINE.match(line)
        ncm = None if fm else NO_COLON_LINE.match(line)
        if fm and fm.group(1).strip() in KNOWN_LABELS:
            label, value = fm.group(1).strip(), fm.group(2).strip()
            mode = None

            if label == "Nature":
                flush_charge()
                current = {
                    "charge_type": value,
                    "reg_number": None,
                    "reg_date": None,
                    "chargeholder": None,
                    "chargeholder_incorporation_no": None,
                }
                continue

            if current is not None:
                if label == "Registration Number":
                    current["reg_number"] = value
                elif label == "Registration Date and Time":
                    current["reg_date"] = value.split(" ")[0]
                elif label == "Registered Owner":
                    inc = re.search(r"INCORPORATION\s*NO\.?\s*([A-Z0-9]+)", value, re.I)
                    if inc:
                        current["chargeholder_incorporation_no"] = inc.group(1)
                        current["chargeholder"] = value[: inc.start()].strip()
                    else:
                        current["chargeholder"] = value
                continue

            if label == "Registered Owner/Mailing Address":
                inc = re.search(r"INC\.?\s*NO\.?\s*([A-Z0-9]+)", value, re.I)
                if inc:
                    title["owner_incorporation_no"] = inc.group(1)
                    title["registered_owner"] = value[: inc.start()].rstrip(", ").strip()
                else:
                    title["registered_owner"] = value.strip()
                mode = "owner_address"
            elif label == "Parcel Identifier":
                title["pid"] = value
            elif label == "Legal Description":
                if value:
                    title["legal_description"] = value
                mode = "legal_description"
            continue

        if ncm:
            label, value = ncm.group(1), ncm.group(2).strip()
            mode = None
            if label == "Title Number":
                title["title_number"] = value.split()[0] if value else value
            elif label == "Application Received":
                title["application_received"] = value
            elif label == "Taxation Authority":
                title["taxation_authority"] = value
            elif label == "Declared Value":
                title["declared_value"] = value.lstrip("$").replace(",", "")
            # "From Title Number" / "Application Entered" are recognized so their
            # lines don't leak into a continuation field, but not carried forward.
            continue

        if mode == "owner_address":
            title["owner_mailing_address"].append(line)
        elif mode == "legal_description":
            title["legal_description"] = ((title["legal_description"] or "") + " " + line).strip()
        elif mode == "legal_notations":
            title["legal_notations"] = (title["legal_notations"] + " " + line).strip()

    flush_charge()
    title["owner_mailing_address"] = " ".join(title["owner_mailing_address"])
    return title, charges


# Order matters — first match wins, so the specific patterns (life insurance, MIC)
# must precede the broad ones. Expanded after checking the classifier against two real
# datasets: 275 mortgages from pulled titles and 43 lenders from a comparable-sales
# export. The original patterns missed a lot, and two misses actually changed scoring:
#   - "THE TORONTO-DOMINION BANK" (17 mortgages) never matched, because \bTD\b only
#     catches the abbreviation, never the legal name.
#   - Life insurers are registered as "<X> LIFE ASSURANCE COMPANY", not "LIFE INSURANCE"
#     — so Imperial Life, Mutual Life, National Life and Manufacturers Life all fell
#     through to a 5-year default when the observed term for that class is ~10 years.
#     That is a five-year error in the predicted renewal date, in the one lender class
#     where the term is longest.
LENDER_TYPE_PATTERNS = [
    # life insurers first — their names contain "COMPANY"/"ASSURANCE", not "BANK"
    (r"LIFE ASSURANCE|LIFE INSURANCE|SUN LIFE|MANULIFE|MANUFACTURERS LIFE|GREAT-WEST"
     r"|\bSLC MANAGEMENT\b|CANADA LIFE|EMPIRE LIFE|INDUSTRIAL ALLIANCE", "life_insurance"),
    (r"MORTGAGE INVESTMENT|\bMIC\b|MORTGAGE CORP|MORTGAGE INC|MORTGAGE FUND", "mic_private"),
    (r"CREDIT UNION|VANCITY|COAST CAPITAL|FIRST WEST|GULF & FRASER|PROSPERA|ENVISION", "credit_union"),
    (r"ROYAL BANK|BANK OF MONTREAL|BANK OF NOVA SCOTIA|SCOTIABANK|CIBC"
     r"|CANADIAN IMPERIAL BANK|TORONTO-DOMINION|\bTD BANK\b|\bTD\b|HSBC|HONGKONG BANK"
     r"|NATIONAL BANK|CANADIAN WESTERN BANK|LAURENTIAN BANK|ICICI BANK"
     r"|BUSINESS DEVELOPMENT BANK|\bBDC\b", "chartered_bank"),
    # trust/institutional lenders and government agencies behave differently from both
    # banks and private lenders, so they get their own bucket rather than "other"
    (r"\bTRUST\b|TRUSTCO|COMPUTERSHARE|\bCMHC\b|CANADA MORTGAGE AND HOUSING"
     r"|CENTRAL MORTGAGE AND HOUSING|CMLS|MCAP|ROYNAT|WELLS FARGO|EXTENSION FUND"
     r"|\bREIT\b|CHOICE PROPERTIES|PENSION|\bFUND\b", "institutional_trust"),
    # Only genuine numbered companies (a digit string as the company name). An earlier
    # version matched any name ending in LTD/INC/CORP, which swept in Laurentian Trust,
    # a church extension fund and a listed REIT and handed them a 1-year term — inventing
    # renewal urgency that isn't there. Named corporations now fall through to "other"
    # and keep the conservative 5-year default: under-calling a renewal wastes nothing,
    # over-calling one wastes a broker's afternoon.
    (r"^\d{6,7}\s*B\.?C\.?\s*LTD|^\d{6,7}\s*(ONTARIO|ALBERTA|CANADA)\s*(INC|LTD)", "numbered_co_private"),
]

# A chargeholder with no corporate suffix at all is almost always a natural person —
# typically a vendor-take-back mortgage or a private family loan. Worth separating:
# these rarely behave like institutional debt on renewal.
PERSON_NAME = re.compile(r"^[A-Z][A-Z\-' ]+$")
CORPORATE_HINT = re.compile(
    r"\b(LTD|LIMITED|INC|INCORPORATED|CORP\w*|COMPANY|BANK|UNION|TRUST\w*|ASSOCIATION"
    r"|SOCIETY|FUND|CAPITAL|HOLDINGS|INVESTMENTS?|PROPERTIES|VENTURES|ENTERPRISES|GP|LP"
    r"|LLP|AUTHORITY|CHURCH|MANAGEMENT|FINANCE|FINANCIAL|SERVICES|DEVELOPMENTS?)\b")


def classify_lender(name: str) -> str:
    if not name:
        return ""
    upper = name.upper().strip()
    for pattern, label in LENDER_TYPE_PATTERNS:
        if re.search(pattern, upper):
            return label
    if PERSON_NAME.match(upper) and not CORPORATE_HINT.search(upper):
        return "private_individual"
    return "other"


FIELDNAMES = [
    "pid", "title_number", "registered_owner", "owner_incorporation_no",
    "owner_mailing_address", "taxation_authority", "legal_description",
    "legal_notations", "declared_value", "application_received", "charge_type",
    "charge_reg_number", "charge_reg_date", "chargeholder",
    "chargeholder_incorporation_no", "lender_type", "mortgage_count_on_title",
    "distress_charge_count_on_title", "source_file",
]


def to_rows(title: dict, charges: list) -> list:
    mortgages = [c for c in charges if c["charge_type"] == "MORTGAGE"]
    distress = [c for c in charges if c["charge_type"] in
                ("CERTIFICATE OF PENDING LITIGATION", "JUDGMENT", "BUILDERS LIEN")]

    rows_source = charges or [{
        "charge_type": None, "reg_number": None, "reg_date": None,
        "chargeholder": None, "chargeholder_incorporation_no": None,
    }]

    rows = []
    for c in rows_source:
        rows.append({
            "pid": title["pid"],
            "title_number": title["title_number"],
            "registered_owner": title["registered_owner"],
            "owner_incorporation_no": title["owner_incorporation_no"],
            "owner_mailing_address": title["owner_mailing_address"],
            "taxation_authority": title["taxation_authority"],
            "legal_description": title["legal_description"],
            "legal_notations": title["legal_notations"],
            "declared_value": title["declared_value"],
            "application_received": title["application_received"],
            "charge_type": c["charge_type"],
            "charge_reg_number": c["reg_number"],
            "charge_reg_date": c["reg_date"],
            "chargeholder": c["chargeholder"],
            "chargeholder_incorporation_no": c["chargeholder_incorporation_no"],
            "lender_type": classify_lender(c["chargeholder"]) if c["charge_type"] == "MORTGAGE" else "",
            "mortgage_count_on_title": len(mortgages),
            "distress_charge_count_on_title": len(distress),
            "source_file": title["source_file"],
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("data/parsed/charges.csv"))
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for pdf_path in args.pdfs:
        lines = pdf_to_lines(pdf_path)
        title, charges = parse_title(lines, pdf_path.name)
        if not title["pid"]:
            print(f"WARNING: no PID parsed from {pdf_path.name}", file=sys.stderr)
        all_rows.extend(to_rows(title, charges))

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Parsed {len(args.pdfs)} title(s) -> {len(all_rows)} charge rows -> {args.out}")


if __name__ == "__main__":
    main()
