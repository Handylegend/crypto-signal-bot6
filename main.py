import requests
import pandas as pd
import pandas_ta as ta
from binance.client import Client
import time
import os
import json

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

client = Client(API_KEY, API_SECRET)

CACHE_FILE = "signal_cache.json"

# ===== 加载缓存（去重）=====
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

# ===== 获取涨幅榜 =====
def get_top_gainers():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    data = requests.get(url).json()

    df = pd.DataFrame(data)
    df["priceChangePercent"] = df["priceChangePercent"].astype(float)

    # 只要USDT永续
    df = df[df["symbol"].str.endswith("USDT")]

    # 排除涨幅>30%
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

    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)

    return df

# ===== OI =====
def get_oi(symbol):
    url = f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=15m&limit=3"
    data = requests.get(url).json()
    if not data:
        return None

    return [float(x["sumOpenInterest"]) for x in data]

# ===== 信号检测 =====
def check_signal(symbol):
    df = get_klines(symbol)

    if len(df) < 50:
        return None

    df["ema7"] = ta.ema(df["close"], length=7)
    df["ema25"] = ta.ema(df["close"], length=25)
    df["rsi"] = ta.rsi(df["close"], length=14)
    bb = ta.bbands(df["close"], length=20)
    df["bb_upper"] = bb["BBU_20_2.0"]
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    last = df.iloc[-1]

    atr_percent = last["atr"] / last["close"] * 100

    oi = get_oi(symbol)
    if oi is None or len(oi) < 2:
        return None

    oi_ratio = oi[-1] / oi[-2] if oi[-2] != 0 else 0

    if (
        last["close"] > last["bb_upper"] and
        last["ema7"] > last["ema25"] and
        last["rsi"] > 45 and
        oi_ratio >= 1.5 and
        atr_percent >= 1.5
    ):
        return {
            "symbol": symbol,
            "price": last["close"],
            "oi_ratio": round(oi_ratio, 2),
            "rsi": round(last["rsi"], 2),
            "atr": round(atr_percent, 2),
            "time": str(df.iloc[-1]["time"])
        }

    return None

# ===== Discord =====
def send_discord(msg):
    requests.post(DISCORD_WEBHOOK, json={"content": msg})

# ===== 主逻辑 =====
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

                # 去重
                if key not in cache:
                    msg = (
                        f"🚀 {signal['symbol']}\n"
                        f"价格: {signal['price']}\n"
                        f"OI: {signal['oi_ratio']}x\n"
                        f"RSI: {signal['rsi']}\n"
                        f"ATR: {signal['atr']}%\n"
                    )
                    print(msg)
                    send_discord(msg)

                new_cache[key] = True

            time.sleep(0.2)

        except Exception as e:
            print(symbol, e)

    save_cache(new_cache)

if __name__ == "__main__":
    run()
