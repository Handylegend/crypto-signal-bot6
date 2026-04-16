import ccxt
import pandas as pd
import requests
import os

WEBHOOK_URL = "https://discordapp.com/api/webhooks/1494452919678795776/kBiWgOnHsi3QcRDkE28lMsB20X9RSgOvO4Z3OGS7myk9DnNbcs-92z7-D4rnaD6IT0Tx"

try:
    exchange = ccxt.binance()

    ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe="5m", limit=50)

    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

    last_price = df["close"].iloc[-1]

    message = f"🚨 测试信号\nBTC/USDT 当前价格: {last_price}"

    requests.post(WEBHOOK_URL, json={"content": message})

    print("发送成功")
