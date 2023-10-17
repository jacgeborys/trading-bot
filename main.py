from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

from fetch_data import get_last_period_prices
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_ema, calculate_vwap
from login import login_to_xtb
from trade import open_trade, close_all_trades

# Global Variables
current_position = None
crossover_threshold = 0.05
atr_threshold = 2
prev_ema_12 = None
prev_ema_26 = None
prev_signal = None
prev_histogram = None
trade_opened = False
trade_start_time = None

def buy_and_sell(symbol="US500", volume=0.05, wait_time=60, retry_attempts=3):
    global current_position
    global crossover_threshold
    global atr_threshold
    global trade_opened
    global trade_start_time

    userId = 15237562
    password = os.environ.get("XTB_PASSWORD")

    client, ssid = login_to_xtb(userId, password)
    if not client or not ssid:
        return

    prev_macd = None
    prev_signal = None
    prev_histogram = None
    prev_prev_histogram = None

    attempts = 0

    while True:
        try:
            # Fetch and prepare data
            prices, latest_open, latest_close, highs, lows, volume_data = get_last_period_prices(client, symbol, period=5)
            vwap = calculate_vwap(prices[-60:], volume_data[-60:])
            vwap_distance = latest_close - vwap
            macd, signal = calculate_macd(prices)
            atr_value = calculate_atr(highs, lows, prices)
            histogram = macd - signal

            print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
            print(f"Opening Price: {latest_open}")
            print(f"Closing Price: {latest_close}")
            print(f"MACD: {macd}")
            print(f"Signal Line: {signal}")
            print(f"ATR: {atr_value}")
            print(f"VWAP: {vwap}")
            print("-" * 40)

            log_data = [datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), latest_open, latest_close,
                        macd, signal, vwap, atr_value, current_position]
            write_to_csv(log_data)

            # MACD-based logic
            if prev_macd is not None and prev_signal is not None and prev_histogram is not None:

                if prev_macd < prev_signal and macd > signal and abs(macd - signal) > crossover_threshold and atr_value > atr_threshold:

                    print(f"Bullish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if current_position == "short":
                        print("Closing short position.")
                        close_all_trades(client)
                    tp_value = latest_close + 2 * atr_value  # Added ATR value for take profit
                    tp_value = round(tp_value, 1)
                    offset = math.ceil(1 * atr_value + 0.9)
                    sl_value = latest_close - 1000 # Just a large value in order to launch a trailing offset
                    open_trade(client, symbol, volume, offset, tp_value, sl_value)
                    print(f"Opening long position. Take profit set at {tp_value}. Trailing offset is {offset}.")
                    write_to_csv([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None, None, None,
                                  None, None, None, None, "Trade opened", "Long", tp_value, offset])
                    current_position = "long"
                elif prev_macd > prev_signal and macd < signal and abs(macd - signal) > crossover_threshold and atr_value > atr_threshold:
                    print(f"Bearish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if current_position == "long":
                        print("Closing long position.")
                        close_all_trades(client)
                    tp_value = latest_close - 2 * atr_value  # Subtract ATR value for take profit
                    offset = math.ceil(1 * atr_value + 0.9)
                    sl_value = latest_close + 1000 # Just a large value in order to launch a trailing offset
                    open_trade(client, symbol, -volume, offset, tp_value, sl_value)
                    print(f"Opening short position. Take profit set at {tp_value}. Trailing offset is {offset}.")
                    write_to_csv([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None, None, None,
                                  None, None, None, None, "Trade opened", "Long", tp_value, offset])
                    current_position = "short"

                if abs(histogram) < abs(prev_histogram):
                    if abs(macd - signal) > 2:  # New condition
                        print(
                            f"MACD histogram is narrowing at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}. Closing all positions.")
                        close_all_trades(client)
                        current_position = None  # Reset current position
                    else:
                        print(f"MACD - Signal is less than 1. Not closing the position yet.")

            prev_macd = macd
            prev_signal = signal
            prev_histogram = histogram

            if trade_opened:
                if time.time() - trade_start_time < 1200:  # 1200 seconds = 4 * 5 minutes
                    if current_position == "long" and histogram < prev_histogram:
                        print("Converging histogram detected in long position. Closing trade.")
                        close_all_trades(client)
                        current_position = None
                        trade_opened = False  # Reset the flag
                    elif current_position == "short" and histogram > prev_histogram:
                        print("Converging histogram detected in short position. Closing trade.")
                        close_all_trades(client)
                        current_position = None
                        trade_opened = False  # Reset the flag
                else:
                    trade_opened = False  # Reset the flag after 3 minutes

            # Reset attempts counter after successful connection
            attempts = 0

        except (TimeoutError, ConnectionError) as e:
            # Handle the timeout or connection error
            print(f"Encountered a connection issue: {str(e)}")
            attempts += 1
            if attempts > retry_attempts:
                print("Exceeded retry attempts. Exiting...")
                break

            print(f"Re-trying connection. Attempt {attempts}/{retry_attempts}...")
            time.sleep(10)  # Retry after 10 seconds, adjust as needed.

            # Re-login to the platform
            client, ssid = login_to_xtb(userId, password)
            if not client or not ssid:
                print("Failed to re-login. Exiting...")
                break

            continue

        time.sleep(wait_time)  # Wait for the next cycle

if __name__ == "__main__":
    buy_and_sell()