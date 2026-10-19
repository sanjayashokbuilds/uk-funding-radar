# Validation week

**Question:** of the companies the radar flags as "likely" or "uncertain",
how many really raised money? And how many publicly announced London rounds
did the radar miss?

**Period:** _start date_ to _end date_ (7 days of daily runs)

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

| Company | Flag | Confirmed round? | Source | Announced date | Days earlier than press |
|---|---|---|---|---|---|
| | | | | | |

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
