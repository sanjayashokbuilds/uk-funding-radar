"""Stage 3: read the Companies House filings stream and collect SH01s.

How it works (each run):
1. "Peek" at the live stream to learn the current position (timepoint).
   That is our finish line for this run.
2. Reconnect from where we stopped last time (saved in data/stream_state.json).
   On the very first run there is no saved position, so we rewind as far as
   Companies House allows and start from there.
3. Read every filing event up to the finish line, keep only SH01s, save them
   to data/sh01_events.jsonl, and save our new position for next time.

Why a finish line instead of "stop when the event times look recent"?
Comparing timestamps depends on time zones; comparing timepoints doesn't.

Usage:
    python -m radar.stream
    python -m radar.stream --max-minutes 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterator, Optional

import requests
from dotenv import load_dotenv

STREAM_URL = "https://stream.companieshouse.gov.uk/filings"
DATA_DIR = Path("data")
STATE_FILE = DATA_DIR / "stream_state.json"
SH01_FILE = DATA_DIR / "sh01_events.jsonl"

# How far back to try on the first run. Companies House doesn't document
# its limit, so we try big jumps first and shrink until one is accepted.
REWIND_STEPS = [5_000_000, 2_000_000, 1_000_000, 500_000, 200_000, 100_000, 50_000]


class StreamError(Exception):
    pass


class TimepointTooOld(StreamError):
    pass


# --- Pure logic (no network), easy to test ------------------------------

def parse_sh01(event: dict) -> Optional[dict]:
    """Turn one stream event into a tidy SH01 record, or None if it isn't one.

    Only exact 'SH01' counts. Corrections (RP04SH01, RP01SH01) are
    re-filings of old allotments, not new money.
    """
    if (event.get("event") or {}).get("type") == "deleted":
        return None
    data = event.get("data") or {}
    if data.get("type") != "SH01":
        return None
    # resource_uri looks like '/company/13302625/filing-history/<id>'
    parts = (event.get("resource_uri") or "").split("/")
    if len(parts) < 3 or parts[1] != "company":
        return None
    values = data.get("description_values") or {}
    return {
        "company_number": parts[2],
        "filing_id": event.get("resource_id"),
        "filing_date": data.get("date"),
        "allotment_date": values.get("date"),
        "capital": values.get("capital") or [],
        "timepoint": (event.get("event") or {}).get("timepoint"),
    }


def load_state() -> Optional[int]:
    try:
        return int(json.loads(STATE_FILE.read_text())["timepoint"])
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        return None


def save_state(timepoint: int) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({"timepoint": timepoint}))


def append_sh01s(records: list) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with SH01_FILE.open("a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def load_sh01s() -> list:
    """All SH01s collected so far, one per filing (latest version wins,
    because Companies House sends two events per filing)."""
    if not SH01_FILE.exists():
        return []
    by_id = {}
    for line in SH01_FILE.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            by_id[r["filing_id"]] = r
    return list(by_id.values())


# --- Network -------------------------------------------------------------

def open_stream(key: str, timepoint: Optional[int] = None) -> requests.Response:
    params = {"timepoint": timepoint} if timepoint is not None else None
    # (10s to connect, 90s max silence: the stream sends blank "heartbeat"
    # lines to keep the connection alive, so 90s of nothing means trouble.)
    resp = requests.get(STREAM_URL, params=params, auth=(key, ""),
                        stream=True, timeout=(10, 90))
    if resp.status_code == 200:
        return resp
    resp.close()
    if resp.status_code == 416:
        raise TimepointTooOld(f"Timepoint {timepoint} is too old")
    if resp.status_code == 401:
        raise StreamError("Stream rejected the key (401). Check CH_STREAM_API_KEY "
                          "is the STREAM key, not the REST key.")
    if resp.status_code == 429:
        raise StreamError("Rate limited by the stream (429). Wait a few minutes. "
                          "Also check nothing else is connected with this account "
                          "(max 2 connections).")
    raise StreamError(f"Stream returned {resp.status_code}")


def read_events(resp: requests.Response) -> Iterator[Optional[dict]]:
    """Yield each event as a dict, or None for a heartbeat (blank line)."""
    for line in resp.iter_lines():
        if not line or not line.strip():
            yield None
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue  # skip a garbled line rather than crash


def peek_live_timepoint(key: str) -> int:
    """Connect live, grab the first event's timepoint, disconnect."""
    resp = open_stream(key)
    try:
        for event in read_events(resp):
            if event and (event.get("event") or {}).get("timepoint"):
                return int(event["event"]["timepoint"])
    finally:
        resp.close()
    raise StreamError("Live stream closed before sending any events")


def find_first_run_start(key: str, live_tp: int) -> int:
    """First run only: rewind as far as Companies House will let us."""
    for step in REWIND_STEPS:
        candidate = max(0, live_tp - step)
        try:
            open_stream(key, candidate).close()
            print(f"  First run: rewinding {step:,} events (timepoint {candidate:,})")
            return candidate
        except TimepointTooOld:
            time.sleep(2)  # be gentle between attempts
    print("  First run: couldn't rewind, starting from live")
    return live_tp


def collect(key: str, start_tp: int, finish_tp: int, max_minutes: float) -> dict:
    """Read from start_tp to finish_tp, keeping SH01s. Saves as it goes."""
    resp = open_stream(key, start_tp)
    started = time.monotonic()
    last_tp = start_tp
    events = 0
    batch = []
    stop_reason = "stream ended"
    try:
        for event in read_events(resp):
            if time.monotonic() - started > max_minutes * 60:
                stop_reason = f"time limit ({max_minutes} min); run again to continue"
                break
            if event is None:
                continue
            events += 1
            tp = (event.get("event") or {}).get("timepoint")
            if tp:
                last_tp = int(tp)
            record = parse_sh01(event)
            if record:
                batch.append(record)
            if events % 50_000 == 0:  # checkpoint so a crash loses little
                append_sh01s(batch)
                batch = []
                save_state(last_tp)
                print(f"  ...{events:,} events read, at timepoint {last_tp:,}")
            if last_tp >= finish_tp:
                stop_reason = "caught up"
                break
    finally:
        resp.close()
        append_sh01s(batch)
        save_state(last_tp)
    return {"events": events, "last_tp": last_tp, "stop_reason": stop_reason,
            "seconds": round(time.monotonic() - started)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect SH01s from the filings stream.")
    parser.add_argument("--max-minutes", type=float, default=30,
                        help="stop after this long (progress is saved)")
    args = parser.parse_args(argv)

    load_dotenv()
    key = os.getenv("CH_STREAM_API_KEY", "").strip()
    if not key:
        print("Error: no stream key. Add CH_STREAM_API_KEY to .env")
        return 1

    before = {r["filing_id"] for r in load_sh01s()}
    try:
        print("Checking the live position...")
        live_tp = peek_live_timepoint(key)
        start_tp = load_state()
        if start_tp is None:
            start_tp = find_first_run_start(key, live_tp)
        print(f"Reading from {start_tp:,} to {live_tp:,} "
              f"({max(0, live_tp - start_tp):,} events)...")
        if start_tp >= live_tp:
            print("Already up to date.")
            return 0
        try:
            result = collect(key, start_tp, live_tp, args.max_minutes)
        except TimepointTooOld:
            print("Warning: last saved position is too old (laptop off too long?). "
                  "Some filings were missed. Restarting from the furthest point allowed.")
            start_tp = find_first_run_start(key, live_tp)
            result = collect(key, start_tp, live_tp, args.max_minutes)
    except (StreamError, requests.RequestException) as err:
        print(f"Error: {err}")
        return 1

    all_sh01s = load_sh01s()
    new = [r for r in all_sh01s if r["filing_id"] not in before]
    print(f"\nDone: {result['stop_reason']}. Read {result['events']:,} events "
          f"in {result['seconds']}s.")
    print(f"New SH01s this run: {len(new)} (total collected: {len(all_sh01s)})")
    for r in sorted(new, key=lambda r: r["filing_date"] or "")[-10:]:
        cap = "; ".join(f"{c.get('currency')} {c.get('figure')}" for c in r["capital"])
        print(f"  {r['filing_date']}  {r['company_number']}  allotted {r['allotment_date']}  capital {cap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
