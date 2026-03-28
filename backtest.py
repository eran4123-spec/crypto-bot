"""
=====================================================
  קריפטו בוט — Backtest v2
  4H מגמה + 1H Sweep/BOS/FVG + 15M כניסה + נפח
  LONG ו-SHORT בהתאם למגמה
=====================================================
"""

import ccxt
import pandas as pd
import numpy as np
import time
import warnings
from config import *
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────
# הורדת נתונים — OKX (נגיש מכל מקום)
# ─────────────────────────────────────────
def fetch_candles(timeframe, limit, symbol="BTC/USDT"):
    exchange = ccxt.okx()
    tf_ms = {"1m":60000,"5m":300000,"15m":900000,
             "1h":3600000,"4h":14400000,"1d":86400000}
    ms = tf_ms.get(timeframe, 3600000)
    since = exchange.milliseconds() - limit * ms
    all_candles = []
    while len(all_candles) < limit:
        batch = min(1000, limit - len(all_candles))
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=batch)
        if not raw:
            break
        all_candles += raw
        since = raw[-1][0] + ms
        if len(raw) < batch:
            break
        time.sleep(0.3)
    df = pd.DataFrame(all_candles, columns=["timestamp","open","high","low","close","volume"])
    df.drop_duplicates("timestamp", inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df


# ─────────────────────────────────────────
# ATR
# ─────────────────────────────────────────
def calc_atr(df, period=ATR_PERIOD):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()


# ─────────────────────────────────────────
# מגמת 4H — EMA 50
# ─────────────────────────────────────────
def get_4h_trend(df_4h):
    df = df_4h.copy()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["trend"] = np.where(df["close"] > df["ema50"], "bull", "bear")
    return df[["trend"]]


# ─────────────────────────────────────────
# Pivot Highs/Lows על 1H
# ─────────────────────────────────────────
def find_pivots(df):
    df = df.copy()
    raw_ph = (df["high"] > df["high"].shift(1)) & (df["high"] > df["high"].shift(-1))
    raw_pl = (df["low"]  < df["low"].shift(1))  & (df["low"]  < df["low"].shift(-1))
    df["ph_val"] = df["high"].where(raw_ph).shift(1)
    df["pl_val"] = df["low"].where(raw_pl).shift(1)
    df["last_ph"] = df["ph_val"].ffill()
    df["last_pl"] = df["pl_val"].ffill()
    return df


# ─────────────────────────────────────────
# חיפוש FVG בטווח נרות
# ─────────────────────────────────────────
def find_fvg_in_range(df, start_i, end_i, direction):
    """
    Bearish FVG: low[j] > high[j+2]  → פער למטה
    Bullish FVG: high[j] < low[j+2]  → פער למעלה
    מחזיר את ה-FVG האחרון שנמצא בטווח
    """
    result = None
    for j in range(max(start_i, end_i - 20), end_i - 1):
        if j + 2 > end_i:
            break
        if direction == "bearish":
            if df.iloc[j]["low"] > df.iloc[j+2]["high"]:
                result = {
                    "top":    df.iloc[j]["low"],
                    "bottom": df.iloc[j+2]["high"]
                }
        else:
            if df.iloc[j]["high"] < df.iloc[j+2]["low"]:
                result = {
                    "top":    df.iloc[j+2]["low"],
                    "bottom": df.iloc[j]["high"]
                }
    return result


# ─────────────────────────────────────────
# זיהוי Setups על 1H
# Sweep → BOS → FVG → setup מוכן לכניסה
# ─────────────────────────────────────────
def detect_setups(df_1h):
    setups = []
    state       = "SEEK_SWEEP"
    sweep_price = None
    sweep_idx   = None
    direction   = None

    for i in range(ATR_PERIOD + 5, len(df_1h) - 1):
        row     = df_1h.iloc[i]
        trend   = row["trend_4h"]
        last_pl = row["last_pl"]
        last_ph = row["last_ph"]
        atr     = row["atr"]

        if pd.isna(last_pl) or pd.isna(last_ph) or pd.isna(atr) or atr == 0:
            continue

        # ── שלב 1: חיפוש Sweep ──────────────────────
        if state == "SEEK_SWEEP":

            if trend == "bear" and TRADE_DIRECTION in ("both", "short"):
                # Bearish sweep: wick מעל Pivot High, סגירה מתחתיו
                if row["high"] > last_ph and row["close"] < last_ph:
                    sweep_price = row["high"]
                    sweep_idx   = i
                    direction   = "short"
                    state       = "SEEK_BOS"

            elif trend == "bull" and TRADE_DIRECTION in ("both", "long"):
                # Bullish sweep: wick מתחת Pivot Low, סגירה מעליו
                if row["low"] < last_pl and row["close"] > last_pl:
                    sweep_price = row["low"]
                    sweep_idx   = i
                    direction   = "long"
                    state       = "SEEK_BOS"

        # ── שלב 2: חיפוש BOS ────────────────────────
        elif state == "SEEK_BOS":
            if i - sweep_idx > SWEEP_WINDOW:
                state = "SEEK_SWEEP"
                continue

            if direction == "short" and row["close"] < last_pl:
                # BOS ירידה מאושר — מחפש FVG
                fvg = find_fvg_in_range(df_1h, sweep_idx, i, "bearish")

                # אין FVG → נשתמש בגוף נר ה-BOS כאזור כניסה
                if fvg is None:
                    body_top    = max(row["open"], row["close"])
                    body_bottom = min(row["open"], row["close"])
                    fvg = {"top": body_top, "bottom": body_bottom}

                sl_price  = sweep_price + atr * SL_BUFFER_ATR
                risk_est  = sl_price - row["close"]

                if risk_est > 0 and (risk_est / row["close"]) >= MIN_SL_PCT:
                    setups.append({
                        "direction": "short",
                        "fvg_top":    fvg["top"],
                        "fvg_bottom": fvg["bottom"],
                        "sl_price":   sl_price,
                        "valid_from": df_1h.index[i],
                        "used": False
                    })
                state = "SEEK_SWEEP"

            elif direction == "long" and row["close"] > last_ph:
                # BOS עלייה מאושר — מחפש FVG
                fvg = find_fvg_in_range(df_1h, sweep_idx, i, "bullish")

                if fvg is None:
                    body_top    = max(row["open"], row["close"])
                    body_bottom = min(row["open"], row["close"])
                    fvg = {"top": body_top, "bottom": body_bottom}

                sl_price  = sweep_price - atr * SL_BUFFER_ATR
                risk_est  = row["close"] - sl_price

                if risk_est > 0 and (risk_est / row["close"]) >= MIN_SL_PCT:
                    setups.append({
                        "direction": "long",
                        "fvg_top":    fvg["top"],
                        "fvg_bottom": fvg["bottom"],
                        "sl_price":   sl_price,
                        "valid_from": df_1h.index[i],
                        "used": False
                    })
                state = "SEEK_SWEEP"

    return setups


# ─────────────────────────────────────────
# כניסות על 15M
# מחכה שמחיר יחזור ל-FVG + אישור נפח
# ─────────────────────────────────────────
def find_entries_15m(df_15m, setups):
    trades    = []
    in_trade  = False
    entry = sl = tp = trade_dir = None
    entry_window = pd.Timedelta(minutes=15 * FVG_ENTRY_WINDOW)

    for i in range(VOL_MA_PERIOD + 1, len(df_15m) - 1):
        row          = df_15m.iloc[i]
        current_time = df_15m.index[i]

        # ── ניהול עסקה פתוחה ──────────────────────
        if in_trade:
            if trade_dir == "short":
                if row["low"] <= tp:
                    trades.append({
                        "dir":"SHORT","result":"WIN","rr":RISK_REWARD,
                        "entry":round(entry,1),"sl":round(sl,1),
                        "tp":round(tp,1),"time":current_time
                    })
                    in_trade = False
                elif row["high"] >= sl:
                    trades.append({
                        "dir":"SHORT","result":"LOSS","rr":-1.0,
                        "entry":round(entry,1),"sl":round(sl,1),
                        "tp":round(tp,1),"time":current_time
                    })
                    in_trade = False
            else:
                if row["high"] >= tp:
                    trades.append({
                        "dir":"LONG","result":"WIN","rr":RISK_REWARD,
                        "entry":round(entry,1),"sl":round(sl,1),
                        "tp":round(tp,1),"time":current_time
                    })
                    in_trade = False
                elif row["low"] <= sl:
                    trades.append({
                        "dir":"LONG","result":"LOSS","rr":-1.0,
                        "entry":round(entry,1),"sl":round(sl,1),
                        "tp":round(tp,1),"time":current_time
                    })
                    in_trade = False
            continue

        # ── בדיקת נפח ─────────────────────────────
        vol_ma = row["vol_ma"]
        if pd.isna(vol_ma) or row["volume"] < vol_ma * VOL_THRESHOLD:
            continue

        # ── חיפוש setup פעיל ──────────────────────
        for setup in setups:
            if setup["used"]:
                continue
            if current_time < setup["valid_from"]:
                continue
            if current_time > setup["valid_from"] + entry_window:
                setup["used"] = True
                continue

            fvg_top    = setup["fvg_top"]
            fvg_bottom = setup["fvg_bottom"]
            sl_price   = setup["sl_price"]

            if setup["direction"] == "short":
                # מחיר מתקן חזרה ל-FVG — כניסה Short
                if row["high"] >= fvg_bottom and row["close"] <= fvg_top:
                    entry_p = row["close"]
                    risk    = sl_price - entry_p
                    if risk <= 0 or (risk / entry_p) < MIN_SL_PCT:
                        setup["used"] = True
                        continue
                    entry    = entry_p
                    sl       = sl_price
                    tp       = entry_p - risk * RISK_REWARD
                    trade_dir = "short"
                    in_trade  = True
                    setup["used"] = True
                    break

            elif setup["direction"] == "long":
                # מחיר מתקן חזרה ל-FVG — כניסה Long
                if row["low"] <= fvg_top and row["close"] >= fvg_bottom:
                    entry_p = row["close"]
                    risk    = entry_p - sl_price
                    if risk <= 0 or (risk / entry_p) < MIN_SL_PCT:
                        setup["used"] = True
                        continue
                    entry    = entry_p
                    sl       = sl_price
                    tp       = entry_p + risk * RISK_REWARD
                    trade_dir = "long"
                    in_trade  = True
                    setup["used"] = True
                    break

    return trades


# ─────────────────────────────────────────
# הדפסת תוצאות
# ─────────────────────────────────────────
def print_results(trades, df_15m):
    if not trades:
        print("\n  לא נמצאו עסקאות.")
        return

    results   = pd.DataFrame(trades)
    wins      = (results["result"] == "WIN").sum()
    losses    = (results["result"] == "LOSS").sum()
    total     = len(results)
    wr        = wins / total * 100
    avg_rr    = results["rr"].mean()
    exp       = (wr/100 * RISK_REWARD) - ((1 - wr/100) * 1.0)

    long_r    = results[results["dir"] == "LONG"]
    short_r   = results[results["dir"] == "SHORT"]
    long_wr   = (long_r["result"]=="WIN").sum() / len(long_r) * 100 if len(long_r) > 0 else 0
    short_wr  = (short_r["result"]=="WIN").sum() / len(short_r) * 100 if len(short_r) > 0 else 0

    print("\n" + "=" * 55)
    print("        תוצאות Backtest v2")
    print("=" * 55)
    print(f"  טווח ניתוח    : {df_15m.index[0].date()} → {df_15m.index[-1].date()}")
    print(f"  סה\"כ עסקאות   : {total}")
    print(f"  ניצחונות      : {wins}")
    print(f"  הפסדים        : {losses}")
    print(f"  Win Rate       : {wr:.1f}%")
    print(f"  R:R ממוצע     : {avg_rr:.2f}")
    print(f"  Expectancy     : {exp:.2f}R לעסקה")
    print("=" * 55)

    if exp > 0:
        print("  ✔  Expectancy חיובי — רווחי בתיאוריה")
    else:
        print("  ✘  Expectancy שלילי — לא רווחי בנתונים אלו")

    if total < 30:
        print(f"  ⚠  רק {total} עסקאות — צריך 50+ לתוצאה אמינה")

    if len(long_r) > 0:
        print(f"  LONG:  {len(long_r)} עסקאות | Win Rate {long_wr:.1f}%")
    if len(short_r) > 0:
        print(f"  SHORT: {len(short_r)} עסקאות | Win Rate {short_wr:.1f}%")

    print(f"\n  כל העסקאות:")
    print(results[["time","dir","result","entry","sl","tp","rr"]].to_string(index=False))
    print()


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
def run_backtest():
    print("=" * 55)
    print("  מוריד נתונים מ-Bybit (שלושה טווחי זמן)...")
    print("  זה עשוי לקחת כ-30 שניות...")
    print("=" * 55)

    df_4h  = fetch_candles("4h",  TREND_CANDLES)
    df_1h  = fetch_candles("1h",  SETUP_CANDLES)
    df_15m = fetch_candles("15m", ENTRY_CANDLES)

    print(f"  4H  נרות: {len(df_4h)}  | {df_4h.index[0].date()} → {df_4h.index[-1].date()}")
    print(f"  1H  נרות: {len(df_1h)}  | {df_1h.index[0].date()} → {df_1h.index[-1].date()}")
    print(f"  15M נרות: {len(df_15m)} | {df_15m.index[0].date()} → {df_15m.index[-1].date()}")

    # הכנת 1H
    df_1h = find_pivots(df_1h)
    df_1h["atr"] = calc_atr(df_1h)
    trend = get_4h_trend(df_4h).reindex(df_1h.index, method="ffill")
    df_1h["trend_4h"] = trend["trend"]

    # הכנת 15M
    df_15m["vol_ma"] = df_15m["volume"].rolling(VOL_MA_PERIOD).mean()

    # זיהוי setups על 1H
    setups = detect_setups(df_1h)
    long_s  = sum(1 for s in setups if s["direction"] == "long")
    short_s = sum(1 for s in setups if s["direction"] == "short")
    print(f"\n  Setups על 1H: {len(setups)} ({long_s} LONG, {short_s} SHORT)")

    # כניסות על 15M
    trades = find_entries_15m(df_15m, setups)

    print_results(trades, df_15m)


if __name__ == "__main__":
    run_backtest()
