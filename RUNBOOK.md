# Runbook

## Daily routine (after 15:45 IST on each trading day)
1. `python3 -I engine/papertrade.py` (today) and check every strategy produced a result.
2. Add Shivansh's day to `data/benchmark.json` if he posted it.
3. Review trades; write any proposed rule change below with the date it takes effect (next trading day at the earliest).
4. Commit and push; GitHub Pages redeploys the dashboard.

## Rule changes
- 2026-10-28 (before Day 1 replay): per-trade risk capped at ₹1,500 at the stop-loss. The original plan's ₹30k position with a 30% stop could lose ₹9k on one trade, three times the ₹3k daily stop. Stop is 20% of premium, tightened when one lot costs more; trades needing a stop under 10% are skipped. Target 2R, trail after +1R giving back ½R.

## Open questions
- Exchange holiday list in `engine/papertrade.py` (`HOLIDAYS`) needs checking against the NSE/BSE 2026 calendar.
- Yahoo keeps 1-minute data for about 7 days; a missed evening must be replayed within that window.
