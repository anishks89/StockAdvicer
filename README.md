# Stock Shortlist

A personal, rule-based screen of the Nifty 500. A scheduled job downloads daily
prices, applies four fixed rules, and publishes the result as a small web page.

**This is not investment advice.** The page lists stocks that meet mechanical
rules. It does not predict prices and is not a recommendation to buy or sell.
The author is not a SEBI-registered adviser.

## How it works

| Piece | What it does |
|---|---|
| `screen.py` | Fetches one year of daily prices per stock from Yahoo Finance, applies the rules, writes `docs/data.json`. One dependency, `curl_cffi`. |
| `symbols.txt` | Nifty 500 symbols. Refreshed from NSE when NSE answers. |
| `docs/index.html` | Static page that reads `data.json`. Served by GitHub Pages. |
| `.github/workflows/screen.yml` | Runs the screen at 11:28 AM IST on weekdays and commits the result. |

## The rules

1. **Steady uptrend** (the main shortlist): price above the 50-day average, 50-day above the 200-day, traded value in the top half of the index, ranked by the smallest price swings over 3 months.
2. **Momentum**: same uptrend, within 5% of the 52-week high, ranked by 3-month return.
3. **Pullback in an uptrend**: above the 200-day, within 3% of the 50-day, at least 5% below the 20-day high.
4. **Beaten down**: within 5% of the 52-week low with 14-day RSI below 30.

Change the rules in `build()` in `screen.py`.

## Running it

```bash
pip install curl_cffi
python screen.py           # writes docs/data.json if the market traded today
python screen.py --force   # write even on a holiday or weekend
```

To run it on GitHub outside the schedule: Actions → Daily screen → Run workflow.

## Setup (once)

Settings → Pages → Source: "Deploy from a branch" → Branch `main`, folder `/docs` → Save.

## Do not commit

No holdings, quantities, account numbers, broker exports, or API tokens. This
repository is public and git history is permanent.
