from xAPIConnector import *
import time
import os
import math
from datetime import datetime, timedelta
import traceback
import pandas as pd

from fetch_data import get_last_period_prices, get_current_positions, seconds_until_next_minute
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap, calculate_sma
from login import login_to_xtb
from trade import open_trade, close_all_trades, close_trade

class TradingBot:
    def __init__(self, client, symbol, crossover_threshold=0.1, atr_threshold=1, profit_threshold=15, second_profit_threshold=40, loss_threshold=-20, partial_close_volume_profitable=0.01, partial_close_volume_losing=0.01, volume=0.01):
        self.volume = volume
        self.client = client
        self.retry_attempts = 3
        self.wait_time = 30
        self.symbol = symbol
        self.crossover_threshold = crossover_threshold
        self.atr_threshold = atr_threshold
        self.profit_threshold = profit_threshold
        self.second_profit_threshold = second_profit_threshold
        self.loss_threshold = loss_threshold
        self.partial_close_volume_profitable = partial_close_volume_profitable
        self.partial_close_volume_losing = partial_close_volume_losing
        self.prev_macd = None
        self.prev_signal = None
        self.prev_histogram = None
        self.prev_prev_histogram = None
        self.trade_just_opened = False
        self.last_trade_action = 'None'  # Initialize the last trade action
        self.data_log = pd.DataFrame()  # Initialize DataFrame for logging
        self.prices, self.latest_open, self.latest_close, self.highs, self.lows, self.volume_data, self.positions = self.fetch_and_prepare_data()

    def fetch_and_prepare_data(self):
        # Fetch 1-minute data
        response = get_last_period_prices(self.client, self.symbol, period=1)
        if not response or len(response) != 6:
            print("Failed to fetch complete data or received incorrect data format.")
            return None, None, None, None, None, None  # Return None for each expected value

        prices, latest_open, latest_close, highs, lows, volume_data = response

        # Call your volume indicators with correct data
        vwap = calculate_vwap(prices, volume_data)

        # MACD calculations
        macd, signal, histogram = calculate_macd(prices)
        prices_5m, _, _, _, _, _ = get_last_period_prices(self.client, self.symbol, period=5)
        macd_5m, signal_5m, histogram_5m = calculate_macd(prices_5m)

        atr_value = calculate_atr(highs, lows, prices)
        sma = calculate_sma(prices, period=20)

        # Convert prices list to a DataFrame for RSI calculation
        price_df = pd.DataFrame(prices, columns=['close'])
        rsi = calculate_rsi(price_df, window=15)

        # Store all computed values
        self.macd = macd
        self.signal = signal
        self.histogram = histogram
        self.macd_5m = macd_5m
        self.signal_5m = signal_5m
        self.histogram_5m = histogram_5m
        self.atr_value = atr_value
        self.vwap = vwap
        self.positions = get_current_positions(self.client)
        self.sma = sma
        self.latest_open = latest_open
        self.latest_close = latest_close
        self.rsi = rsi  # Save RSI to be used later

        return prices, latest_open, latest_close, highs, lows, volume_data, self.positions

    def open_position(self, position_type, order_type='market', entry_price=None):
        volume = self.volume
        atr_value = self.atr_value  # Use the ATR value computed during data fetch
        offset = round(2.0 * atr_value, 1)

        if order_type == 'market':
            # Market orders use the latest close as the entry price
            entry_price = self.latest_close
        elif order_type == 'pending' and entry_price is None:
            # For pending orders, calculate it based on the position type
            entry_price = (self.latest_close + atr_value) if position_type == 'long' else (
                        self.latest_close - atr_value)

        # Calculate TP and SL based on the entry price for more accurate order setup
        tp_value = (entry_price + 5.0 * atr_value + 0.5) if position_type == 'long' else (entry_price - 5.0 * atr_value - 0.5)
        sl_value = (entry_price - 6.0 * atr_value) if position_type == 'long' else (entry_price + 6.0 * atr_value)
        trade_direction = volume if position_type == 'long' else -volume

        time.sleep(2)  # Wait for 2 seconds before sending the trade request
        open_trade(self.client, self.symbol, trade_direction, entry_price, self.latest_close, offset, tp_value,
                   sl_value, order_type)
        print(
            f"Opening {position_type} position as {order_type} order with volume {volume}, Entry Price: {round(entry_price, 2)}, TP: {round(tp_value, 2)}, SL: {round(sl_value, 2)}")

        # Record the action
        self.last_trade_action = f"{position_type.capitalize()} {order_type.capitalize()} Opened"

    def log_data(self, current_time):
        # Calculate additional indicators
        vwap = calculate_vwap([self.latest_close] * len(self.highs), self.volume_data)

        data = {
            'Time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'Latest Close': round(self.latest_close, 2),
            'ATR': round(self.atr_value, 2),
            'VWAP': round(vwap, 2),
            'SMA': round(self.sma, 2),
            'RSI': round(self.rsi, 2),
            'MACD': round(self.macd, 2),
            'Signal': round(self.signal, 2),
            'Histogram': round(self.histogram, 2),
            'MACD 5m': round(self.macd_5m, 2),
            'Signal 5m': round(self.signal_5m, 2),
            'Histogram 5m': round(self.histogram_5m, 2),
            'Long Positions': self.positions['long_count'],
            'Short Positions': self.positions['short_count'],
            'Long Profits': self.positions['long_profits'],
            'Short Profits': self.positions['short_profits'],
            'Trade Executed': self.last_trade_action
        }
        new_entry = pd.DataFrame([data])
        self.data_log = pd.concat([self.data_log, new_entry], ignore_index=True)
        if len(self.data_log) % 5 == 0:
            self.data_log.to_csv('C:/Users/Asus/OneDrive/Pulpit/Rozne/Python/XTB/_script/excel/trading_log.csv',
                                 index=False)
            print("Data log saved to Excel.")

    def run(self):
        last_trade_time = datetime.min
        reconnection_attempts = 0  # Counter for reconnection attempts
        retry_attempts = 3

        while True:
            try:
                self.last_trade_action = 'None'  # Reset the trade action for this iteration
                response = self.fetch_and_prepare_data()
                if response is None:
                    print("Waiting before the next data request due to previous failure...")
                    time.sleep(2)  # Wait a bit longer if the data fetch failed
                    continue

                current_time = datetime.now()
                print("-" * 50)
                print(f"Checking conditions at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Latest Close: {round(self.latest_close, 2) if self.latest_close else 'Data Unavailable'}")
                print(f"ATR: {round(self.atr_value, 2) if self.atr_value else 'Data Unavailable'}")
                print(f"Histogram: {round(self.histogram, 2) if self.histogram else 'Data Unavailable'}")

                if (current_time - last_trade_time).total_seconds() >= 59 and self.atr_value > 1 and abs(
                        self.histogram) > 0.2:
                    macd_status_1m = "bullish" if self.macd > self.signal else "bearish"
                    print(f"MACD Status 1m: {macd_status_1m}")

                    if macd_status_1m == "bullish":
                        entry_price = self.latest_close + 0.6 * self.atr_value
                        entry_price = round(entry_price, 1)
                        self.open_position('long', 'pending', entry_price)
                        print(f"Set long pending order at price {entry_price}.")
                    elif macd_status_1m == "bearish":
                        entry_price = self.latest_close - 0.6 * self.atr_value
                        entry_price = round(entry_price, 1)
                        self.open_position('short', 'pending', entry_price)
                        print(f"Set short pending order at price {entry_price}.")
                    else:
                        print("No trade executed. Conditions not met.")

                    self.log_data(current_time)  # Log the data to the DataFrame
                    last_trade_time = current_time

                sleep_time = seconds_until_next_minute() + 1
                print(f"Sleeping for {sleep_time} seconds.")
                time.sleep(sleep_time)

            except (TimeoutError, ConnectionError) as e:
                # Handle the timeout or connection error
                print(f"Encountered a connection issue: {str(e)}")
                reconnection_attempts += 1
                if reconnection_attempts > retry_attempts:
                    print("Exceeded retry attempts. Exiting...")
                    break

                print(f"Re-trying connection. Attempt {reconnection_attempts}/{retry_attempts}...")
                time.sleep(10 * reconnection_attempts)  # Increase delay with each attempt

                # Re-login to the platform
                self.client, _ = login_to_xtb(self.userId, self.password)
                if not self.client:
                    print("Failed to re-login. Exiting...")
                    break

            except Exception as e:
                print(f"An unexpected error occurred: {str(e)}")
                traceback.print_exc()  # This will print the entire stack trace
                break


# Main execution logic
if __name__ == "__main__":
    userId = os.environ.get("XTB_USERID")
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if client and ssid:
        bot = TradingBot(client, "US500", 0.01, 1)
        bot.run()  # Start the trading bot