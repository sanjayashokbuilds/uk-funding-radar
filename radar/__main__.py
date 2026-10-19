"""One command for the whole morning run:

    python -m radar

1. stream  - collect new SH01s from the Companies House filings stream
2. filters - keep London tech startups and score funding-round likelihood
3. export  - add current directors and write output/funding_radar_<date>.csv
"""
import sys

from radar import export, filters, stream


def main() -> int:
    steps = [("Collecting SH01s", stream.main),
             ("Filtering and scoring", filters.main),
             ("Exporting CSV", export.main)]
    for n, (label, step) in enumerate(steps, 1):
        print(f"\n=== Step {n}/3: {label} ===")
        if step([]) != 0:
            print(f"\nStopped at step {n}. Fix the error above and run again; "
                  "progress so far is saved.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
