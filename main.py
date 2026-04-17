import requests
import pandas as pd
import time
import os
import json

from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

BASE_URL = "https://api.bybit.com"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

CACHE_FILE = "signal_cache.json"
DAILY_FLAG_FILE = "daily_flag.json"

# ===== 安全请求 =====
def safe_request(url, retries=3, timeout=10):
    for i in range(retries):
        try:
            res = requests.get(url, timeout=timeout)

            if res.status_code != 200:
                print(f"HTTP错误 {res.status_code}: {url}")
                time.sleep(1)
                continue

            if not res.text:
                print("空响应:", url)
                time.sleep(1)
                continue

            return res.json()

        except Exception as e:
            print(f"请求失败({i+1}):", e)
            time.sleep(1)

    return None

# ===== 缓存 =====
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

# ===== 每日心跳缓存 =====
def load_daily_flag():
    if os.path.exists(DAILY_FLAG_FILE):
        with open(DAILY_FLAG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_daily_flag(data):
    with open(DAILY_FLAG_FILE, "w") as f:
        json.dump(data, f)

# ===== 启动测试 =====
def send_test_message():
    try:
        msg = "✅ Bot启动成功（链路正常）"
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=5)
        print("测试消息已发送")
    except Exception as e:
        print("测试消息发送失败:", e)

# ===== 每日心跳 =====
def send_daily_heartbeat():
    now = time.gmtime()  # UTC

    if now.tm_hour == 12 and now.tm_min < 10:  # 08:30 智利时间
        flag = load_daily_flag()
        today = time.strftime("%Y-%m-%d", now)

        if flag.get("date") != today:
            msg = "🟢 系统运行正常（每日心跳）"
            send_discord(msg)
            print("发送每日心跳")

            flag["date"] = today
            save_daily_flag(flag)

# ===== Discord =====
def send_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=5)
    except Exception as e:
        print("Discord发送失败:", e)

# ===== 涨幅榜 =====
def get_top_gainers():
    url = f"{BASE_URL}/v5/market/tickers?category=linear"

    data = safe_request(url)
    if not data or "result" not in data:
        print("获取涨幅榜失败")
        return []

    df = pd.DataFrame(data["result"]["list"])

    df["price24hPcnt"] = df["price24hPcnt"].astype(float)

    df = df[df["symbol"].str.endswith("USDT")]
    df = df[df["price24hPcnt"] < 0.3]

    df = df.sort_values(by="price24hPcnt", ascending=False)

    return df.head(100)["symbol"].tolist()

# ===== K线 =====
def get_klines(symbol):
    url = f"{BASE_URL}/v5/market/kline?category=linear&symbol={symbol}&interval=15&limit=100"

    data = safe_request(url)
    if not data or "result" not in data:
        return None

    raw = data["result"]["list"]
    if not raw:
        return None

    df = pd.DataFrame(raw, columns=[
        "time","open","high","low","close","volume","turnover"
    ])

    df = df[::-1]

    df["open"] = df["open"].astype(float)
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["volume"] = df["volume"].astype(float)

    return df

# ===== OI =====
def get_oi(symbol):
    url = f"{BASE_URL}/v5/market/open-interest?category=linear&symbol={symbol}&intervalTime=15min&limit=2"

    data = safe_request(url)
    if not data or "result" not in data:
        return None

    raw = data["result"]["list"]
    if not raw:
        return None

    return [float(x["openInterest"]) for x in raw]

# ===== Funding =====
def get_funding(symbol):
    url = f"{BASE_URL}/v5/market/tickers?category=linear&symbol={symbol}"

    data = safe_request(url)
    if not data or "result" not in data:
        return 0

    return float(data["result"]["list"][0]["fundingRate"])

# ===== 信号检测 =====
def check_signal(symbol):
    df = get_klines(symbol)

    if df is None or len(df) < 50:
        return None

    df["ema7"] = EMAIndicator(df["close"], window=7).ema_indicator()
    df["ema25"] = EMAIndicator(df["close"], window=25).ema_indicator()
    df["rsi"] = RSIIndicator(df["close"], window=14).rsi()

    bb = BollingerBands(df["close"], window=20)
    df["bb_upper"] = bb.bollinger_hband()

    atr = AverageTrueRange(df["high"], df["low"], df["close"], window=14)
    df["atr"] = atr.average_true_range()

    last = df.iloc[-1]

    atr_percent = last["atr"] / last["close"] * 100
    if atr_percent < 1.5:
        return None

    oi = get_oi(symbol)
    if not oi or len(oi) < 2:
        return None
    oi_ratio = oi[-1] / oi[-2] if oi[-2] != 0 else 0

    avg_vol = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = last["volume"] / avg_vol if avg_vol else 0

    funding = get_funding(symbol)

    # CVD
    df["delta"] = df.apply(
        lambda row: row["volume"] if row["close"] > row["open"] else -row["volume"],
        axis=1
    )
    df["cvd"] = df["delta"].cumsum()
    cvd_trend = df["cvd"].iloc[-1] - df["cvd"].iloc[-5]

    # ===== 评分 =====
    score = 0
    reasons = []

    if last["close"] > last["bb_upper"]:
        score += 2
        reasons.append("BB突破")

    if last["ema7"] > last["ema25"]:
        score += 1
        reasons.append("EMA趋势")

    if last["rsi"] > 42:
        score += 1
        reasons.append("RSI")

    if oi_ratio >= 1.2:
        score += 2
        reasons.append("OI放大")

    if vol_ratio >= 1.2:
        score += 2
        reasons.append("成交量放大")

    if funding < 0:
        score += 2
        reasons.append("Funding有利")

    if cvd_trend > 0:
        score += 2
        reasons.append("CVD买盘")

    if score >= 5:
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

# ===== 主程序 =====
def run():
    send_test_message()
    send_daily_heartbeat()

    cache = load_cache()
    new_cache = {}

    symbols = get_top_gainers()
    print("扫描:", len(symbols))

    if not symbols:
        return

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

            time.sleep(0.3)

        except Exception as e:
            print(symbol, "error:", e)

    save_cache(new_cache)

if __name__ == "__main__":
    run()
