"""Tests for reading stream events and building CSV rows. No network needed."""
from radar.client import current_directors, normalise_company_number
from radar.export import best_per_company, format_address
from radar.stream import parse_sh01


def event(form_type, event_type="changed"):
    return {"resource_uri": "/company/12345678/filing-history/abc", "resource_id": "abc",
            "data": {"type": form_type, "date": "2026-10-18",
                     "description_values": {"date": "2026-10-10",
                                            "capital": [{"currency": "GBP", "figure": "1.5"}]}},
            "event": {"timepoint": 100, "type": event_type}}


def test_parse_sh01_keeps_only_real_sh01s():
    record = parse_sh01(event("SH01"))
    assert record["company_number"] == "12345678"
    assert record["allotment_date"] == "2026-10-10"
    assert parse_sh01(event("RP04SH01")) is None   # correction, not new money
    assert parse_sh01(event("CS01")) is None
    assert parse_sh01(event("SH01", "deleted")) is None


def test_normalise_company_number():
    assert normalise_company_number("6") == "00000006"
    assert normalise_company_number(" sc123456 ") == "SC123456"


def test_current_directors_excludes_resigned_and_secretaries():
    officers = {"items": [
        {"name": "A", "officer_role": "director"},
        {"name": "B", "officer_role": "director", "resigned_on": "2024-01-01"},
        {"name": "C", "officer_role": "secretary"}]}
    assert [d["name"] for d in current_directors(officers)] == ["A"]


def test_one_row_per_company_keeps_best_score():
    rows = [{"company_number": "1", "filing_id": "a", "score": 1},
            {"company_number": "1", "filing_id": "b", "score": 4},
            {"company_number": "2", "filing_id": "c", "score": 2}]
    best = {r["company_number"]: r for r in best_per_company(rows)}
    assert best["1"]["filing_id"] == "b" and best["1"]["filings_count"] == 2
    assert best["2"]["filings_count"] == 1


def test_format_address_skips_blanks():
    assert format_address({"address_line_1": "1 Test St", "address_line_2": "",
                           "locality": "London", "postal_code": "EC1A 1AA"}) \
        == "1 Test St, London, EC1A 1AA"
