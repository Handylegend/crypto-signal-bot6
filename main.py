import ccxt
import pandas as pd
import requests

# ===== 配置 =====
WEBHOOK_URL = "https://discordapp.com/api/webhooks/1494452919678795776/kBiWgOnHsi3QcRDkE28lMsB20X9RSgOvO4Z3OGS7myk9DnNbcs-92z7-D4rnaD6IT0Tx"
SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"

# ===== 获取数据 =====
exchange = ccxt.binance()
ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=50)

df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

# ===== 简单测试信号 =====
last_price = df["close"].iloc[-1]

message = f"🚨 测试信号\n{SYMBOL} 当前价格: {last_price}"

# ===== 发送到 Discord =====
requests.post(WEBHOOK_URL, json={"content": message})
