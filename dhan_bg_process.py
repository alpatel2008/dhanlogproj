
import os
import json
import time
from datetime import datetime
from dhanhq import marketfeed
import threading

client_id = "1104794978"
access_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzQ3MTA2NTc3LCJ0b2tlbkNvbnN1bWVyVHlwZSI6IlNFTEYiLCJ3ZWJob29rVXJsIjoiIiwiZGhhbkNsaWVudElkIjoiMTEwNDc5NDk3OCJ9.1GotZAlUer5QOXptwd_yh6BvdzDnr9xqKX58PH0YhaxRN2HAYW9CdrX2oPgScRItylESeGVwV35G9-ZiUdXatg"

trading_hour_start = 11
trading_hour_end = 20
instrument_map = {
    1333: "HDFC Bank",
    4963: "ICICI Bank",
    3045: "SBI",
    317: "Bajaj Finance",
    5900: "Axis Bank"
}

instruments = [(marketfeed.NSE, str(iid), marketfeed.Full) for iid in instrument_map]

version = "v2"
stocks_on_hold = {}
initial_highs = {}
ltp_tracker = {}  # store latest ltp

log_dir = "logs"
shared_data_file = "shared_data.json"

os.makedirs(log_dir, exist_ok=True)


# ----------------- Utility Functions ---------------- #

def is_trading_hours():
    now = datetime.now()
    return now.weekday() < 5 and trading_hour_start <= now.hour < trading_hour_end


def get_today_logfile():
    return os.path.join(log_dir, datetime.now().strftime("%d-%m-%Y") + ".json")


def write_trade_log(trade_data):
    log_file = get_today_logfile()
    all_data = {}
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            all_data = json.load(f)
    stock = trade_data["symbol"]
    all_data.setdefault(stock, []).append(trade_data)
    with open(log_file, "w") as f:
        json.dump(all_data, f, indent=2)


def update_daily_pnl_summary():
    summary_file = os.path.join(log_dir, "daily_pnl.json")
    today = datetime.now().strftime("%d-%m-%Y")
    pnl_total = 0

    log_file = get_today_logfile()
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            trades = json.load(f)
        for stock_trades in trades.values():
            for t in stock_trades:
                pnl_total += t.get("pnl", 0)

    summary_data = {}
    if os.path.exists(summary_file):
        with open(summary_file, "r") as f:
            summary_data = json.load(f)
    summary_data[today] = round(pnl_total, 2)

    with open(summary_file, "w") as f:
        json.dump(summary_data, f, indent=2)


# ------------------- Market Data Processing ---------------- #

def process_stock_data(response):
    try:
        instrument_id = response["security_id"]
        symbol = instrument_map.get(instrument_id, str(instrument_id))
        ltp = float(response["LTP"])
        high = float(response["high"])
        low = float(response["low"])
        open_price = float(response["open"])

        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")

        ltp_tracker[instrument_id] = ltp  # Update latest LTP

        # Set initial high at 11:00
        if now.hour == 11 and now.minute == 1:
            initial_highs[instrument_id] = high

        update_shared_data(symbol, ltp, high, low, open_price)

        if not is_trading_hours():
            return

        # Selling logic (Target)
        if instrument_id in stocks_on_hold:
            buy_info = stocks_on_hold[instrument_id]
            buy_price = buy_info["buy_price"]
            invested = round(buy_price * 100, 2)
            target_price = round(initial_highs[instrument_id] * (1 + 0.0045), 2)

            if ltp >= target_price:
                pnl = round((ltp - buy_price) * 100, 2)
                write_trade_log({
                    "symbol": symbol,
                    "action": "Target Sell",
                    "buy_price": buy_price,
                    "sell_price": ltp,
                    "quantity": 100,
                    "invested": invested,
                    "pnl": pnl,
                    "time": time_str,
                    "sold_by_target": True
                })
                del stocks_on_hold[instrument_id]

        # Buying logic
        elif instrument_id not in stocks_on_hold and instrument_id in initial_highs:
            if ltp >= initial_highs[instrument_id]:
                stocks_on_hold[instrument_id] = {
                    "buy_price": ltp,
                    "buy_time": time_str
                }
                write_trade_log({
                    "symbol": symbol,
                    "action": "Buy",
                    "buy_price": ltp,
                    "quantity": 100,
                    "time": time_str
                })

    except Exception as e:
        print(f"Processing error: {e}")


# ------------------- Shared Data Writer ------------------- #

def update_shared_data(name, ltp, high, low, open_price):
    if os.path.exists(shared_data_file):
        with open(shared_data_file, "r") as f:
            all_data = json.load(f)
    else:
        all_data = {}

    all_data[name] = {
        "ltp": ltp,
        "high": high,
        "low": low,
        "open": open_price,
        "status": "Bought" if any(name == instrument_map[iid] for iid in stocks_on_hold) else "Watching"
    }

    with open(shared_data_file, "w") as f:
        json.dump(all_data, f, indent=2)


# ------------------ End-of-Day Force Sell ------------------- #

def force_sell_remaining():
    now = datetime.now()
    for instrument_id, buy_info in list(stocks_on_hold.items()):
        ltp = ltp_tracker.get(instrument_id, buy_info["buy_price"])
        buy_price = buy_info["buy_price"]
        symbol = instrument_map[instrument_id]
        invested = round(buy_price * 100, 2)
        pnl = round((ltp - buy_price) * 100, 2)

        write_trade_log({
            "symbol": symbol,
            "action": "Forced Sell",
            "buy_price": buy_price,
            "sell_price": ltp,
            "quantity": 100,
            "invested": invested,
            "pnl": pnl,
            "time": now.strftime("%H:%M:%S"),
            "sold_by_target": False
        })

        del stocks_on_hold[instrument_id]

    update_daily_pnl_summary()


# ----------------------- Main Loop ------------------------ #

def run_feed():
    try:
        data = marketfeed.DhanFeed(client_id, access_token, instruments, version)
        data.run_forever()

        while True:
            now = datetime.now()
            if now.hour >= trading_hour_start and now.hour <= trading_hour_end:
                if now.hour == trading_hour_end and now.minute == 0:
                    force_sell_remaining()
                    break

                response = data.get_data()
                if response:
                    process_stock_data(response)
                time.sleep(1)
            else:
                print("It's not market hour...")
                exit(0)

    except Exception as e:
        print("Feed error:", e)
        run_feed()

if __name__ == "__main__":
    run_feed()

