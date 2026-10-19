# UK Funding Radar

Spots London tech startups that have just issued new shares, often before
the funding round is in the press, using free public data from Companies House.

## The problem

Startups that have just raised money are hiring, buying and building. That
makes it the best moment to approach them, whether you're looking for a job,
selling a service or tracking a market. But funding news usually appears
weeks later, if at all, and paid databases are expensive.

There is a public signal much earlier. When a UK company issues new shares,
it must file a form called an **SH01** (a "statement of capital following an
allotment of shares") at Companies House within a month. A priced funding
round always produces one.

The catch: most SH01s are **not** funding rounds. They are also filed for
employee option exercises, founder share issues and corporate restructurings.
The interesting part of this project is separating the two.

## How it works

One command, `python -m radar`, runs three steps:

```
Companies House           1. COLLECT           2. FILTER & SCORE            3. EXPORT
filings stream  ───▶  keep only SH01s  ───▶  London? tech? <5 yrs?  ───▶  add current directors,
(every UK filing)     save position for      does it look like a          write a dated CSV
                      tomorrow               funding round?
```

**1. Collect** (`radar/stream.py`). Reads the Companies House **Streaming API**,
a live feed of every filing in the UK, and keeps only SH01s. It saves its
position (a "timepoint"), so each morning it carries on exactly where it stopped.

**2. Filter and score** (`radar/filters.py`). This is a funnel, with the cheapest checks first:

| Step | Cost | Keeps |
|---|---|---|
| Filing date | free | filed in the last 14 days (the stream also re-sends old filings when they're updated) |
| Company number | free | numbers are issued in sequence, so old numbers and Scottish/NI companies are dropped without an API call |
| Company profile | 1 request | active, London postcode, tech SIC code (software, IT, data, R&D), incorporated in the last 5 years |
| Filing history | 1 request | scored for how much this looks like a funding round |

The score uses only what the filing history shows:

| Signal | Points | Why |
|---|---|---|
| Share capital up 5–500% | +2 | priced rounds typically add 10–25% new shares |
| Share capital up 1–5% | +1 | could be a small round |
| Share capital up under 1% | −2 | typical of option exercises |
| Share capital up over 500% | 0 | too big for a normal round; usually a shell or restructuring |
| New resolutions or articles within 45 days | +2 | investors almost always require new articles |
| New share class within 45 days | +1 | e.g. preferred shares for investors |
| 4+ SH01s in the past year | −1 | drip pattern of option exercises |
| Within 90 days of incorporation | −2 | probably founder shares |
| Name like BIDCO, TOPCO, INVESTCO | −3 | buyout or fund vehicle, not a startup |

**3 or more = likely, 1–2 = uncertain, 0 or less = unlikely.** Uncertain
results are kept and flagged, not dropped. Holding companies (SIC 64209/70100)
are kept, because many startups raise at holding-company level, but they can
never be rated higher than "uncertain".

**3. Export** (`radar/export.py`). Adds current directors (names and appointment
dates only) and writes `output/funding_radar_<date>.csv`, one row per company,
containing only filings you haven't seen before.

All requests are paced at no more than 2 per second, which is Companies House's
limit of 600 per 5 minutes, so the tool can't exceed it.

## Example output

*Fake data, for illustration.*

| company_name | likely_funding_round | score | reason | share_capital_increase_pct | allotment_date | directors |
|---|---|---|---|---|---|---|
| EXAMPLE ROBOTICS LTD | likely | 4 | share capital up 18.2%; new resolutions/articles filed nearby | 18.2 | 2026-10-02 | SMITH, Jane (appointed 2023-01-10) |
| SAMPLE DATA LABS LTD | uncertain | 2 | no earlier capital figure to compare; new resolutions/articles filed nearby | | 2026-09-28 | DOE, John (appointed 2025-03-01) |
| DEMO HOLDINGS LIMITED | uncertain | 2 | share capital up 22.6%; holding company, so capped at uncertain | 22.6 | 2026-10-05 | ROE, Alex (appointed 2024-08-30) |

The CSV also includes company number, SIC codes, sector, registered address,
incorporation date, filing date, number of SH01s in the batch, and a link to
the Companies House page.

## Setup

You need Python 3.9+ and two free keys from the
[Companies House developer hub](https://developer.company-information.service.gov.uk/).
Create a **Live** application, then add a **REST** key and a **Streaming** key to it.

```bash
git clone https://github.com/<your-username>/uk-funding-radar.git
cd uk-funding-radar
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste both keys into .env
```

## Usage

```bash
python -m radar                    # the whole morning run
```

Useful extras:

```bash
python -m radar.lookup 15396489    # inspect one company
python -m radar.export --tech-only # leave holding companies out of the CSV
python -m radar.filters --rescore  # re-score everything after changing the rules
```

The first run rewinds as far as Companies House allows (about 1 million events)
and takes around 30 minutes. Daily runs take a few minutes.

Run the tests (no API key or internet needed):

```bash
pip install -r requirements-dev.txt
pytest
```

## How it was tested

The first live run (19 October 2026) read about 1,000,000 filing events in
under 3 minutes and found 3,355 SH01s. The funnel narrowed these to 373 London
tech companies and **30 "likely" funding rounds**.

Reviewing that list exposed false positives, which led to rule changes. Each
one is in the commit history and covered by a test:

- **Private-equity buyout shells** (e.g. names ending BIDCO or TOPCO) showed
  share capital increases above 70,000%. Fixed with the deal-vehicle name rule
  and the 500% cap.
- **Non-tech holding companies** got in through the holding-company SIC codes.
  Fixed by capping them at "uncertain".
- **One round filed as several SH01s** appeared as duplicates. Fixed with one
  row per company.
- **Old filings re-sent by the stream** (one was from April 2025). Fixed with
  the 14-day filing-date check.

After the fixes there were 8 "likely" companies. A one-week comparison against
published funding news is in [docs/VALIDATION.md](docs/VALIDATION.md).

## Limitations

What the SH01 signal **misses**:

- **Convertible notes, SAFEs and ASAs.** These create no new shares until they
  convert, so there's no SH01. Many pre-seed and some seed rounds are raised this way.
- **Rounds at a parent company outside the UK**, e.g. a US Delaware parent with a UK subsidiary.
- **Late or batched filings.** SH01s are due within a month, but some arrive
  months late. The tool shows both the allotment date and the filing date.
- **Companies registered at an address outside London** (often their accountant's), and
  **tech companies using non-tech SIC codes.**
- **Days the laptop was off for too long.** The stream only rewinds about 1
  million events. The tool warns you if it can't catch up.

Where it gives **false positives**:

- **Large option grants or employee share schemes** can look like a round.
- **Modest increases plus new articles** (1–5%) can be an angel top-up or a
  small round. These are the most common borderline "likely" results.
- **Holding companies** fill much of the "uncertain" list. Use `--tech-only` if
  you only want clear tech companies.

What it **can't tell you**:

- **How much was raised.** The API gives only nominal share capital (e.g.
  £0.0001 per share), not the share premium where the money actually sits. That
  is in the filed PDF.
- **The first round's increase.** Many companies have no earlier capital
  figure in the API data, so it can't be compared. These are marked rather than guessed.

The thresholds (5%, 45 days, 500%) are judgement calls. The validation week
is how they get tested.

## What I'd do next

1. **Read the SH01 PDF** (Companies House Document API) to get the amount paid
   per share, which gives the actual amount raised and removes most false positives.
2. **Tune the thresholds against a labelled sample** of past rounds, and
   measure precision and recall properly.
3. **Add a news check** that searches each "likely" company name to see whether
   the round is already public.
4. **Run it on a schedule** (e.g. a small cloud machine) so it doesn't depend on a laptop.

## Data and privacy

All data is public, from Companies House under the Open Government Licence.
Directors' names are personal data, so the tool exports only names and
appointment dates (no dates of birth or addresses). The output files and raw
data stay local: `output/`, `data/` and `.env` are gitignored and never committed.

## Licence

MIT. See [LICENSE](LICENSE).
