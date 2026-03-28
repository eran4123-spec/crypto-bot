"""
סקנר חד-פעמי — מריץ GitHub Actions כל 15 דקות
"""

import ccxt
import pandas as pd
import numpy as np
import time
import requests
import json
import os
import warnings
from backtest import (fetch_candles, get_4h_trend, find_pivots,
                      calc_atr, detect_setups)
warnings.filterwarnings("ignore")

# ── Telegram — מגיע מ-GitHub Secrets ──────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── פרמטרים ───────────────────────────────────
SYMBOL           = "BTC/USDT:USDT"
RISK_REWARD      = 3.0
MIN_SL_PCT       = 0.004
VOL_MA_PERIOD    = 20
VOL_THRESHOLD    = 1.1
FVG_ENTRY_WINDOW = 48
TRADE_DIRECTION  = "both"
ATR_PERIOD       = 14
SWING_LOOKBACK   = 5
SWEEP_WINDOW     = 30
SL_BUFFER_ATR    = 0.5

LAST_SIGNAL_FILE = "last_signal.json"


def send_telegram(message):
    if not TELEGRAM_TOKEN:
        print("אין Telegram Token")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"שגיאת Telegram: {e}")


def load_last_signal():
    if os.path.exists(LAST_SIGNAL_FILE):
        with open(LAST_SIGNAL_FILE, "r") as f:
            return json.load(f)
    return {}


def save_last_signal(data):
    with open(LAST_SIGNAL_FILE, "w") as f:
        json.dump(data, f)


def format_message(signal):
    emoji  = "🟢" if signal["dir"] == "LONG" else "🔴"
    action = "LONG  📈" if signal["dir"] == "LONG" else "SHORT 📉"
    entry  = signal["entry"]
    sl     = signal["sl"]
    tp     = signal["tp"]
    risk   = abs(entry - sl)
    rr     = abs(tp - entry) / risk if risk > 0 else 0

    return (
        f"{emoji} <b>{action} BTC/USDT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 כניסה:  <b>${entry:,.1f}</b>\n"
        f"🛑 SL:     ${sl:,.1f}\n"
        f"🎯 TP:     ${tp:,.1f}\n"
        f"📊 R:R:    1:{rr:.1f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>התראה בלבד — ההחלטה שלך!</i>"
    )


def check_signal():
    df_4h  = fetch_candles("4h",  200)
    df_1h  = fetch_candles("1h",  500)
    df_15m = fetch_candles("15m", 300)

    df_1h = find_pivots(df_1h)
    df_1h["atr"] = calc_atr(df_1h)
    trend = get_4h_trend(df_4h).reindex(df_1h.index, method="ffill")
    df_1h["trend_4h"] = trend["trend"]
    df_15m["vol_ma"] = df_15m["volume"].rolling(VOL_MA_PERIOD).mean()

    setups = detect_setups(df_1h)
    if not setups:
        print("אין setups פעילים")
        return

    last         = load_last_signal()
    entry_window = pd.Timedelta(minutes=15 * FVG_ENTRY_WINDOW)
    recent_15m   = df_15m.iloc[-20:]

    for i in range(len(recent_15m)):
        row          = recent_15m.iloc[i]
        current_time = recent_15m.index[i]

        vol_ma = row["vol_ma"]
        if pd.isna(vol_ma) or row["volume"] < vol_ma * VOL_THRESHOLD:
            continue

        for setup in setups:
            if current_time < setup["valid_from"]:
                continue
            if current_time > setup["valid_from"] + entry_window:
                continue

            fvg_top    = setup["fvg_top"]
            fvg_bottom = setup["fvg_bottom"]
            sl_price   = setup["sl_price"]
            signal     = None

            if setup["direction"] == "short":
                if row["high"] >= fvg_bottom and row["close"] <= fvg_top:
                    entry_p = row["close"]
                    risk    = sl_price - entry_p
                    if risk <= 0 or (risk / entry_p) < MIN_SL_PCT:
                        continue
                    signal = {
                        "dir":   "SHORT",
                        "entry": round(entry_p, 1),
                        "sl":    round(sl_price, 1),
                        "tp":    round(entry_p - risk * RISK_REWARD, 1),
                        "time":  str(current_time)
                    }

            elif setup["direction"] == "long":
                if row["low"] <= fvg_top and row["close"] >= fvg_bottom:
                    entry_p = row["close"]
                    risk    = entry_p - sl_price
                    if risk <= 0 or (risk / entry_p) < MIN_SL_PCT:
                        continue
                    signal = {
                        "dir":   "LONG",
                        "entry": round(entry_p, 1),
                        "sl":    round(sl_price, 1),
                        "tp":    round(entry_p + risk * RISK_REWARD, 1),
                        "time":  str(current_time)
                    }

            if signal:
                if (last.get("dir")   == signal["dir"] and
                    last.get("entry") == signal["entry"]):
                    print(f"סיגנל כפול — מדלג")
                    continue

                save_last_signal(signal)
                msg = format_message(signal)
                send_telegram(msg)
                print(f"✔ סיגנל נשלח: {signal['dir']} @ ${signal['entry']}")
                return

    print("אין סיגנל חדש")


if __name__ == "__main__":
    check_signal()
