"""
Camarilla R5 Backfill Scanner — All Binance USDT-M Perpetual Futures
----------------------------------------------------------------------
Same logic as scan_camarilla.py, but instead of checking only the most
recent 2 closed candles, this scans EVERY consecutive candle-pair since
the start of today (00:00 UTC) on the 15-minute timeframe.

Use this to replicate a manual "scroll back through the day" check —
it answers "did this happen at any point today?" rather than "is this
happening right now?"

This does NOT send Discord alerts by default (it's meant for one-time
comparison/testing, not live notification) — set SEND_TO_DISCORD = True
below if you want a summary posted to Discord as well.
"""

import requests
import time
import sys
from datetime import datetime, timezone

# ---------- CONFIG ----------
R5_FORMULA = "a"  # must match scan_camarilla.py's setting
BINANCE_FUTURES_BASE = "https://fapi.binance.com"
REQUEST_DELAY_SECONDS = 0.15
TIMEOUT = 10
SEND_TO_DISCORD = False
DISCORD_WEBHOOK_URL = ""  # only used if SEND_TO_DISCORD is True

# ---------- HELPERS (same as scan_camarilla.py) ----------

def get_all_usdt_perpetual_symbols():
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/exchangeInfo"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return [
        s["symbol"] for s in data["symbols"]
        if s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("status") == "TRADING"
    ]


def get_daily_hlc(symbol):
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": 2}
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    klines = resp.json()
    if len(klines) < 2:
        return None
    prev = klines[-2]
    return float(prev[2]), float(prev[3]), float(prev[4])


def get_todays_15m_candles(symbol):
    """All 15m candles from 00:00 UTC today up to now."""
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_ms = int(start_of_day.timestamp() * 1000)

    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": "15m",
        "startTime": start_ms,
        "limit": 100,  # safely covers a full day (96 candles) + buffer
    }
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    klines = resp.json()

    # Drop the currently-forming (last, incomplete) candle
    if not klines:
        return []
    now_ms = int(now.timestamp() * 1000)
    closed = [k for k in klines if k[6] < now_ms]  # k[6] = close time
    return closed


def calc_camarilla_r5(high, low, close):
    rng = high - low
    r3 = close + rng * 1.1 / 4
    r4 = close + rng * 1.1 / 2
    if R5_FORMULA == "a":
        return (high / low) * close
    else:
        return r4 + 1.168 * (r4 - r3)


def find_all_occurrences_today(symbol, r5):
    """Returns a list of (time1, time2, close1, close2) for every
    consecutive candle-pair today where both are green and both
    closed above r5."""
    candles = get_todays_15m_candles(symbol)
    occurrences = []
    for i in range(len(candles) - 1):
        c1_data, c2_data = candles[i], candles[i + 1]
        o1, c1 = float(c1_data[1]), float(c1_data[4])
        o2, c2 = float(c2_data[1]), float(c2_data[4])
        t1 = datetime.fromtimestamp(c1_data[0] / 1000, tz=timezone.utc)
        t2 = datetime.fromtimestamp(c2_data[0] / 1000, tz=timezone.utc)

        if c1 > o1 and c1 > r5 and c2 > o2 and c2 > r5:
            occurrences.append((t1, t2, c1, c2))
    return occurrences


def send_discord_summary(all_results):
    if not DISCORD_WEBHOOK_URL:
        print("[WARN] SEND_TO_DISCORD is True but no webhook URL set")
        return
    lines = [f"**Backfill scan — {len(all_results)} symbol(s) with today's occurrences**"]
    for symbol, occs in all_results.items():
        lines.append(f"\n**{symbol}** — {len(occs)} occurrence(s)")
        for t1, t2, c1, c2 in occs[:3]:  # cap to avoid a giant message
            lines.append(f"  {t1.strftime('%H:%M')} -> {t2.strftime('%H:%M')} UTC (closed {c1:.6f}, {c2:.6f})")
    message = {"content": "\n".join(lines)[:1900]}  # Discord message length limit
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=TIMEOUT)
    except Exception as e:
        print(f"[ERROR] Discord summary failed: {e}")


def backfill():
    print(f"Backfill scan starting at {datetime.now(timezone.utc).isoformat()}")
    print("Scanning today's full candle history (since 00:00 UTC) for every symbol...")
    print()

    try:
        symbols = get_all_usdt_perpetual_symbols()
    except Exception as e:
        print(f"[FATAL] Could not fetch symbol list: {e}")
        sys.exit(1)

    print(f"Found {len(symbols)} USDT-M perpetual symbols\n")

    all_results = {}

    for symbol in symbols:
        try:
            hlc = get_daily_hlc(symbol)
            if not hlc:
                continue
            r5 = calc_camarilla_r5(*hlc)

            occurrences = find_all_occurrences_today(symbol, r5)
            if occurrences:
                all_results[symbol] = occurrences
                print(f"[FOUND] {symbol} — {len(occurrences)} occurrence(s) today, R5={r5:.6f}")
                for t1, t2, c1, c2 in occurrences:
                    print(f"         {t1.strftime('%H:%M')} -> {t2.strftime('%H:%M')} UTC | closed {c1:.6f}, {c2:.6f}")

        except requests.exceptions.RequestException as e:
            print(f"[SKIP] {symbol} — network error: {e}")
        except Exception as e:
            print(f"[SKIP] {symbol} — unexpected error: {e}")

        time.sleep(REQUEST_DELAY_SECONDS)

    print()
    print(f"Backfill complete. {len(all_results)} symbol(s) had at least one occurrence today.")
    print(f"Symbols: {list(all_results.keys())}")

    if SEND_TO_DISCORD:
        send_discord_summary(all_results)


if __name__ == "__main__":
    backfill()
