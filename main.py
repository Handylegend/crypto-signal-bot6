import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import os

WEBHOOK_URL = os.getenv("WEBHOOK_URL")

SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"

def get_oi():
    # Binance OI（USDT永续）
    url = "https://fapi.binance.com/futures/data/openInterestHist"
    params = {
        "symbol": "BTCUSDT",
        "period": "15m",
        "limit": 50
    }
    data = requests.get(url, params=params).json()
    df = pd.DataFrame(data)
    df["sumOpenInterest"] = df["sumOpenInterest"].astype(float)
    return df

try:
    exchange = ccxt.binance()

    ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=100)
    df = pd.DataFrame(ohlcv, columns=["time","open","high","low","close","volume"])

    # ===== 指标 =====
    df["ema7"] = ta.ema(df["close"], length=7)
    df["ema20"] = ta.ema(df["close"], length=20)
    df["ema25"] = ta.ema(df["close"], length=25)

    bb = ta.bbands(df["close"], length=20)
    df["bb_upper"] = bb["BBU_20_2.0"]

    df["rsi"] = ta.rsi(df["close"], length=14)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    # ===== OI =====
    oi_df = get_oi()

    # ===== 当前 & 前一根 =====
    last = df.iloc[-1]
    prev = df.iloc[-2]

    oi_last = oi_df["sumOpenInterest"].iloc[-1]
    oi_prev = oi_df["sumOpenInterest"].iloc[-2]

    # ===== 条件 =====

    # 1. 布林带突破
    cond_bb = last["close"] > last["bb_upper"]

    # 2. EMA20突破（从下到上）
    cond_ema20 = prev["close"] < prev["ema20"] and last["close"] > last["ema20"]

    # 3. EMA7 > EMA25
    cond_ema_trend = last["ema7"] > last["ema25"]

    # 4. RSI > 45
    cond_rsi = last["rsi"] > 45

    # 5. 涨幅条件
    change_last = (last["close"] - prev["close"]) / prev["close"]
    prev2 = df.iloc[-3]
    change_prev = (prev["close"] - prev2["close"]) / prev2["close"]

    cond_change = (change_last > 0) and (change_prev > 0) and (change_last > 2 * change_prev)

    # 6. OI 放大1.5倍
    cond_oi = oi_last > 1.5 * oi_prev

    # 7. ATR过滤
    atr_ratio = last["atr"] / last["close"]
    cond_atr = atr_ratio >= 0.015   # 小于1.5%跳过

    # ===== 总信号 =====
    signal = all([
        cond_bb,
        cond_ema20,
        cond_ema_trend,
        cond_rsi,
        cond_change,
        cond_oi,
        cond_atr
    ])

    if signal:
        message = f"""
🚀 强势多头信号
{SYMBOL}

价格: {last['close']:.2f}
RSI: {last['rsi']:.2f}
ATR%: {atr_ratio*100:.2f}%
OI倍数: {oi_last/oi_prev:.2f}x

条件满足：
✔ 布林带突破
✔ EMA20突破
✔ EMA7>EMA25
✔ RSI>45
✔ 动量增强
✔ OI放大
"""

        requests.post(WEBHOOK_URL, json={"content": message})
        print("信号已发送")

    else:
        print("无信号")

except Exception as e:
    print("错误:", str(e))
    raise
