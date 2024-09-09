from xAPIConnector import *
import time
import os
import math
import traceback
import pandas as pd
import numpy as np

from fetch_data import get_last_period_prices, get_current_positions, seconds_until_next_minute
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap, calculate_sma, calculate_supertrend
from login import login_to_xtb
from trade import open_trade, close_all_trades, close_trade
from datetime import datetime, timedelta

class TradingBot:
    def __init__(self, client, symbol, crossover_threshold=0.1, atr_threshold=1, profit_threshold=3, second_profit_threshold=40, loss_threshold=-20, partial_close_volume_profitable=0.01, partial_close_volume_losing=0.01, volume=0.01):
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
        self.prev_histogram = None
        self.trade_just_opened = False
        self.last_trade_action = 'None'
        self.data_log = pd.DataFrame()
        self.prices, self.latest_open, self.latest_close, self.highs, self.lows, self.volume_data, self.positions = self.fetch_and_prepare_data()

    def fetch_and_prepare_data(self):
        # Ensure you fetch enough data points for ATR calculation
        response = get_last_period_prices(self.client, self.symbol, period=1)
        if not response or len(response) != 6:
            print("Failed to fetch complete data or received incorrect data format.")
            return None, None, None, None, None, None

        prices, latest_open, latest_close, highs, lows, volume_data = response

        # Make sure to fetch more data points for 14-period ATR calculation
        if len(prices) < 14 or len(highs) < 14 or len(lows) < 14:
            print("Not enough data points for ATR calculation. Skipping this iteration.")
            return prices, latest_open, latest_close, highs, lows, volume_data, None

        vwap = calculate_vwap(prices, volume_data)
        if vwap is None:
            print("VWAP calculation failed. VWAP is None.")
        macd, signal, histogram = calculate_macd(prices)
        prices_5m, _, _, _, _, _ = get_last_period_prices(self.client, self.symbol, period=5)
        macd_5m, signal_5m, histogram_5m = calculate_macd(prices_5m)
        atr_series = calculate_atr(highs, lows, prices)
        sma = calculate_sma(prices, period=20)
        price_df = pd.DataFrame(prices, columns=['close'])
        rsi = calculate_rsi(price_df, window=15)

        if len(highs) < 5 or len(lows) < 5 or len(prices) < 5:
            print("Not enough data points to calculate Supertrend. Skipping this iteration.")
            return prices, latest_open, latest_close, highs, lows, volume_data, None

        highs = np.array(highs)
        lows = np.array(lows)
        prices = np.array(prices)
        atr_series = np.array(atr_series)

        supertrend, supertrend_direction = calculate_supertrend(highs, lows, prices, atr_series)

        self.macd = macd
        self.signal = signal
        self.histogram = histogram
        self.macd_5m = macd_5m
        self.signal_5m = signal_5m
        self.histogram_5m = histogram_5m
        self.atr_value = atr_series[-1]
        self.vwap = vwap
        self.positions = get_current_positions(self.client)
        self.sma = sma
        self.latest_open = latest_open
        self.latest_close = latest_close
        self.rsi = rsi
        self.supertrend = supertrend
        self.supertrend_direction = supertrend_direction
        self.highs = highs
        self.lows = lows

        # Print the positions
        print("Current Positions:")
        print(f"Long positions: {self.positions['long_count']}")
        print(f"Short positions: {self.positions['short_count']}")
        print(f"Long profits: {self.positions['long_profits']}")
        print(f"Short profits: {self.positions['short_profits']}")

        return prices, latest_open, latest_close, highs, lows, volume_data, self.positions

    def open_position(self, position_type, order_type='market', entry_price=None):
        volume = self.volume
        atr_value = self.atr_value


        recent_high = max(self.highs[-10:])
        recent_low = min(self.lows[-10:])
        recent_range = recent_high - recent_low

        print(f"Recent high: {recent_high}, recent low: {recent_low}")
        print(f"ATR value: {atr_value}")
        print(f"Latest close: {self.latest_close}")

        offset = round(5.0 * recent_range, 1)

        if order_type == 'market':
            entry_price = self.latest_close
        elif order_type == 'pending' and entry_price is None:
            if position_type == 'long':
                entry_price = self.latest_close - 0.5 * atr_value
                print(f"Long position calculation: {self.latest_close} - 0.5 * {round(atr_value, 1)} = {round(entry_price, 1)}")
            else:
                entry_price = self.latest_close + 0.5 * atr_value
                print(f"Short position calculation: {self.latest_close} + 0.5 * {round(atr_value, 1)} = {round(entry_price, 1)}")

        entry_price = round(entry_price, 1)

        print(f"Position type: {position_type}")
        print(f"Calculated entry price: {entry_price}")

        # Dynamic take profit based on recent range
        tp_value = (entry_price + 0.8 * recent_range) if position_type == 'long' else (entry_price - 0.8 * recent_range)

        # Stop loss based on ATR
        sl_value = (entry_price - 1.2 * recent_range) if position_type == 'long' else (entry_price + 1.2 * recent_range)

        trade_direction = volume if position_type == 'long' else -volume

        time.sleep(2)
        open_trade(self.client, self.symbol, trade_direction, entry_price, self.latest_close, offset, tp_value,
                   sl_value, order_type)
        print(
            f"Opening {position_type} position as {order_type} order with volume {volume}, Entry Price: {round(entry_price, 2)}, TP: {round(tp_value, 2)}, SL: {round(sl_value, 2)}")
        self.last_trade_action = f"{position_type.capitalize()} {order_type.capitalize()} Opened"

    def modify_trade_offset(self, order_id, new_offset):
        trade_info = {
            "cmd": 3,  # MODIFY command
            "order": order_id,
            "offset": int(new_offset * 10),  # Convert to points
            "symbol": self.symbol,
            "type": 3  # Modify type
        }

        request = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": trade_info
            }
        }

        response = self.client.execute(request)
        print(f"Modified trade {order_id} with new offset: {new_offset}")
        return response

    def log_data(self, current_time):
        vwap = self.vwap if self.vwap is not None else 0  # Default to 0 if VWAP is None

        data = {
            'Time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'Latest Close': round(self.latest_close, 2),
            'High': round(self.highs[-1], 2),
            'Low': round(self.lows[-1], 2),
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
            'Supertrend': round(self.supertrend[-1], 2),
            'Supertrend Direction': self.supertrend_direction[-1],
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

    def manage_positions(self):
        for direction in ['long', 'short']:
            profits = self.positions[f'{direction}_profits']
            for i, profit in enumerate(profits):
                if isinstance(profit, dict):
                    order_id = profit.get('order')
                    profit_value = profit.get('profit')
                    if order_id and isinstance(profit_value, (int, float)) and profit_value >= self.profit_threshold:
                        new_offset = round(1.0 * self.atr_value, 1)  # Set new offset to 1.0 * ATR
                        time.sleep(3)  # Add delay before sending the request
                        response = self.modify_trade_offset(order_id, new_offset)
                        print(f"Modified {direction} position {i} with profit {profit_value}: {response}")

    def modify_trade_offset(self, order_id, new_offset):
        trade_info = {
            "cmd": 3,  # MODIFY command
            "order": order_id,
            "offset": int(new_offset * 10),  # Convert to points
            "symbol": self.symbol,
            "type": 3  # Modify type
        }

        request = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": trade_info
            }
        }

        response = self.client.execute(request)
        print(f"Modified trade {order_id} with new offset: {new_offset}")
        return response

    def run(self):
        last_trade_time = datetime.min
        reconnection_attempts = 0
        retry_attempts = 3

        while True:
            try:
                self.last_trade_action = 'None'
                response = self.fetch_and_prepare_data()
                if response is None:
                    print("Waiting before the next data request due to previous failure...")
                    time.sleep(2)
                    continue

                current_time = datetime.now()
                print("-" * 50)
                print(f"Checking conditions at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Latest Close: {round(self.latest_close, 2) if self.latest_close else 'Data Unavailable'}")
                print(f"ATR: {round(self.atr_value, 2) if self.atr_value else 'Data Unavailable'}")
                print(f"Supertrend: {self.supertrend[-1]}")
                print(f"Supertrend Direction: {self.supertrend_direction[-1]}")

                # Manage existing positions
                self.manage_positions()

                # Avoid trades during consolidation periods
                if self.supertrend_direction[-1] == 0:
                    print("Market is in consolidation. Skipping this iteration.")
                    time.sleep(seconds_until_next_minute() + 1)
                    continue

                if (current_time - last_trade_time).total_seconds() >= 59 and self.atr_value > 0.5:
                    if self.supertrend_direction[-1] == 1:
                        self.open_position('long', 'pending')
                        print(f"Attempted to set long pending order.")
                    elif self.supertrend_direction[-1] == -1:
                        self.open_position('short', 'pending')
                        print(f"Attempted to set short pending order.")

                    self.log_data(current_time)
                    last_trade_time = current_time

                sleep_time = seconds_until_next_minute() + 1
                print(f"Sleeping for {sleep_time} seconds.")
                time.sleep(sleep_time)

            except Exception as e:
                print(f"An unexpected error occurred: {str(e)}")
                traceback.print_exc()
                reconnection_attempts += 1
                if reconnection_attempts > retry_attempts:
                    print("Exceeded retry attempts. Exiting...")
                    break

                print(f"Re-trying connection. Attempt {reconnection_attempts}/{retry_attempts}...")
                time.sleep(10 * reconnection_attempts)
                self.client, _ = login_to_xtb(self.userId, self.password)
                if not self.client:
                    print("Failed to re-login. Exiting...")
                    break


if __name__ == "__main__":
    userId = os.environ.get("XTB_USERID")
    # userId = 16531572
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if client and ssid:
        bot = TradingBot(client, "US500", 0.01, 1)
        bot.run()