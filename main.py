from xAPIConnector import *
import time
import os
import math
import datetime

from fetch_data import get_last_period_prices, get_current_positions, seconds_until_next_minute
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap, calculate_sma
from login import login_to_xtb
from trade import open_trade, close_all_trades, close_trade

def buy_and_sell(symbol="US500"):
    # Global Variables
    trade_just_opened = False

    userId = os.environ.get("XTB_USERID")
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if not client or not ssid:
        return

    prev_macd, prev_signal, prev_histogram, prev_prev_histogram = None, None, None, None
    crossover_threshold, atr_threshold = 0.1, 1
    attempts, wait_time, retry_attempts = 0, 60, 3
    profit_threshold = 15  # For partial profit-taking
    second_profit_threshold = 40
    loss_threshold = 40
    partial_close_volume_profitable = 0.01
    second_partial_close_volume_profitable = 0.02
    partial_close_volume_crossover = 0.01
    partial_close_volume_losing = 0.01

    attempts = 0

    while True:
        try:
            print("-" * 50)

            # Fetch and prepare data
            prices, latest_open, latest_close, highs, lows, volume_data = get_last_period_prices(client, symbol, period=1)
            macd, signal, histogram = calculate_macd(prices)
            atr_value = calculate_atr(highs, lows, prices)
            vwap = calculate_vwap(prices[-60:], volume_data[-60:])
            positions = get_current_positions(client)
            sma = calculate_sma(prices, period=20)

            # Determine volume based on SMA for MACD crossover
            volume = 0.08  # Default volume

            if prev_macd is not None and prev_signal is not None and prev_histogram is not None:
                # Bullish Crossover: Enter trade if low below SMA, reduce volume if above SMA - 1
                if prev_macd < prev_signal and macd > signal:
                    if latest_close > sma - 1:
                        volume = 0.04  # Decrease volume if price is above SMA by more than 1 unit

                # Bearish Crossover: Enter trade if high above SMA, reduce volume if below SMA + 1
                elif prev_macd > prev_signal and macd < signal:
                    if latest_close < sma + 1:
                        volume = 0.04  # Decrease volume if price is below SMA by more than 1 unit

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

            if latest_close > (sma + 1):
                print("Price higher than SMA + 1")
            elif latest_close < (sma - 1):
                print("Price lower than SMA - 1")
            else:
                print("Price close to SMA")

            log_data = [datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), latest_open, latest_close,
                        macd, signal, sma, atr_value]
            write_to_csv(log_data)

            print("-" * 10)
            print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
            print(f"Opening Price: {latest_open}")
            print(f"Closing Price: {latest_close}")
            print(f"MACD: {macd}")
            print(f"Signal Line: {signal}")
            print((f"Histogram: {histogram}, previous histogram: {prev_histogram}"))
            print(f"ATR: {atr_value}")
            print(f"SMA: {sma}")
            print(f"Number of open long positions: {positions['long_count']}")
            print(f"Number of open short positions: {positions['short_count']}")
            print("-" * 10)

            # MACD-based logic
            if prev_macd is not None and prev_signal is not None and prev_histogram is not None:
                if prev_macd < prev_signal and macd > signal:

                    print(f"Bullish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if positions['short']:
                        print(f"Closing {partial_close_volume_crossover} of short position.")
                        close_trade(client, 1, partial_close_volume_crossover)  # 1 for short position
                    else:
                        print("No short positions to partially close")

                    if abs(histogram - prev_histogram) > crossover_threshold and atr_value > atr_threshold:
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
                    else:
                        print(f"The histogram difference was {histogram - prev_histogram}. Not opening the trade")

                elif prev_macd > prev_signal and macd < signal:

                    print(f"Bearish crossover detected at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                    if positions['long']:
                        print(f"Closing {partial_close_volume_crossover} of long position.")
                        close_trade(client, 0, partial_close_volume_crossover)  # 0 for long position
                    else:
                        print("No long positions to partially close")

                    if abs(histogram - prev_histogram) > crossover_threshold and atr_value > atr_threshold:
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
                    else:
                        print(f"The histogram difference was {histogram - prev_histogram}. Not opening the trade")

            # if prev_histogram is not None and prev_prev_histogram is not None:
            #     if (
            #             histogram < prev_histogram and prev_histogram > prev_prev_histogram):  # For positive histograms, indicating it's narrowing down
            #         print("Histogram has changed direction from extending to narrowing (positive). Closing 0.01 pips.")
            #         if positions['long']:
            #             close_trade(client, 0, 0.01)  # Closing long position
            #         elif positions['short']:
            #             close_trade(client, 1, 0.01)  # Closing short position
            #
            #     elif (
            #             histogram > prev_histogram and prev_histogram < prev_prev_histogram):  # For negative histograms, indicating it's narrowing up
            #         print("Histogram has changed direction from extending to narrowing (negative). Closing 0.01 pips.")
            #         if positions['long']:
            #             close_trade(client, 0, 0.01)  # Closing long position
            #         elif positions['short']:
            #             close_trade(client, 1, 0.01)  # Closing short position

            for profit in positions['long_profits']:
                if profit > second_profit_threshold:
                    print(f"Partial profit taking for long position with profit: {profit}")
                    close_trade(client, 0, second_partial_close_volume_profitable, min_profit=second_profit_threshold)
                elif profit > profit_threshold:
                    print(f"Partial profit taking for long position with profit: {profit}")
                    close_trade(client, 0, partial_close_volume_profitable, min_profit=profit_threshold)
                elif profit < -loss_threshold:  # Notice the condition change here
                    print(f"Partial loss saving for long position with loss: {profit}")
                    close_trade(client, 0, partial_close_volume_losing, max_loss=-loss_threshold)

            # For short positions
            for profit in positions['short_profits']:
                if profit > second_profit_threshold:
                    print(f"Partial profit taking for short position with profit: {profit}")
                    close_trade(client, 1, second_partial_close_volume_profitable, min_profit=second_profit_threshold)
                elif profit > profit_threshold:
                    print(f"Partial profit taking for short position with profit: {profit}")
                    close_trade(client, 1, partial_close_volume_profitable, min_profit=profit_threshold)
                elif profit < -loss_threshold:  # Use a consistent negative threshold for losses
                    print(f"Partial loss saving for short position with loss: {profit}")
                    close_trade(client, 1, partial_close_volume_losing, max_loss=-loss_threshold)

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