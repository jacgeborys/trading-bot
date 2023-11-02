from xAPIConnector import *
import time
import os
import math
import datetime

from fetch_data import get_last_period_prices, get_current_positions, seconds_until_next_minute
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap
from login import login_to_xtb
from trade import open_trade, close_all_trades, close_trade

def buy_and_sell(symbol="US500", volume=0.06):
    # Global Variables
    trade_just_opened = False

    userId = os.environ.get("XTB_USERID")
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if not client or not ssid:
        return

    prev_macd, prev_signal, prev_histogram, prev_prev_histogram = None, None, None, None
    crossover_threshold, atr_threshold = 0.10, 1
    attempts, wait_time, retry_attempts = 0, 60, 3

    attempts = 0

    while True:
        try:

            # Fetch and prepare data
            prices, latest_open, latest_close, highs, lows, volume_data = get_last_period_prices(client, symbol, period=1)
            macd, signal, histogram = calculate_macd(prices)
            atr_value = calculate_atr(highs, lows, prices)
            vwap = calculate_vwap(prices[-60:], volume_data[-60:])
            positions = get_current_positions(client)

            # Print statements to understand histogram direction and position
            if prev_histogram is not None:
                if histogram > prev_histogram:
                    print("Histogram is rising")
                elif histogram < prev_histogram:
                    print("Histogram is falling")
                else:
                    print("Histogram is unchanged")

                if histogram > 0:
                    print("Histogram is above zero")
                else:
                    print("Histogram is below zero")

            log_data = [datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), latest_open, latest_close,
                        macd, signal, vwap, atr_value]
            write_to_csv(log_data)

            print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
            print(f"Opening Price: {latest_open}")
            print(f"Closing Price: {latest_close}")
            print(f"MACD: {macd}")
            print(f"Signal Line: {signal}")
            print((f"Histogram: {histogram}, previous histogram: {prev_histogram}"))
            print(f"ATR: {atr_value}")
            print(f"VWAP: {vwap}")
            print(f"Number of open long positions: {positions['long_count']}")
            print(f"Number of open short positions: {positions['short_count']}")
            print("-" * 40)

            # MACD-based logic
            if prev_macd is not None and prev_signal is not None and prev_histogram is not None:
                if prev_macd < prev_signal and macd > signal and abs(histogram - prev_histogram) > crossover_threshold and atr_value > atr_threshold:

                    print(f"Bullish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if positions['short']:
                        print("Closing 20% of short position.")
                        close_trade(client, 1, 0.02)  # 1 for short position
                    tp_value = round((latest_close + 3 * atr_value), 1)  # Added ATR value for take profit
                    offset = math.ceil(1 * atr_value + 0.9)
                    sl_value = latest_close - 5 * atr_value

                    open_trade(client, symbol, volume, offset, tp_value, sl_value)
                    trade_start_time = time.time()
                    trade_just_opened = True
                    print(f"Opening long position. Take profit set at {tp_value}. Trailing offset is {offset}.")
                    print(f"Trade start time (from open_trade function): {trade_start_time}")
                    write_to_csv([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None, None, None,
                                  None, None, None, None, "Trade opened", "Long", tp_value, offset])
                elif prev_macd > prev_signal and macd < signal and abs(histogram - prev_histogram) > crossover_threshold and atr_value > atr_threshold:

                    print(f"Bearish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if positions['long']:
                        print("Closing 20% of long position.")
                        close_trade(client, 0, 0.02)  # 0 for long position
                    tp_value = round((latest_close - 3 * atr_value), 1)  # Subtract ATR value for take profit
                    offset = math.ceil(1 * atr_value + 0.9)
                    sl_value = latest_close + 5 * atr_value

                    open_trade(client, symbol, -volume, offset, tp_value, sl_value)
                    trade_start_time = time.time()
                    trade_just_opened = True
                    print(f"Opening short position. Take profit set at {tp_value}. Trailing offset is {offset}.")
                    print(f"Trade start time (from open_trade function): {trade_start_time}")
                    write_to_csv([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None, None, None,
                                  None, None, None, None, "Trade opened", "Short", tp_value, offset])
                elif prev_macd > prev_signal and macd < signal and abs(histogram - prev_histogram) < crossover_threshold and atr_value > atr_threshold:
                    print(f"The histogram difference was {histogram - prev_histogram}. Not opening the trade")

            if prev_histogram is not None and prev_prev_histogram is not None:
                if (
                        histogram < prev_histogram and prev_histogram > prev_prev_histogram):  # For positive histograms, indicating it's narrowing down
                    print("Histogram has changed direction from extending to narrowing (positive). Closing 0.01 pips.")
                    if positions['long']:
                        close_trade(client, 0, 0.01)  # Closing long position
                    elif positions['short']:
                        close_trade(client, 1, 0.01)  # Closing short position

                elif (
                        histogram > prev_histogram and prev_histogram < prev_prev_histogram):  # For negative histograms, indicating it's narrowing up
                    print("Histogram has changed direction from extending to narrowing (negative). Closing 0.01 pips.")
                    if positions['long']:
                        close_trade(client, 0, 0.01)  # Closing long position
                    elif positions['short']:
                        close_trade(client, 1, 0.01)  # Closing short position

            # Check for partial profit taking
            profit_threshold = 20  # Adjust the threshold as per your needs
            partial_close_volume = 0.01

            for profit in positions['long_profits']:
                if profit >= profit_threshold:
                    print(f"Partial profit taking for long position with profit: {profit}")
                    close_trade(client, 0, partial_close_volume)

            for profit in positions['short_profits']:
                if profit >= profit_threshold:
                    print(f"Partial profit taking for short position with profit: {profit}")
                    close_trade(client, 1, partial_close_volume)

            prev_macd = macd
            prev_signal = signal
            prev_prev_histogram = prev_histogram
            prev_histogram = histogram
            trade_just_opened = False

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

        # Sleep until the next minute plus one second
        sleep_time = seconds_until_next_minute() + 1
        time.sleep(sleep_time)

if __name__ == "__main__":
    buy_and_sell()