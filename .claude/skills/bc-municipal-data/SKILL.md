---
name: bc-municipal-data
description: Find and pull free property, zoning, and business licence data from BC municipal open data portals. Use when building a candidate list for a new municipality, looking for parcel/zoning/assessment data, identifying which company operates at an address, or when asked what free data exists for a city in Metro Vancouver.
---

# BC municipal open data

Where the free Tier 1 data comes from, what each municipality actually publishes, and how
to find it fast. Every city below was surveyed directly — the differences are real and
large, so check this table before promising a deliverable.

## What each municipality actually has

| City | Parcel/zoning | Assessed values | Business licences | Verdict |
|---|---|---|---|---|
| **Surrey** | Yes — one unified file | **Yes** | **Yes** (33k records, incl. phone) | Best. Full scoring possible |
| **Delta** | Yes — one unified file | No | Yes (no phone/contacts) | Good. Single file, clean |
| **Coquitlam** | Yes — 2 layers, joins cleanly | No | No | Usable, needs a join |
| **Burnaby** | Yes — joins on `LTO_PID` | No | No | Thin. Flat list only |
| **Langley Twp** | Two systems that **do not join** | Partial | No | Avoid — see below |
| **Richmond** | **Nothing** | No | No | No open data at all |

**Surrey is the only one publishing assessed land vs improvement values**, which is what
makes the underbuilt-land signal computable there and nowhere else. BC Assessment values
are provincial data; republishing them is each city's choice and most decline.

**Richmond has no open data portal** — only a read-only map viewer (RIM). Don't spend time
hunting; it isn't there. Richmond addresses need per-address lookup.

**Langley Township is a trap.** It publishes `Parcel_Attributes` (1,053 industrial-zoned
parcels) and `Assessments_2026` separately, but they do not share a usable key: 97% of
industrial PIDs in the parcel layer are absent from the 51,772-PID assessment file. Also,
the Assessments layer's own `Zoning` field is stale — it reports only 40 industrial
parcels where `Parcel_Attributes.Zoning_Descr` correctly reports 1,053. Trust
`Parcel_Attributes`.

## Finding a portal for a city not listed above

Most BC municipalities run Esri ArcGIS Hub. The fast path:

1. Try the DCAT catalog directly — it lists every dataset with direct CSV links:
   ```
   curl -sL "https://<portal-domain>/api/feed/dcat-us/1.1.json"
   ```
   Worked for Surrey and Delta. Returns `{"error": "Domain record(s) not found"}` if the
   domain is guessed wrong — don't guess domains, find the real one from the city website.

2. If the DCAT feed is incomplete, get the ArcGIS **org ID** and search content directly:
   ```
   curl -sL "https://<portal>/datasets/<any-slug>.json" | grep -oE '"orgId":"[A-Za-z0-9_-]+"'
   curl -sL "https://www.arcgis.com/sharing/rest/search?q=orgid:<ORGID>%20AND%20(parcel%20OR%20zoning%20OR%20assessment)&f=json&num=40"
   ```
   This is how Langley, Burnaby and Coquitlam were found. The DCAT feed missed datasets
   the org search returned.

3. Get a layer's fields and row count before downloading:
   ```
   curl -sL "<FeatureServer-url>/0?f=json"                                  # fields
   curl -sL "<FeatureServer-url>/0/query?where=1=1&returnCountOnly=true&f=json"
   ```

4. Page a FeatureServer 2000 rows at a time via `resultOffset`/`resultRecordCount`.

**Watch for name collisions.** Searching "Richmond" surfaces Richmond, California and
Richmond, Virginia; "Zoning FeatureServer" surfaced Santa Rosa County, Florida. Always
confirm the org actually belongs to the BC municipality before pulling.

**Rate limits are real.** Coquitlam's server returns HTTP 429 at ~6000 request units/min.
Back off ~60-90s rather than retrying immediately.

## Joining business licences to addresses

Licence addresses need normalising before they'll match a clean address list:

- **Delta embeds a newline and the city**: `"7690 VANTAGE WAY\nDELTA BC  V4G 1A7"` — split
  on `\n` and take the first line. Without this the join returns **zero** matches.
- Strip unit prefixes: `102-`, `E-`, `DOCK-`, `Unit 105,`, `#3`.
- Normalise street types both ways (`AVENUE`/`AVE`, `PARKWAY`/`PKWY`, etc.).

Typical yield after normalising: ~77-79% of addresses match a licence.

## What business licences do and don't tell you

They name the **operator**, not the registered owner. For an owner-occupied industrial
building those are often the same entity — a strong signal, worth flagging as
"single tenant". For a multi-tenant building none of the listed businesses is the
landlord, and the ownership lead is worthless.

Contact fields: **Surrey's licence data includes a phone number; Delta's does not.**
Neither includes email addresses or personal names, anywhere.
