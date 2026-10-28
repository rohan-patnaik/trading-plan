"""Paper-trade replay for Nifty/Sensex weekly ATM option buying.

Replays one trading day bar by bar from 1-minute index data (Yahoo Finance),
prices options with Black-Scholes using India VIX as implied volatility, and
applies the same hard risk rules to three strategies, each on its own ₹1L book.
No order ever touches a broker.

Usage:  python3 -I engine/papertrade.py [YYYY-MM-DD ...]   (default: today)
"""
import datetime as dt
import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DAYS = ROOT / "data" / "days"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

CAPITAL = 100_000
# NSE/BSE trading holidays in the replay window. Verify against the exchange
# calendar; a wrong entry only shifts days-to-expiry by one.
HOLIDAYS = {"2026-11-10", "2026-11-24", "2026-12-25"}

INSTRUMENTS = {
    "NIFTY": {"yahoo": "^NSEI", "lot": 65, "step": 50, "expiry_wd": 1, "exch": 0.0003503},
    "SENSEX": {"yahoo": "^BSESN", "lot": 20, "step": 100, "expiry_wd": 3, "exch": 0.000325},
}

RULES = {
    "max_premium_per_position": 30_000,
    "max_risk_per_trade": 1_500,  # loss if the stop-loss is hit; 2 stops = daily loss stop
    "max_orders_per_day": 10,
    "daily_loss_stop": -3_000,
    "max_consecutive_sl": 2,
    "profit_lock_at": 5_000,      # above this, new positions are half size
    "daily_profit_stop": 10_000,
    "no_entry_before": "09:30",
    "last_entry_expiry": "14:45",
    "last_entry_other": "15:00",
    "flat_by": "15:10",
    "vix_min": 11.0,
    "vix_max": 22.0,
    "kill_switch_drawdown": -20_000,
    "sl_pct": 0.20,               # tightened per trade so the stop-loss never costs more than max_risk_per_trade
    "min_sl_pct": 0.10,           # if that would need a stop tighter than this, skip the trade
    "target_r": 2,                # target = 2× the stop distance; trail after +1R, giving back ½R
    "slippage_pct": 0.005,
    "stt_sell_pct": 0.0015,       # conservative: assumes the 2026 Budget STT rise
}

STRATEGIES = {
    "orb": "Opening range breakout (15 min)",
    "ema": "5-min EMA 9/21 trend cross",
    "pm": "Afternoon range break (13:00)",
}


# ---------- data ----------

def fetch_bars(symbol, day):
    cache = RAW / f"{day}_{symbol.strip('^')}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    start = dt.datetime.combine(day, dt.time(9, 0), IST)
    end = dt.datetime.combine(day, dt.time(16, 0), IST)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}"
           f"?interval=1m&period1={int(start.timestamp())}&period2={int(end.timestamp())}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(res.get("timestamp") or []):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        hm = dt.datetime.fromtimestamp(t, IST).strftime("%H:%M")
        if "09:15" <= hm <= "15:29":
            bars.append({"t": hm, "o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": q["close"][i]})
    if bars and dt.datetime.now(IST) > end:
        RAW.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(bars))
    return bars


# ---------- calendar & pricing ----------

def is_trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def instrument_for(d):
    # Trade whichever weekly expiry is nearest: Nifty (Tue) on Mon/Tue/Fri, Sensex (Thu) on Wed/Thu.
    return "SENSEX" if d.weekday() in (2, 3) else "NIFTY"


def expiry_for(name, d):
    wd = INSTRUMENTS[name]["expiry_wd"]
    e = d + dt.timedelta(days=(wd - d.weekday()) % 7)
    while not is_trading_day(e):
        e -= dt.timedelta(days=1)
    if e < d:  # expiry moved before today by a holiday: roll to next week
        e = expiry_for(name, d + dt.timedelta(days=7 - (d.weekday() - wd) % 7))
    return e


def trading_days_between(a, b):
    n, d = 0, a + dt.timedelta(days=1)
    while d <= b:
        n += is_trading_day(d)
        d += dt.timedelta(days=1)
    return n


def minutes_to_close(hm):
    h, m = map(int, hm.split(":"))
    return max(0, 15 * 60 + 30 - (h * 60 + m))


def bs_price(kind, s, k, t_years, iv):
    if t_years <= 0:
        return max(0.0, s - k) if kind == "CE" else max(0.0, k - s)
    v = iv * math.sqrt(t_years)
    d1 = (math.log(s / k) + 0.5 * v * v) / v
    d2 = d1 - v
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    if kind == "CE":
        return s * n(d1) - k * n(d2)
    return k * n(-d2) - s * n(-d1)


def charges(name, buy_val, sell_val):
    brk = min(20, 0.0003 * buy_val) + min(20, 0.0003 * sell_val)
    exch = (buy_val + sell_val) * INSTRUMENTS[name]["exch"]
    sebi = (buy_val + sell_val) * 1e-6
    gst = 0.18 * (brk + exch + sebi)
    stt = sell_val * RULES["stt_sell_pct"]
    stamp = buy_val * 0.00003
    return round(brk + exch + sebi + gst + stt + stamp, 2)


# ---------- signals (all use only bars up to and including i) ----------

def sig_orb(bars, i, st):
    if "orh" not in st:
        first = [b for b in bars if b["t"] < "09:30"]
        st["orh"], st["orl"] = max(b["h"] for b in first), min(b["l"] for b in first)
    if bars[i]["t"] < "09:30" or i == 0:
        return None
    c, p = bars[i]["c"], bars[i - 1]["c"]
    if c > st["orh"] >= p:
        return "CE"
    if c < st["orl"] <= p:
        return "PE"
    return None


def sig_ema(bars, i, st):
    b = bars[i]
    if int(b["t"][-2:]) % 5 != 4:  # act only on the close of each 5-min candle
        return None
    a9, a21 = 2 / 10, 2 / 22
    prev = st.get("ema")
    e9 = b["c"] if prev is None else prev[0] + a9 * (b["c"] - prev[0])
    e21 = b["c"] if prev is None else prev[1] + a21 * (b["c"] - prev[1])
    st["ema"] = (e9, e21)
    st["n"] = st.get("n", 0) + 1
    if prev is None or st["n"] < 6:
        return None
    day_open = bars[0]["o"]
    if prev[0] <= prev[1] and e9 > e21 and b["c"] > day_open:
        return "CE"
    if prev[0] >= prev[1] and e9 < e21 and b["c"] < day_open:
        return "PE"
    return None


def sig_pm(bars, i, st):
    t = bars[i]["t"]
    if t < "13:00":
        return None
    if "h" not in st:
        win = [b for b in bars if "12:30" <= b["t"] < "13:00"]
        if not win:
            return None
        st["h"], st["l"] = max(b["h"] for b in win), min(b["l"] for b in win)
    c, p = bars[i]["c"], bars[i - 1]["c"]
    if c > st["h"] >= p:
        return "CE"
    if c < st["l"] <= p:
        return "PE"
    return None


SIGNALS = {"orb": sig_orb, "ema": sig_ema, "pm": sig_pm}


# ---------- replay ----------

def replay(day, key, bars, vix, cum_before):
    name = instrument_for(day)
    ins = INSTRUMENTS[name]
    expiry = expiry_for(name, day)
    dte = trading_days_between(day, expiry)
    is_expiry = dte == 0
    last_entry = RULES["last_entry_expiry"] if is_expiry else RULES["last_entry_other"]
    vix_at = {b["t"]: b["c"] for b in vix}
    events, trades = [], []
    st, pos = {}, None
    day_net, orders, consec_sl = 0.0, 0, 0
    halted = None

    open_vix = next((vix_at[t] for t in sorted(vix_at) if t >= "09:30"), None)
    if cum_before <= RULES["kill_switch_drawdown"]:
        halted = "Kill switch: book is down ₹20k or more, back to paper review"
    elif open_vix is None:
        halted = "No India VIX data"
    elif not RULES["vix_min"] <= open_vix <= RULES["vix_max"]:
        halted = f"India VIX {open_vix:.1f} outside {RULES['vix_min']:.0f}–{RULES['vix_max']:.0f}: no trades"
    if halted:
        events.append({"t": "09:30", "rule": halted})

    def price(kind, strike, spot, t):
        mins = minutes_to_close(t) + 375 * dte
        iv = (vix_at.get(t) or open_vix or 15) / 100
        return bs_price(kind, spot, strike, mins / (252 * 375), iv)

    def close(i, t, prem, why):
        nonlocal pos, day_net, orders, consec_sl
        exit_px = round(prem * (1 - RULES["slippage_pct"]), 2)
        buy_val, sell_val = pos["entry"] * pos["qty"], exit_px * pos["qty"]
        ch = charges(name, buy_val, sell_val)
        gross = sell_val - buy_val
        net = gross - ch
        day_net += net
        orders += 1
        consec_sl = consec_sl + 1 if why == "stop-loss" else 0
        trades.append({**pos, "exit_t": t, "exit": exit_px, "why": why,
                       "gross": round(gross, 2), "charges": ch, "net": round(net, 2)})
        pos = None

    for i, b in enumerate(bars):
        t = b["t"]
        sig = SIGNALS[key](bars, i, st)  # called every bar so indicator state stays current
        if pos:
            pos_t = pos
            hi_spot, lo_spot = (b["h"], b["l"]) if pos_t["kind"] == "CE" else (b["l"], b["h"])
            p_best = price(pos_t["kind"], pos_t["strike"], hi_spot, t)
            p_worst = price(pos_t["kind"], pos_t["strike"], lo_spot, t)
            p_close = price(pos_t["kind"], pos_t["strike"], b["c"], t)
            stop = pos_t["sl"]
            risk = pos_t["entry"] - pos_t["sl"]
            if pos_t["peak"] >= pos_t["entry"] + risk:  # trail once up 1R, give back at most half of 1R
                stop = max(stop, pos_t["peak"] - risk / 2)
            if p_worst <= stop:  # assume the worse outcome first inside a bar
                close(i, t, stop, "trailing stop" if stop > pos_t["sl"] else "stop-loss")
            elif p_best >= pos_t["target"]:
                close(i, t, pos_t["target"], "target")
            elif t >= RULES["flat_by"]:
                close(i, t, p_close, "time exit")
            else:
                pos_t["peak"] = max(pos_t["peak"], p_best)
            if not pos:
                if day_net <= RULES["daily_loss_stop"] and not halted:
                    halted = f"Daily loss stop hit (₹{day_net:,.0f})"
                    events.append({"t": t, "rule": halted})
                elif consec_sl >= RULES["max_consecutive_sl"] and not halted:
                    halted = "Two stop-losses in a row: done for the day"
                    events.append({"t": t, "rule": halted})
                elif day_net >= RULES["daily_profit_stop"] and not halted:
                    halted = f"Daily profit stop hit (₹{day_net:,.0f})"
                    events.append({"t": t, "rule": halted})
            continue

        if halted or not sig or i + 1 >= len(bars):
            continue
        nt = bars[i + 1]["t"]
        if nt < RULES["no_entry_before"] or nt > last_entry:
            continue
        if orders + 2 > RULES["max_orders_per_day"]:
            if not any(e["rule"].startswith("Order cap") for e in events):
                events.append({"t": t, "rule": "Order cap reached (10 orders)"})
            continue
        spot = bars[i + 1]["o"]
        strike = round(spot / ins["step"]) * ins["step"]
        prem = price(sig, strike, spot, nt) * (1 + RULES["slippage_pct"])
        budget = RULES["max_premium_per_position"]
        if day_net >= RULES["profit_lock_at"]:
            budget /= 2
        lot_cost = prem * ins["lot"]
        lots = int(min(budget, RULES["max_risk_per_trade"] / RULES["sl_pct"]) // lot_cost)
        lots = max(lots, 1 if lot_cost <= budget else 0)
        sl_pct = min(RULES["sl_pct"], RULES["max_risk_per_trade"] / (lots * lot_cost)) if lots else 0
        if lots < 1 or sl_pct < RULES["min_sl_pct"]:
            why = (f"Skipped: 1 lot costs ₹{lot_cost:,.0f}, more than the size cap" if lots < 1 else
                   f"Skipped: 1 lot (₹{lot_cost:,.0f}) would need a stop tighter than {RULES['min_sl_pct']:.0%}")
            if not any(e["rule"].startswith("Skipped") for e in events):
                events.append({"t": nt, "rule": why})
            continue
        qty = lots * ins["lot"]
        entry = round(prem, 2)
        pos = {"kind": sig, "strike": strike, "entry_t": nt, "entry": entry, "qty": qty, "lots": lots,
               "sl": entry * (1 - sl_pct), "target": entry * (1 + 2 * sl_pct),
               "peak": entry, "spot_in": round(spot, 2)}
        orders += 1
        # entry is filled on bar i+1's open; exits are evaluated from bar i+1 on via the loop

    if pos:
        close(len(bars) - 1, bars[-1]["t"], price(pos["kind"], pos["strike"], bars[-1]["c"], bars[-1]["t"]), "time exit")

    for tr in trades:
        tr["sl"] = round(tr["sl"], 2)
        tr["target"] = round(tr["target"], 2)
        tr["peak"] = round(tr["peak"], 2)
    return {
        "strategy": key, "label": STRATEGIES[key], "instrument": name,
        "expiry": expiry.isoformat(), "dte": dte, "open_vix": open_vix,
        "trades": trades, "events": events, "orders": orders,
        "gross": round(sum(t["gross"] for t in trades), 2),
        "charges": round(sum(t["charges"] for t in trades), 2),
        "net": round(day_net, 2), "grade": grade(day_net),
    }


def grade(net):
    pct = net / CAPITAL * 100
    if pct >= 5:
        return "very good"
    if pct >= 1:
        return "good"
    if pct > -1:
        return "average"
    if pct > -3:
        return "bad"
    return "very bad"


def cumulative_before(day):
    cum = {k: 0.0 for k in STRATEGIES}
    for f in sorted(DAYS.glob("*.json")):
        if f.stem >= day.isoformat():
            break
        for s in json.loads(f.read_text())["strategies"]:
            cum[s["strategy"]] += s["net"]
    return cum


def run_day(day):
    if not is_trading_day(day):
        print(f"{day}: not a trading day, skipped")
        return
    name = instrument_for(day)
    bars = fetch_bars(INSTRUMENTS[name]["yahoo"], day)
    vix = fetch_bars("^INDIAVIX", day)
    if len(bars) < 300:
        print(f"{day}: only {len(bars)} bars for {name}, skipped (holiday or data not ready)")
        return
    cum = cumulative_before(day)
    result = {
        "date": day.isoformat(), "instrument": name,
        "generated_at": dt.datetime.now(IST).isoformat(timespec="minutes"),
        "spot": [{"t": b["t"], "c": round(b["c"], 2)} for b in bars],
        "strategies": [replay(day, k, bars, vix, cum[k]) for k in STRATEGIES],
    }
    DAYS.mkdir(parents=True, exist_ok=True)
    (DAYS / f"{day}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(day, name, *(f"{s['strategy']}={s['net']:+,.0f}({len(s['trades'])})" for s in result["strategies"]))


def build_summary():
    bench = json.loads((ROOT / "data" / "benchmark.json").read_text())
    days, cum = [], {k: 0.0 for k in STRATEGIES}
    for f in sorted(DAYS.glob("*.json")):
        d = json.loads(f.read_text())
        row = {"date": d["date"], "instrument": d["instrument"], "strategies": {}}
        for s in d["strategies"]:
            cum[s["strategy"]] += s["net"]
            row["strategies"][s["strategy"]] = {"net": s["net"], "grade": s["grade"], "trades": len(s["trades"]),
                                                "cum": round(cum[s["strategy"]], 2)}
        row["benchmarks"] = {b["id"]: b["days"][d["date"]] for b in bench["benchmarks"] if d["date"] in b["days"]}
        days.append(row)
    summary = {"capital": CAPITAL, "strategies": STRATEGIES, "rules": RULES, "benchmarks": [{k: v for k, v in b.items() if k != "days"} for b in bench["benchmarks"]],
               "days": days, "updated": dt.datetime.now(IST).isoformat(timespec="minutes")}
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    targets = [dt.date.fromisoformat(a) for a in sys.argv[1:]] or [dt.datetime.now(IST).date()]
    for d in targets:
        run_day(d)
    build_summary()
