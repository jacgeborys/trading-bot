from xAPIConnector import *
import time
import os
import math
import datetime

from fetch_data import get_last_period_prices
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap
from login import login_to_xtb
from trade import open_trade, close_all_trades

# State variables
prev_signal = None
prev_histogram = None

def buy_and_sell(symbol="US500", volume=0.05):
    # Global Variables
    current_position = None
    trade_opened = False
    trade_start_time = None

    userId = os.environ.get("XTB_USERID")
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if not client or not ssid:
        return

    prev_macd, prev_signal, prev_histogram = None, None, None
    crossover_threshold, atr_threshold = 0.15, 1
    attempts, wait_time, retry_attempts = 0, 60, 3

    attempts = 0

    while True:
        try:
            # Fetch and prepare data
            prices, latest_open, latest_close, highs, lows, volume_data = get_last_period_prices(client, symbol, period=1)
            macd, signal, histogram = calculate_macd(prices)
            atr_value = calculate_atr(highs, lows, prices)
            vwap = calculate_vwap(prices[-60:], volume_data[-60:])

            log_data = [datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), latest_open, latest_close,
                        macd, signal, vwap, atr_value, current_position]
            write_to_csv(log_data)

            print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
            print(f"Opening Price: {latest_open}")
            print(f"Closing Price: {latest_close}")
            print(f"MACD: {macd}")
            print(f"Signal Line: {signal}")
            print((f"Histogram: {histogram}, previous histogram: {prev_histogram}"))
            print(f"ATR: {atr_value}")
            print(f"VWAP: {vwap}")
            print(f"Current position: {current_position}")
            print("-" * 40)

            # MACD-based logic
            if prev_macd is not None and prev_signal is not None and prev_histogram is not None:
                if prev_macd < prev_signal and macd > signal and abs(histogram - prev_histogram) > crossover_threshold and atr_value > atr_threshold:

                    print(f"Bullish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if current_position == "short":
                        print("Closing short position.")
                        close_all_trades(client)
                    tp_value = round(((latest_close + latest_open)/2 + 3 * atr_value), 1)  # Added ATR value for take profit
                    offset = math.ceil(1 * atr_value + 0.9)
                    sl_value = latest_close - 2 * atr_value

                    trade_result = open_trade(client, symbol, volume, offset, tp_value, sl_value)
                    trade_start_time = time.time()
                    trade_opened = True
                    print(f"Opening long position. Take profit set at {tp_value}. Trailing offset is {offset}.")
                    print(f"Trade start time (from open_trade function): {trade_start_time}")
                    write_to_csv([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None, None, None,
                                  None, None, None, None, "Trade opened", "Long", tp_value, offset])
                    current_position = "long"
                elif prev_macd > prev_signal and macd < signal and abs(histogram - prev_histogram) > crossover_threshold and atr_value > atr_threshold:

                    print(f"Bearish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if current_position == "long":
                        print("Closing long position.")
                        close_all_trades(client)
                    tp_value = round(((latest_close + latest_open)/2 - 3 * atr_value), 1)  # Subtract ATR value for take profit
                    offset = math.ceil(1 * atr_value + 0.9)
                    sl_value = latest_close + 2 * atr_value

                    trade_result = open_trade(client, symbol, -volume, offset, tp_value, sl_value)
                    trade_start_time = time.time()
                    trade_opened = True
                    print(f"Opening short position. Take profit set at {tp_value}. Trailing offset is {offset}.")
                    print(f"Trade start time (from open_trade function): {trade_start_time}")
                    write_to_csv([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None, None, None,
                                  None, None, None, None, "Trade opened", "Short", tp_value, offset])
                    current_position = "short"

            prev_macd = macd
            prev_signal = signal
            prev_histogram = histogram

            if trade_opened:
                if time.time() - trade_start_time < 1200:  #1200 seconds = 20 * 1 minutes
                    time_passed = time.time() - trade_start_time
                    print(f"Time passed from trade opening: {time_passed}")
                    if abs(histogram) < abs(prev_histogram):
                        print(
                            "Converging histogram detected within 20 minutes. Closing trade due to potential false signal.")
                        close_all_trades(client)
                        current_position = None
                        trade_opened = False  # Reset the flag
                    else:
                        print(f"Histogram is still growing")

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