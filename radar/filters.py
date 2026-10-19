"""Stage 4: decide which SH01s are London tech startups, and which look
like real funding rounds.

It works as a funnel, cheapest checks first, so we spend as few API
requests as possible:

  1. Company number (free, no API call). Numbers are issued in sequence,
     so the number tells you roughly when a company was born. England &
     Wales numbers below 12,000,000 were issued before ~2019, so they can't
     be under 5 years old. Scottish (SC) / NI numbers can't have a London
     registered office. Both get dropped without asking the API.
  2. Company profile (1 request): active, London postcode, tech SIC code,
     incorporated in the last 5 years.
  3. Filing history (1 request, survivors only): score how much this SH01
     looks like a funding round.

Usage:
    python -m radar.filters
    python -m radar.filters --limit 50     # quick test on 50 SH01s
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from radar.client import CompaniesHouseClient, CompaniesHouseError
from radar.stream import load_sh01s

DATA_DIR = Path("data")
ASSESSED_FILE = DATA_DIR / "assessed.jsonl"
PROFILE_CACHE = DATA_DIR / "profiles_cache.json"

# --- Settings (the assumptions you'd defend in an interview) --------------

MAX_AGE_YEARS = 5
# Safe lower bound: comfortably older than 5 years, so we never wrongly drop
# a young company. Exact age is checked properly from the profile anyway.
MIN_COMPANY_NUMBER = 12_000_000

# London postcode areas (inner London). Outer areas like HA, KT, BR also
# cover places outside London, so we don't use them.
LONDON_POSTCODE_AREAS = {"E", "EC", "N", "NW", "SE", "SW", "W", "WC"}

TECH_SIC_CODES = {
    "58210": "publishing of computer games",
    "58290": "other software publishing",
    "62011": "ready-made interactive leisure software",
    "62012": "business and domestic software development",
    "62020": "IT consultancy",
    "62030": "computer facilities management",
    "62090": "other IT services",
    "63110": "data processing and hosting",
    "63120": "web portals",
    "72110": "R&D in biotechnology",
    "72190": "other R&D in natural sciences and engineering",
}
# Many startups raise at a holding-company level (e.g. Bloom & Wild
# Holdings is 64209). We keep these but mark the sector as uncertain.
HOLDING_SIC_CODES = {"64209": "holding company", "70100": "head office activities"}

# Funding-round scoring
WINDOW_DAYS = 45            # how close a resolution / new share class must be
BIG_INCREASE_PCT = 5.0      # priced rounds typically add ~10-25% new shares
TINY_INCREASE_PCT = 1.0     # below this: option exercises, small top-ups
FREQUENT_SH01S = 4          # this many SH01s in the past year = drip pattern
FOUNDER_WINDOW_DAYS = 90    # SH01s this soon after incorporation = founder shares


# --- Pure logic (no network), easy to test ------------------------------

def cheap_number_check(company_number: str) -> Optional[str]:
    """Return a reason to drop the company, or None to keep it."""
    if not company_number.isdigit():
        return "not an England & Wales company number"
    if int(company_number) < MIN_COMPANY_NUMBER:
        return "company number issued before ~2019 (too old)"
    return None


def postcode_area(postcode: str) -> str:
    match = re.match(r"([A-Z]+)", (postcode or "").strip().upper())
    return match.group(1) if match else ""


def profile_check(profile: dict, today: date) -> tuple:
    """Return (keep: bool, reason: str, sector: str)."""
    if profile.get("company_status") != "active":
        return False, f"status is {profile.get('company_status')}", ""
    address = profile.get("registered_office_address") or {}
    if postcode_area(address.get("postal_code", "")) not in LONDON_POSTCODE_AREAS:
        return False, "registered office not in London", ""
    created = profile.get("date_of_creation")
    if not created or date.fromisoformat(created) < today - timedelta(days=365 * MAX_AGE_YEARS):
        return False, f"incorporated over {MAX_AGE_YEARS} years ago", ""
    sics = profile.get("sic_codes") or []
    if any(s in TECH_SIC_CODES for s in sics):
        return True, "", "tech"
    if any(s in HOLDING_SIC_CODES for s in sics):
        return True, "", "holding company (sector unclear)"
    return False, "not a tech SIC code", ""


def capital_amounts(capital: list) -> dict:
    """[{'currency': 'GBP', 'figure': '2,764.95'}] -> {'GBP': 2764.95}"""
    amounts = {}
    for c in capital or []:
        try:
            amounts[c["currency"]] = float(str(c["figure"]).replace(",", ""))
        except (KeyError, ValueError):
            continue
    return amounts


def effective_date(item: dict) -> str:
    """SH01s: the allotment date. Anything else: the filing date."""
    if item.get("type") == "SH01":
        return (item.get("description_values") or {}).get("date") or item.get("date", "")
    return item.get("date", "")


def previous_capital(history_items: list, sh01: dict) -> dict:
    """Most recent share capital recorded BEFORE this allotment."""
    before = [
        i for i in history_items
        if (i.get("description_values") or {}).get("capital")
        and i.get("transaction_id") != sh01["filing_id"]
        and not i.get("type", "").startswith("RP")   # corrections
        and effective_date(i) < (sh01["allotment_date"] or sh01["filing_date"])
    ]
    if not before:
        return {}
    latest = max(before, key=effective_date)
    return capital_amounts(latest["description_values"]["capital"])


def percent_increase(new: dict, old: dict) -> Optional[float]:
    """Biggest % increase across currencies both statements share."""
    changes = [(new[c] - old[c]) / old[c] * 100
               for c in new if c in old and old[c] > 0]
    return round(max(changes), 4) if changes else None


def days_between(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def score_funding_round(sh01: dict, history_items: list, incorporated: str) -> dict:
    """Score how much this SH01 looks like a funding round.
    Returns flag (likely / uncertain / unlikely), score, % increase and reasons."""
    score, reasons = 0, []
    anchor = sh01["allotment_date"] or sh01["filing_date"]

    pct = percent_increase(capital_amounts(sh01["capital"]),
                           previous_capital(history_items, sh01))
    if pct is None:
        reasons.append("no earlier capital figure to compare")
    elif pct >= BIG_INCREASE_PCT:
        score += 2
        reasons.append(f"share capital up {pct}%")
    elif pct >= TINY_INCREASE_PCT:
        score += 1
        reasons.append(f"share capital up {pct}% (modest)")
    else:
        score -= 2
        reasons.append(f"share capital up only {pct}% (looks like options/top-up)")

    nearby = [i for i in history_items
              if i.get("date") and days_between(i["date"], anchor) <= WINDOW_DAYS]
    if any(i.get("category") == "resolution" or i.get("type") == "MA" for i in nearby):
        score += 2
        reasons.append("new resolutions/articles filed nearby")
    if any(i.get("type") in ("SH08", "SH10") for i in nearby):
        score += 1
        reasons.append("new share class / rights changed nearby")

    year_ago = (date.fromisoformat(anchor) - timedelta(days=365)).isoformat()
    recent_sh01s = [i for i in history_items
                    if i.get("type") == "SH01" and i.get("date", "") >= year_ago]
    if len(recent_sh01s) >= FREQUENT_SH01S:
        score -= 1
        reasons.append(f"{len(recent_sh01s)} SH01s in the past year (drip pattern)")

    if incorporated and days_between(anchor, incorporated) <= FOUNDER_WINDOW_DAYS:
        score -= 2
        reasons.append("allotted within 90 days of incorporation (founder shares?)")

    flag = "likely" if score >= 3 else "uncertain" if score >= 1 else "unlikely"
    return {"flag": flag, "score": score, "pct_increase": pct, "reasons": "; ".join(reasons)}


# --- Running it -----------------------------------------------------------

def load_assessed() -> dict:
    if not ASSESSED_FILE.exists():
        return {}
    rows = [json.loads(l) for l in ASSESSED_FILE.read_text().splitlines() if l.strip()]
    return {r["filing_id"]: r for r in rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Filter and score collected SH01s.")
    parser.add_argument("--limit", type=int, help="only check this many new SH01s")
    args = parser.parse_args(argv)

    today = date.today()
    assessed = load_assessed()
    todo = [s for s in load_sh01s() if s["filing_id"] not in assessed]
    if args.limit:
        todo = todo[:args.limit]
    cache = json.loads(PROFILE_CACHE.read_text()) if PROFILE_CACHE.exists() else {}
    funnel = {"checked": len(todo), "number": 0, "profile": 0, "scored": 0}
    print(f"{len(todo)} new SH01s to check...")

    try:
        client = CompaniesHouseClient()
    except CompaniesHouseError as err:
        print(f"Error: {err}")
        return 1

    DATA_DIR.mkdir(exist_ok=True)
    try:
        with ASSESSED_FILE.open("a") as out:
            for n, sh01 in enumerate(todo, 1):
                row = dict(sh01)
                drop = cheap_number_check(sh01["company_number"])
                if drop:
                    funnel["number"] += 1
                else:
                    profile = cache.get(sh01["company_number"]) or client.company_profile(sh01["company_number"])
                    if profile:
                        cache[sh01["company_number"]] = profile
                    keep, drop, sector = profile_check(profile or {}, today) if profile else (False, "profile not found", "")
                    if not keep:
                        funnel["profile"] += 1
                    else:
                        history = client.filing_history(sh01["company_number"], items_per_page=100)
                        result = score_funding_round(sh01, (history or {}).get("items", []),
                                                     profile.get("date_of_creation"))
                        funnel["scored"] += 1
                        row.update(result, sector=sector,
                                   company_name=profile.get("company_name"),
                                   sic_codes=profile.get("sic_codes", []),
                                   address=profile.get("registered_office_address", {}),
                                   incorporated=profile.get("date_of_creation"))
                        drop = None
                row["dropped_because"] = drop
                out.write(json.dumps(row) + "\n")
                if n % 100 == 0:
                    print(f"  ...{n} checked ({client.requests_made} API requests so far)")
    except CompaniesHouseError as err:
        print(f"Error: {err} (progress so far is saved; run again to continue)")
        return 1
    finally:
        PROFILE_CACHE.write_text(json.dumps(cache))

    scored = [r for r in load_assessed().values() if r.get("flag")]
    print(f"\nFunnel for this run ({client.requests_made} API requests):")
    print(f"  {funnel['checked']} SH01s checked")
    print(f"  -{funnel['number']} dropped by company number (too old / not E&W)")
    print(f"  -{funnel['profile']} dropped by profile (not active, London, tech, or young)")
    print(f"  = {funnel['scored']} London tech startups scored")
    for flag in ("likely", "uncertain", "unlikely"):
        rows = [r for r in scored if r["flag"] == flag]
        print(f"\n{flag.upper()} ({len(rows)} so far):")
        for r in sorted(rows, key=lambda r: -r["score"])[:15]:
            print(f"  {r['company_name']} ({r['company_number']}) score {r['score']}: {r['reasons']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
