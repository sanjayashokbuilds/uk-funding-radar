"""A small, polite client for the Companies House REST API.

Why it looks like this:
- Companies House allows 600 requests per 5 minutes (= 2 per second).
  We never send faster than one request every 0.5 seconds, so we can't
  break the limit even on a long run.
- If we still get a 429 (rate limited), we wait until the limit resets
  and try again, instead of hammering the API.
- The API key is read from .env (never from the code), as Companies House's
  developer guidelines require.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.company-information.service.gov.uk"

# 600 requests / 300 seconds = 2 per second, so at most one every 0.5s.
MIN_SECONDS_BETWEEN_REQUESTS = 0.5


class CompaniesHouseError(Exception):
    """Raised when Companies House returns something we can't handle."""


def normalise_company_number(raw: str) -> str:
    """Company numbers are always 8 characters, e.g. '6' -> '00000006'.

    Scottish/NI numbers start with letters (SC123456, NI123456) and are
    already 8 characters, so we only pad purely numeric ones.
    """
    number = raw.strip().upper().replace(" ", "")
    if number.isdigit():
        number = number.zfill(8)
    return number


class CompaniesHouseClient:
    def __init__(self, api_key: Optional[str] = None,
                 min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS):
        load_dotenv()
        self.api_key = api_key or os.getenv("CH_REST_API_KEY", "").strip()
        if not self.api_key:
            raise CompaniesHouseError(
                "No REST API key found. Copy .env.example to .env and paste "
                "your key after CH_REST_API_KEY="
            )
        self.session = requests.Session()
        # Companies House uses HTTP Basic auth: key as username, blank password.
        self.session.auth = (self.api_key, "")
        self.session.headers["Accept"] = "application/json"
        self.min_interval = min_interval
        self._last_request = 0.0
        self.requests_made = 0

    def get(self, path: str, params: Optional[dict] = None,
            max_retries: int = 3) -> Optional[dict]:
        """GET a path like '/company/00000006'. Returns parsed JSON,
        or None if the thing doesn't exist (404)."""
        for attempt in range(max_retries + 1):
            self._wait_for_turn()
            response = self.session.get(BASE_URL + path, params=params, timeout=30)
            self.requests_made += 1

            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                return None
            if response.status_code == 401:
                raise CompaniesHouseError(
                    "Companies House rejected the key (401). Check it is the "
                    "REST key (not the stream key), from a Live application."
                )
            if response.status_code == 429 and attempt < max_retries:
                time.sleep(self._seconds_until_reset(response))
                continue
            if response.status_code >= 500 and attempt < max_retries:
                time.sleep(5 * 2 ** attempt)  # 5s, 10s, 20s
                continue
            raise CompaniesHouseError(
                f"Companies House returned {response.status_code} for {path}: "
                f"{response.text[:200]}"
            )
        raise CompaniesHouseError(f"Gave up on {path} after {max_retries} retries")

    def _wait_for_turn(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @staticmethod
    def _seconds_until_reset(response: requests.Response) -> int:
        """Companies House sends the reset time as a Unix timestamp header.
        If it's missing or odd, wait a safe 60 seconds."""
        reset = response.headers.get("X-Ratelimit-Reset")
        try:
            return max(1, min(300, int(reset) - int(time.time()) + 1))
        except (TypeError, ValueError):
            return 60

    # --- The three endpoints this project uses --------------------------

    def company_profile(self, company_number: str) -> Optional[dict]:
        return self.get(f"/company/{normalise_company_number(company_number)}")

    def officers(self, company_number: str) -> Optional[dict]:
        return self.get(f"/company/{normalise_company_number(company_number)}/officers",
                        params={"items_per_page": 100})

    def filing_history(self, company_number: str, items_per_page: int = 25,
                       category: Optional[str] = None) -> Optional[dict]:
        params = {"items_per_page": items_per_page}
        if category:
            params["category"] = category
        return self.get(
            f"/company/{normalise_company_number(company_number)}/filing-history",
            params=params,
        )


def current_directors(officers_response: Optional[dict]) -> list:
    """Officers who are directors and haven't resigned."""
    if not officers_response:
        return []
    return [
        o for o in officers_response.get("items", [])
        if "director" in o.get("officer_role", "") and not o.get("resigned_on")
    ]
