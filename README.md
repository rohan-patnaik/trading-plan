# Paper trading log

Rule-based paper trading of Nifty/Sensex weekly ATM options, replayed each evening on real 1-minute index data and compared with two public AI trading experiments: [Shivansh](https://x.com/shivanshco/status/2115064439972249723) (real money, Fable 5.1) and [Pranjal](https://x.com/pranjalsoni_/status/2115423231343722789) (Claude, ₹2L, paper in week 1).

Dashboard: https://rohan-patnaik.github.io/trading-plan/

- `engine/papertrade.py` replays a day (`python3 -I engine/papertrade.py 2026-10-29`) and rebuilds `data/summary.json`. Python 3 standard library only.
- `data/benchmark.json` holds each benchmark's posted daily results (`benchmarks[].days`); add each day by hand from their threads.
- `RUNBOOK.md` records every rule change and the date it took effect. Rules never change in the middle of a day.

No broker connection and no real orders. Option prices are modelled (Black-Scholes, India VIX as IV), not real quotes.
