import ccxt
import pandas as pd
import requests
import os

WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL 没有设置")

SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"

try:
    exchange = ccxt.binance({
        'enableRateLimit': True
    })

    ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=50)

    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

    last_price = df["close"].iloc[-1]

    message = f"🚨 测试信号\n{SYMBOL} 当前价格: {last_price}"

    requests.post(WEBHOOK_URL, json={"content": message})

except Exception as e:
    error_msg = f"❌ 报错: {str(e)}"
    requests.post(WEBHOOK_URL, json={"content": error_msg})
    raise
