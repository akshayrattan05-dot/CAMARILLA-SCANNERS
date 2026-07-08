"""
Camarilla R5 Scanner — All Binance USDT-M Perpetual Futures
--------------------------------------------------------------
Scans every USDT-margined perpetual futures pair on Binance.
Flags a symbol when the last TWO CLOSED 15-minute candles are both:
  1. Green (close > open)
  2. Closed ABOVE that symbol's daily Camarilla R5 level

Sends a Discord notification via webhook when a match is found.

R5 FORMULA — IMPORTANT, PLEASE VERIFY:
Camarilla only has one universally agreed formula up to R4. R5 has at
least two different conventions used across different indicators:
  (a) R5 = (High / Low) * Close          <- used here, from the original
                                             Frank Ochoa / Pivot Boss source
  (b) R5 = R4 + 1.168 * (R4 - R3)        <- alternate convention

This script uses (a) by default. CHECK THIS AGAINST YOUR OWN TRADINGVIEW
CHART before trusting live signals — if your chart's R5 doesn't match
what this script prints for BTC, switch R5_FORMULA below to "b".
"""

import requests
import time
import os
import sys
from datetime import datetime, timezone

# ---------- CONFIG ----------
R5_FORMULA = "a"  # "a" = (H/L)*C   |   "b" = R4 + 1.168*(R4-R3)
TIMEFRAME = os.environ.get("TIMEFRAME", "15m")  # "15m" or "30m"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
BINANCE_FUTURES_BASE = "https://fapi.binance.com"
REQUEST_DELAY_SECONDS = 0.15  # pacing to stay well under Binance rate limits
TIMEOUT = 10

# ---------- BINANCE HELPERS ----------

def get_all_usdt_perpetual_symbols():
    """
    Returns all actively trading USDT-Margined PERPETUAL futures symbols.
    This is exactly what TradingView calls "SYMBOL.P" (e.g. BTCUSDT.P) —
    USDT-margined perpetual futures on Binance. This function ONLY reads
    from fapi.binance.com (the futures API). It never touches spot prices
    (api.binance.com), so results here can never accidentally include
    spot-market symbols.
    """
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/exchangeInfo"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    symbols = []
    for s in data["symbols"]:
        if (
            s.get("contractType") == "PERPETUAL"   # excludes quarterly/dated futures
            and s.get("quoteAsset") == "USDT"        # excludes coin-margined (BTCUSD_PERP etc.)
            and s.get("status") == "TRADING"         # excludes delisted/paused symbols
        ):
            symbols.append(s["symbol"])

    # Safety check: fail loudly rather than silently scan the wrong thing
    assert BINANCE_FUTURES_BASE == "https://fapi.binance.com", \
        "BINANCE_FUTURES_BASE must point at the futures API, not spot"

    return symbols


def get_daily_hlc(symbol):
    """Previous COMPLETED daily candle's High, Low, Close."""
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": 2}
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    klines = resp.json()
    if len(klines) < 2:
        return None
    # second-to-last entry = most recently FULLY CLOSED daily candle
    prev = klines[-2]
    high, low, close = float(prev[2]), float(prev[3]), float(prev[4])
    return high, low, close


def get_last_two_closed_candles(symbol):
    """Returns the last two fully closed candles (at TIMEFRAME resolution)
    as (open, close) tuples."""
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": 3}
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    klines = resp.json()
    if len(klines) < 3:
        return None
    # last entry [-1] is the CURRENTLY FORMING candle — skip it.
    # we want [-3] and [-2], the two most recent CLOSED candles.
    candle_2_ago = klines[-3]
    candle_1_ago = klines[-2]
    result = []
    for k in (candle_2_ago, candle_1_ago):
        o, c = float(k[1]), float(k[4])
        result.append((o, c))
    return result


def calc_camarilla_r5(high, low, close):
    rng = high - low
    r3 = close + rng * 1.1 / 4
    r4 = close + rng * 1.1 / 2
    if R5_FORMULA == "a":
        r5 = (high / low) * close
    else:
        r5 = r4 + 1.168 * (r4 - r3)
    return r5


def send_discord_alert(symbol, r5, candles):
    if not DISCORD_WEBHOOK_URL:
        print(f"[WARN] No DISCORD_WEBHOOK_URL set — would have alerted on {symbol}")
        return
    (o1, c1), (o2, c2) = candles
    message = {
        "content": (
            f"**R5 Breakout — {symbol} ({TIMEFRAME})**\n"
            f"Two consecutive green {TIMEFRAME} candles closed above R5.\n"
            f"R5 level: `{r5:.6f}`\n"
            f"Candle 1: open `{o1:.6f}` → close `{c1:.6f}`\n"
            f"Candle 2: open `{o2:.6f}` → close `{c2:.6f}`\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=TIMEOUT)
        if r.status_code >= 300:
            print(f"[ERROR] Discord webhook failed for {symbol}: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[ERROR] Discord webhook exception for {symbol}: {e}")


def scan():
    print(f"Starting scan at {datetime.now(timezone.utc).isoformat()} (timeframe: {TIMEFRAME})")

    try:
        symbols = get_all_usdt_perpetual_symbols()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        body = e.response.text[:500] if e.response is not None else ""
        print(f"[FATAL] Could not fetch symbol list — HTTP {status}")
        print(f"[FATAL] Response body: {body}")
        if status == 451:
            print(
                "[FATAL] HTTP 451 means Binance is geo-blocking this request. "
                "This commonly happens because GitHub's free hosted runners run "
                "on US-based cloud infrastructure, and Binance restricts API "
                "access from the US for regulatory reasons. This is an "
                "infrastructure problem, not a bug in this script — see the "
                "README for workarounds."
            )
        sys.exit(1)
    except Exception as e:
        print(f"[FATAL] Could not fetch symbol list — unexpected error: {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"Found {len(symbols)} USDT-M perpetual symbols")

    # Debug print: always show BTC's R5 so it can be checked against
    # your TradingView chart, even on runs where nothing triggers.
    try:
        btc_hlc = get_daily_hlc("BTCUSDT")
        if btc_hlc:
            btc_r5 = calc_camarilla_r5(*btc_hlc)
            print(f"[VERIFY] BTCUSDT daily H/L/C = {btc_hlc} -> R5 = {btc_r5:.4f} "
                  f"(compare this to your TradingView chart)")
    except Exception as e:
        print(f"[VERIFY] Could not fetch BTC R5 for verification: {e}")

    hits = []

    for symbol in symbols:
        try:
            hlc = get_daily_hlc(symbol)
            if not hlc:
                print(f"[SKIP] {symbol} — insufficient daily candle history "
                      f"(likely a very recently listed symbol)")
                continue
            high, low, close = hlc
            r5 = calc_camarilla_r5(high, low, close)

            candles = get_last_two_closed_candles(symbol)
            if not candles:
                print(f"[SKIP] {symbol} — insufficient {TIMEFRAME} candle history")
                continue
            (o1, c1), (o2, c2) = candles

            candle1_green_above = c1 > o1 and c1 > r5
            candle2_green_above = c2 > o2 and c2 > r5

            if candle1_green_above and candle2_green_above:
                print(f"[HIT] {symbol} ({TIMEFRAME}) — R5={r5:.6f}, candles closed at {c1:.6f} and {c2:.6f}")
                send_discord_alert(symbol, r5, candles)
                hits.append(symbol)

        except requests.exceptions.RequestException as e:
            print(f"[SKIP] {symbol} — network error: {e}")
        except Exception as e:
            print(f"[SKIP] {symbol} — unexpected error: {type(e).__name__}: {e}")

        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Scan complete. {len(hits)} symbol(s) matched: {hits}")


if __name__ == "__main__":
    if not DISCORD_WEBHOOK_URL:
        print("[WARN] DISCORD_WEBHOOK_URL environment variable is not set. "
              "Alerts will only print to the log, not send to Discord.")
    scan()
