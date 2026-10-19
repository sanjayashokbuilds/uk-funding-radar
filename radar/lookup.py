"""Look up one company: profile, current directors and recent filings.

Usage:
    python -m radar.lookup 13302625
    python -m radar.lookup 13302625 --save   # also saves raw JSON to data/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from radar.client import (CompaniesHouseClient, CompaniesHouseError,
                          current_directors, normalise_company_number)

DATA_DIR = Path("data")  # gitignored: may contain directors' personal data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Look up one UK company.")
    parser.add_argument("company_number", help="e.g. 13302625")
    parser.add_argument("--save", action="store_true",
                        help="save the raw API responses to data/ for inspection")
    args = parser.parse_args(argv)

    number = normalise_company_number(args.company_number)
    try:
        client = CompaniesHouseClient()
        profile = client.company_profile(number)
        if profile is None:
            print(f"No company found with number {number}.")
            return 1
        officers = client.officers(number)
        filings = client.filing_history(number, items_per_page=15)
    except CompaniesHouseError as err:
        print(f"Error: {err}")
        return 1

    address = profile.get("registered_office_address", {})
    print(f"\n{profile.get('company_name')} ({number})")
    print(f"  Status:        {profile.get('company_status')}")
    print(f"  Incorporated:  {profile.get('date_of_creation')}")
    print(f"  SIC codes:     {', '.join(profile.get('sic_codes', [])) or 'none'}")
    print(f"  Address:       {', '.join(v for v in address.values() if v)}")

    directors = current_directors(officers)
    print(f"\nCurrent directors ({len(directors)}):")
    for d in directors:
        print(f"  - {d.get('name')} (appointed {d.get('appointed_on')})")

    print("\nRecent filings:")
    for f in (filings or {}).get("items", []):
        print(f"  {f.get('date')}  {f.get('type', ''):<8} {f.get('category', '')}")
        if f.get("type") == "SH01":
            # This is the bit stage 3 depends on: what an SH01 tells us.
            print(f"      description_values: {f.get('description_values')}")

    if args.save:
        DATA_DIR.mkdir(exist_ok=True)
        out = DATA_DIR / f"raw_{number}.json"
        out.write_text(json.dumps(
            {"profile": profile, "officers": officers, "filings": filings},
            indent=2))
        print(f"\nSaved raw responses to {out}")

    print(f"\n({client.requests_made} API requests used)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
