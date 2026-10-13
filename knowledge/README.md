# knowledge/

Reference data the agents look up. Committed, so it must contain **no patient
data**: nothing copied from case records, no names, dates, record numbers or
Bates labels. Build entries from published sources only, and record the
source on every entry.

- `abbreviations.json`: `entries` maps an abbreviation to its possible
  expansions and the published list it came from.
- `date_roles.json`: labels that name what a date on a page means.
- `injury_profiles/<region>.json`: one file per body region (`cervical`,
  `lumbar`, `shoulder`, ...). Each needs `sources` (guideline or paper
  citations) and `reviewed_by` before it is used.

CI fails if anything other than `.json` or `.md` lands in this folder.
