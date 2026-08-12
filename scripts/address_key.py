#!/usr/bin/env python3
"""One canonical civic-address key, shared by every join in this project.

Address formats differ in every source and the mismatches are silent — a bad key
returns zero matches or, worse, a plausible partial match. Formats seen so far:

    Altus comps        "Unit 7, 8311 129th Street"   ordinals, full street type
    AutoProp           "12487 82 AV Surrey BC V3W"   abbreviated, city appended
    Surrey municipal   "12487 82 Ave"                abbreviated, no city
    Delta licences     "7690 VANTAGE WAY\\nDELTA BC"  newline + city + postal

Two bugs this fixes, both found by checking real joins rather than trusting the code:
  - Delta's embedded newline made an entire join return zero matches.
  - "AV" vs "AVE" silently failed, hiding real overlap between the comps and AutoProp.
"""

import re

# Every variant maps to one canonical token. Longest forms first so "AVENUE" is
# consumed before a bare "AVE" rule could half-match it.
STREET_TYPES = {
    "AVENUE": "AVE", "AVEN": "AVE", "AV": "AVE", "AVE": "AVE",
    "STREET": "ST", "STR": "ST", "ST": "ST",
    "ROAD": "RD", "RD": "RD",
    "DRIVE": "DR", "DR": "DR",
    "BOULEVARD": "BLVD", "BLVD": "BLVD",
    "PLACE": "PL", "PL": "PL",
    "CRESCENT": "CR", "CRES": "CR", "CR": "CR",
    "PARKWAY": "PKWY", "PKY": "PKWY", "PKWY": "PKWY",
    "HIGHWAY": "HWY", "HY": "HWY", "HWY": "HWY",
    "COURT": "CRT", "CRT": "CRT", "CT": "CRT",
    "LANE": "LN", "LN": "LN",
    "WAY": "WAY", "WY": "WAY",
    "GATE": "GATE", "TERRACE": "TERR", "TERR": "TERR",
    "CONNECTOR": "CONN", "DIVERSION": "DIVERSION",
}

# Only strip a city name when it is genuinely a city tail — i.e. followed by "BC" or a
# postal code, or ending the string after a comma. Several of these double as street
# names ("4872 Delta Street", "Langley Bypass"); an unconditional strip silently
# destroyed those addresses, leaving just the street number.
CITY_TAIL = re.compile(
    r"(?:,\s*|\s+)(?:SURREY|DELTA|RICHMOND|BURNABY|LANGLEY|COQUITLAM|ABBOTSFORD"
    r"|NEW WESTMINSTER|TSAWWASSEN|LADNER|NORTH VANCOUVER|WEST VANCOUVER|PORT COQUITLAM)"
    r"(?=\s*,?\s*(?:BC|B\.C\.|BRITISH COLUMBIA)\b|\s*$).*$")
UNIT_PREFIX = re.compile(r"^(UNIT|SUITE|STE|BAY|DOCK)\s*[#]?\s*\S+\s*,?\s*", re.I)
HASH_PREFIX = re.compile(r"^#\s*\S+\s*,?\s*")
DASH_PREFIX = re.compile(r"^[A-Z0-9]{1,4}\s*-\s*(?=\d)")
ORDINAL = re.compile(r"\b(\d+)(ST|ND|RD|TH)\b")


def address_key(raw) -> str:
    """Return a canonical key, or '' if there's nothing usable to match on."""
    if not raw:
        return ""
    a = str(raw).upper().strip()
    if a in ("N/A", "-", "NONE"):
        return ""
    a = a.split("\n")[0]              # Delta packs city onto a second line
    a = CITY_TAIL.sub("", a)
    a = UNIT_PREFIX.sub("", a)
    a = HASH_PREFIX.sub("", a)
    a = DASH_PREFIX.sub("", a)
    a = re.sub(r"[.,]", " ", a)
    a = ORDINAL.sub(r"\1", a)          # 129th -> 129, matching "129 St"
    tokens = [t for t in a.split() if t]
    tokens = [STREET_TYPES.get(t, t) for t in tokens]
    # drop a trailing postal code if one survived
    if tokens and re.fullmatch(r"[A-Z]\d[A-Z]\d?[A-Z]?\d?", tokens[-1]):
        tokens.pop()
    return " ".join(tokens).strip()


if __name__ == "__main__":
    samples = [
        "Unit 7, 8311 129th Street", "8311 129 St",
        "12487 82nd Avenue", "12487 82 AV Surrey BC V3W 3E8", "12487 82 Ave",
        "7690 VANTAGE WAY\nDELTA BC  V4G 1A7", "7690 Vantage Way",
        "102-4872 DELTA ST", "4872 Delta Street",
    ]
    for s in samples:
        print(f"{s!r:48s} -> {address_key(s)!r}")
