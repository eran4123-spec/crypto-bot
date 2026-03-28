# ===================================================
# הגדרות הבוט — כאן תוכל לשנות פרמטרים
# ===================================================

SYMBOL = "BTC/USDT:USDT"

# ── טווחי זמן ──────────────────────────────────
TREND_TIMEFRAME  = "4h"
TREND_CANDLES    = 1500     # ~250 ימים

SETUP_TIMEFRAME  = "1h"
SETUP_CANDLES    = 6000     # ~250 ימים

ENTRY_TIMEFRAME  = "15m"
ENTRY_CANDLES    = 24000    # ~250 ימים

# ── ניהול סיכונים ───────────────────────────────
RISK_REWARD      = 3.0
SL_BUFFER_ATR    = 0.5      # SL = sweep + ATR * 0.5
MIN_SL_PCT       = 0.004    # SL מינימלי 0.4% מהמחיר
ATR_PERIOD       = 14
SWING_LOOKBACK   = 5
SWEEP_WINDOW     = 30       # נרות 1H לחכות ל-BOS אחרי Sweep
FVG_ENTRY_WINDOW = 48       # נרות 15M לחכות לכניסה (12 שעות)

# ── נפח ─────────────────────────────────────────
VOL_MA_PERIOD    = 20
VOL_THRESHOLD    = 1.1      # כניסה רק כשנפח > 110% ממוצע

# ── כיוון ───────────────────────────────────────
# "both" = לפי מגמה | "long" = רק קנייה | "short" = רק מכירה
TRADE_DIRECTION  = "both"

# ── Telegram ────────────────────────────────────
TELEGRAM_TOKEN   = "8619013125:AAHkfouk-BLSblcyP8TpF8GH_NO04xG5EoY"
TELEGRAM_CHAT_ID = "8368612128"
