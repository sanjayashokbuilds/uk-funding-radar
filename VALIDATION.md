# Validation week

**Question:** of the companies the radar flags as "likely" or "uncertain",
how many really raised money? And how many publicly announced London rounds
did the radar miss?

**Period:** 2026-10-19 to 2026-10-25 (7 days of daily runs)

## Method

1. Run `python -m radar` every morning and keep each day's CSV.
2. For each "likely" company, and a sample of "uncertain" ones, search for
   funding news (UKTN, Sifted, TechCrunch, the company's LinkedIn or blog).
   Record whether a round was announced, when, and how much.
3. From the week's funding roundups (e.g. UKTN's weekly round-up), list every
   **London** round announced. Check whether the radar caught each one. For
   any it missed, note why from the README limitations list (SAFE, overseas
   parent, not London, non-tech SIC, filed late).
4. Count the days between the SH01 filing date and the first public announcement.

## Results

### Flagged companies

First run: 19 Oct 2026 (filings from 5 to 18 Oct). "Not found yet" means no announcement turned up in a quick search on the date checked; recheck daily.

| Company | Flag | Confirmed round? | Source | Announced date | Days earlier than press |
|---|---|---|---|---|---|
| Mint Neurotechnologies (MintNeuro) | likely | Yes: $5m, led by Odyssey Ventures | [Pulse 2.0](https://pulse2.com/mintneuro-raises-5-million-to-scale-semiconductor-platform-for-neural-devices/) | 2026-10-13 | 4 (SH01 filed 2026-10-09) |
| Secure Agentics | likely | Not found yet (19 Oct). An earlier first round was reported in Aug 2026, amount undisclosed | [Jersey Evening Post](https://jerseyeveningpost.com/business/2026/08/05/fighting-the-good-fight-in-the-rapidly-changing-world-of-ai/) | | |
| Pro'Tech Rugby | likely | Not found yet (19 Oct) | | | |
| HALR Tech Group | likely | Not found yet (19 Oct) | | | |
| Conduct AI | likely | Not found yet (19 Oct) | | | |
| Workfree | likely | Not found yet (19 Oct) | | | |
| Nexus KPI | likely | Not found yet (19 Oct) | | | |
| Consensus Foods | likely | Not found yet (19 Oct) | | | |
| CrossSense | uncertain | Not found yet (19 Oct). Won the £1m Longitude Prize in Mar 2026 (a prize, not equity); a new director joined on the allotment date | [Laboratory News](https://labnews.co.uk/?p=241556) | | |

### Announced London rounds

| Company | Round | Caught by radar? | If missed, why |
|---|---|---|---|
| | | | |

## Summary

- **Precision ("likely"):** _confirmed_ / _flagged_ = _%_
- **Precision ("uncertain" sample):** _confirmed_ / _checked_ = _%_
- **Recall:** _caught_ / _announced London rounds_ = _%_
- **Median lead time over press:** _x_ days
- **Main reasons for misses:**
- **Rule changes this suggests:**
