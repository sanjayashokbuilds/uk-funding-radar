"""Tests for the filtering and scoring rules. No network needed.

Each scoring test is a real pattern seen in the first live run.
"""
from datetime import date

from radar.filters import (cheap_number_check, percent_increase, postcode_area,
                           profile_check, score_funding_round, stale_filing_check)

TODAY = date(2026, 10, 19)


def sh01(allotted, figure, filing_id="new"):
    return {"filing_id": filing_id, "allotment_date": allotted, "filing_date": allotted,
            "capital": [{"currency": "GBP", "figure": figure}]}


def earlier_sh01(day, figure, tid):
    return {"transaction_id": tid, "type": "SH01", "date": day, "category": "capital",
            "description_values": {"date": day, "capital": [{"currency": "GBP", "figure": figure}]}}


RESOLUTION = {"transaction_id": "r", "type": "RESOLUTIONS", "date": "2026-10-01",
              "category": "resolution"}


def test_priced_round_scores_likely():
    history = [earlier_sh01("2025-01-01", "100", "a"), RESOLUTION]
    result = score_funding_round(sh01("2026-10-05", "120"), history, "2024-01-01", "ACME AI LTD")
    assert result["flag"] == "likely"
    assert result["pct_increase"] == 20.0


def test_option_exercise_drip_scores_unlikely():
    # Bloom & Wild pattern: many SH01s, each adding a fraction of a penny
    history = [earlier_sh01(d, f, t) for d, f, t in [
        ("2026-02-12", "2,764.9383", "a"), ("2026-01-13", "2,764.9342", "b"),
        ("2025-12-14", "2,764.9334", "c"), ("2025-11-14", "2,764.9244", "d")]]
    result = score_funding_round(sh01("2026-02-27", "2,764.9568"), history, "2021-03-30")
    assert result["flag"] == "unlikely"
    assert "drip pattern" in result["reasons"]


def test_buyout_shell_is_not_likely():
    history = [earlier_sh01("2025-01-01", "1", "a"), RESOLUTION]
    result = score_funding_round(sh01("2026-10-05", "3951"), history, "2024-01-01",
                                 "ZEUS UK BIDCO LIMITED")
    assert result["flag"] == "unlikely"


def test_founder_shares_soon_after_incorporation():
    history = [earlier_sh01("2026-09-01", "1", "a")]
    result = score_funding_round(sh01("2026-10-01", "1.2"), history, "2026-09-01")
    assert "founder shares" in result["reasons"]
    assert result["flag"] != "likely"


def test_holding_company_capped_at_uncertain():
    history = [earlier_sh01("2025-01-01", "100", "a"), RESOLUTION]
    result = score_funding_round(sh01("2026-10-05", "120"), history, "2024-01-01",
                                 "SOMETHING HOLDINGS LIMITED", "holding company (sector unclear)")
    assert result["flag"] == "uncertain"


def test_missing_previous_capital_is_flagged_not_guessed():
    result = score_funding_round(sh01("2026-10-05", "120"), [RESOLUTION], "2024-01-01")
    assert result["pct_increase"] is None
    assert "no earlier capital figure" in result["reasons"]


def test_percent_increase_uses_shared_currencies_only():
    assert percent_increase({"GBP": 120.0, "USD": 5.0}, {"GBP": 100.0}) == 20.0
    assert percent_increase({"USD": 5.0}, {"GBP": 100.0}) is None


def test_old_filing_resent_by_stream_is_dropped():
    old = dict(sh01("2025-04-16", "1"), filing_date="2025-04-30", collected_on="2026-10-19")
    assert stale_filing_check(old, TODAY)
    fresh = dict(sh01("2026-10-15", "1"), collected_on="2026-10-19")
    assert stale_filing_check(fresh, TODAY) is None


def test_company_number_prefilter():
    assert cheap_number_check("07124544")       # issued long ago
    assert cheap_number_check("SC123456")       # Scottish
    assert cheap_number_check("16321995") is None


def test_london_postcodes():
    assert postcode_area("EC2A 4NE") == "EC"
    assert postcode_area("sw1a 1aa") == "SW"
    assert postcode_area("") == ""


def test_profile_check():
    profile = {"company_status": "active", "date_of_creation": "2023-01-10",
               "registered_office_address": {"postal_code": "EC2A 4NE"},
               "sic_codes": ["62012"]}
    assert profile_check(profile, TODAY) == (True, "", "tech")
    derby = dict(profile, registered_office_address={"postal_code": "DE1 1AA"})
    assert profile_check(derby, TODAY)[0] is False
    old = dict(profile, date_of_creation="2015-01-01")
    assert profile_check(old, TODAY)[0] is False
    bakery = dict(profile, sic_codes=["10710"])
    assert profile_check(bakery, TODAY)[0] is False
