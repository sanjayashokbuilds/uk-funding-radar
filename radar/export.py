"""Stage 5: add current directors and write the CSV.

Only scored companies flagged 'likely' or 'uncertain' are exported
('unlikely' too with --all-flags). Each daily CSV contains only filings not
exported before, so every morning's file is just the new leads.

Data minimisation: we export directors' names and appointment dates only,
never dates of birth or addresses. The CSVs go in output/, which is
gitignored, because they contain personal data.

Usage:
    python -m radar.export
    python -m radar.export --rebuild      # one CSV with everything so far
    python -m radar.export --all-flags    # include 'unlikely' rows too
    python -m radar.export --tech-only    # leave out holding companies
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

from radar.client import CompaniesHouseClient, CompaniesHouseError, current_directors
from radar.filters import load_assessed

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
EXPORTED_FILE = DATA_DIR / "exported_ids.json"

COLUMNS = [
    "company_number", "company_name", "likely_funding_round", "score", "reason",
    "sh01_filings_this_batch",
    "share_capital_increase_pct", "filing_date", "allotment_date",
    "sic_codes", "sector", "registered_address", "incorporated",
    "directors", "companies_house_link",
]


def format_address(address: dict) -> str:
    order = ["premises", "address_line_1", "address_line_2", "locality",
             "region", "postal_code"]
    return ", ".join(address[k] for k in order if address.get(k))


def format_directors(officers_response) -> str:
    return "; ".join(
        f"{d.get('name')} (appointed {d.get('appointed_on')})"
        for d in current_directors(officers_response)
    )


def best_per_company(rows: list) -> list:
    """One round is often filed as several SH01s. Keep each company's
    best-scoring filing and count how many there were."""
    best, counts = {}, {}
    for r in rows:
        n = r["company_number"]
        counts[n] = counts.get(n, 0) + 1
        if n not in best or r["score"] > best[n]["score"]:
            best[n] = r
    return [dict(r, filings_count=counts[n]) for n, r in best.items()]


def to_csv_row(row: dict, directors: str) -> dict:
    return {
        "company_number": row["company_number"],
        "company_name": row.get("company_name"),
        "likely_funding_round": row["flag"],
        "score": row["score"],
        "reason": row["reasons"],
        "sh01_filings_this_batch": row.get("filings_count", 1),
        "share_capital_increase_pct": row.get("pct_increase"),
        "filing_date": row.get("filing_date"),
        "allotment_date": row.get("allotment_date"),
        "sic_codes": " ".join(row.get("sic_codes") or []),
        "sector": row.get("sector"),
        "registered_address": format_address(row.get("address") or {}),
        "incorporated": row.get("incorporated"),
        "directors": directors,
        "companies_house_link": "https://find-and-update.company-information.service.gov.uk"
                                f"/company/{row['company_number']}",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write the funding radar CSV.")
    parser.add_argument("--rebuild", action="store_true",
                        help="export everything so far, not just new rows")
    parser.add_argument("--all-flags", action="store_true",
                        help="include 'unlikely' rows")
    parser.add_argument("--tech-only", action="store_true",
                        help="leave out holding companies (sector unclear)")
    args = parser.parse_args(argv)

    flags = {"likely", "uncertain"} | ({"unlikely"} if args.all_flags else set())
    exported = set() if args.rebuild or not EXPORTED_FILE.exists() \
        else set(json.loads(EXPORTED_FILE.read_text()))
    rows = [r for r in load_assessed().values()
            if r.get("flag") in flags and r["filing_id"] not in exported
            and not (args.tech_only and r.get("sector") != "tech")]

    if not rows:
        print("No new likely/uncertain funding rounds to export.")
        return 0

    try:
        client = CompaniesHouseClient()
        csv_rows = [to_csv_row(r, format_directors(client.officers(r["company_number"])))
                    for r in best_per_company(rows)]  # one officers call per company
    except CompaniesHouseError as err:
        print(f"Error: {err}")
        return 1

    order = {"likely": 0, "uncertain": 1, "unlikely": 2}
    csv_rows.sort(key=lambda c: (order[c["likely_funding_round"]], -c["score"]))
    OUTPUT_DIR.mkdir(exist_ok=True)
    name = "funding_radar_all.csv" if args.rebuild else f"funding_radar_{date.today()}.csv"
    path = OUTPUT_DIR / name
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(csv_rows)

    if not args.rebuild:
        DATA_DIR.mkdir(exist_ok=True)
        EXPORTED_FILE.write_text(json.dumps(sorted(exported | {r["filing_id"] for r in rows})))

    likely = sum(c["likely_funding_round"] == "likely" for c in csv_rows)
    print(f"Wrote {len(csv_rows)} rows ({likely} likely) to {path} "
          f"({client.requests_made} API requests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
