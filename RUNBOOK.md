# Runbook

## Daily routine (after 15:45 IST on each trading day)
1. `python3 -I engine/papertrade.py` (today) and check every strategy produced a result.
2. Add Shivansh's and Pranjal's days to `data/benchmark.json` if they posted (Pranjal's numbers are for ₹2L; store them as posted, the dashboard halves them for grading).
3. Review trades; write any proposed rule change below with the date it takes effect (next trading day at the earliest).
4. Commit and push; GitHub Pages redeploys the dashboard.

## Rule changes
- 2026-10-28 (before Day 1 replay): per-trade risk capped at ₹1,500 at the stop-loss. The original plan's ₹30k position with a 30% stop could lose ₹9k on one trade, three times the ₹3k daily stop. Stop is 20% of premium, tightened when one lot costs more; trades needing a stop under 10% are skipped. Target 2R, trail after +1R giving back ½R.

- 2026-10-28: added Pranjal (@pranjalsoni_) as a second benchmark, starting 29 Oct. No strategy rules changed.

## Ideas from other experiments (not adopted)
- Pranjal: max 3 trades a day (ours allows 5 round trips) and a Supertrend strategy. Revisit after Day 5 if our charges or overtrading look like the problem.

## Open questions
- Exchange holiday list in `engine/papertrade.py` (`HOLIDAYS`) needs checking against the NSE/BSE 2026 calendar.
- Yahoo keeps 1-minute data for about 7 days; a missed evening must be replayed within that window.
- Model pricing on Sensex 0DTE may run high. On 29 Oct the model priced 73400 CE at ₹308 at 09:39. Shivansh's real average buy on 73500 CE (100 points further out, two entries 09:40 and 10:07) was ₹219. Moneyness explains roughly ₹40–50 of the gap. Watch the next expiry days; if the model keeps overpricing, lower IV on expiry day (effective from the next trading day, logged here).
- Pranjal switched on 29 Oct from a ₹2L options plan to ₹1L real money on intraday stocks. His row is no longer an options comparison; it stays on the dashboard as a loose reference.
