# Paper trading log

Rule-based paper trading of Nifty/Sensex weekly ATM options, replayed each evening on real 1-minute index data and compared with [Shivansh's real-money Fable 5.1 experiment](https://x.com/shivanshco/status/2115064439972249723).

Dashboard: https://rohan-patnaik.github.io/trading-plan/

- `engine/papertrade.py` replays a day (`python3 -I engine/papertrade.py 2026-10-29`) and rebuilds `data/summary.json`. Python 3 standard library only.
- `data/benchmark.json` holds Shivansh's posted daily results; add each day by hand from his thread.
- `RUNBOOK.md` records every rule change and the date it took effect. Rules never change in the middle of a day.

No broker connection and no real orders. Option prices are modelled (Black-Scholes, India VIX as IV), not real quotes.
