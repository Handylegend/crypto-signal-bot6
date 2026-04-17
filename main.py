import requests
import pandas as pd
from binance.client import Client
import time
import os
import json

from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

client = Client(API_KEY, API_SECRET)

CACHE_FILE = "signal_cache.json"

# ===== 缓存（去重）=====
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

# ===== 涨幅榜 =====
def get_top_gainers():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    data = requests.get(url).json()

    df = pd.DataFrame(data)
    df["priceChangePercent"] = df["priceChangePercent"].astype(float)

    df = df[df["symbol"].str.endswith("USDT")]
    df = df[df["priceChangePercent"] < 30]

    df = df.sort_values(by="priceChangePercent", ascending=False)

    return df.head(100)["symbol"].tolist()

# ===== K线 =====
def get_klines(symbol):
    klines = client.futures_klines(symbol=symbol, interval="15m", limit=100)

    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])

    df["open"] = df["open"].astype(float)
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["volume"] = df["volume"].astype(float)

    return df

# ===== OI =====
def get_oi(symbol):
    url = f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=15m&limit=3"
    data = requests.get(url).json()
    if not data:
        return None
    return [float(x["sumOpenInterest"]) for x in data]

# ===== Funding =====
def get_funding(symbol):
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
    data = requests.get(url).json()
    return float(data["lastFundingRate"])

# ===== 信号检测 =====
def check_signal(symbol):
    df = get_klines(symbol)

    if len(df) < 50:
        return None

    # ===== 技术指标 =====
    df["ema7"] = EMAIndicator(df["close"], window=7).ema_indicator()
    df["ema25"] = EMAIndicator(df["close"], window=25).ema_indicator()
    df["rsi"] = RSIIndicator(df["close"], window=14).rsi()

    bb = BollingerBands(df["close"], window=20)
    df["bb_upper"] = bb.bollinger_hband()

    atr = AverageTrueRange(df["high"], df["low"], df["close"], window=14)
    df["atr"] = atr.average_true_range()

    last = df.iloc[-1]

    # ===== ATR过滤 =====
    atr_percent = last["atr"] / last["close"] * 100
    if atr_percent < 1.5:
        return None

    # ===== OI =====
    oi = get_oi(symbol)
    if oi is None or len(oi) < 2:
        return None
    oi_ratio = oi[-1] / oi[-2] if oi[-2] != 0 else 0

    # ===== Volume Spike =====
    avg_vol = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = last["volume"] / avg_vol if avg_vol else 0

    # ===== Funding =====
    try:
        funding = get_funding(symbol)
    except:
        funding = 0

    # ===== CVD计算 =====
    df["delta"] = df.apply(
        lambda row: row["volume"] if row["close"] > row["open"] else -row["volume"],
        axis=1
    )
    df["cvd"] = df["delta"].cumsum()

    cvd_trend = df["cvd"].iloc[-1] - df["cvd"].iloc[-5]

    # ===== 评分系统 =====
    score = 0
    reasons = []

    if last["close"] > last["bb_upper"]:
        score += 2
        reasons.append("BB突破")

    if last["ema7"] > last["ema25"]:
        score += 1
        reasons.append("EMA趋势")

    if last["rsi"] > 45:
        score += 1
        reasons.append("RSI")

    if oi_ratio >= 1.5:
        score += 2
        reasons.append("OI放大")

    if vol_ratio >= 1.5:
        score += 2
        reasons.append("成交量放大")

    # Funding过滤 + 加分
    if funding < 0:
        score += 2
        reasons.append("Funding有利")
    elif funding > 0.0003:
        return None

    # CVD
    if cvd_trend > 0:
        score += 2
        reasons.append("CVD买盘主导")

    # ===== 信号触发阈值 =====
    if score >= 7:
        return {
            "symbol": symbol,
            "price": last["close"],
            "score": score,
            "oi": round(oi_ratio, 2),
            "vol": round(vol_ratio, 2),
            "funding": round(funding, 5),
            "atr": round(atr_percent, 2),
            "reasons": reasons,
            "time": str(df.iloc[-1]["time"])
        }

    return None

# ===== Discord =====
def send_discord(msg):
    requests.post(DISCORD_WEBHOOK, json={"content": msg})

# ===== 主程序 =====
def run():
    cache = load_cache()
    new_cache = {}

    symbols = get_top_gainers()
    print("扫描:", len(symbols))

    for symbol in symbols:
        try:
            signal = check_signal(symbol)

            if signal:
                key = f"{symbol}_{signal['time']}"

                if key not in cache:
                    msg = (
                        f"🚀 {signal['symbol']} | 评分: {signal['score']}\n"
                        f"价格: {signal['price']}\n"
                        f"OI: {signal['oi']}x | VOL: {signal['vol']}x\n"
                        f"Funding: {signal['funding']}\n"
                        f"ATR: {signal['atr']}%\n"
                        f"原因: {', '.join(signal['reasons'])}"
                    )
                    print(msg)
                    send_discord(msg)

                new_cache[key] = True

            time.sleep(0.2)

        except Exception as e:
            print(symbol, "error:", e)

    save_cache(new_cache)

if __name__ == "__main__":
    run()
