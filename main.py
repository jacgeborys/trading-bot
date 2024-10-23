from xAPIConnector import *
import time
import os
import math
import traceback
import pandas as pd
import numpy as np
from collections import deque
from datetime import datetime, timedelta
from collections import deque

from fetch_data import get_last_period_prices, get_current_positions, seconds_until_next_minute
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap, calculate_sma, calculate_supertrend
from login import login_to_xtb
from trade import open_trade, close_all_trades, close_trade, partial_close_trade, modify_trade


class TradingBot:
    def __init__(self, client, symbol, crossover_threshold=0.1, atr_threshold=1, profit_threshold=3,
                 second_profit_threshold=40, loss_threshold=-40, partial_close_volume_profitable=0.01,
                 partial_close_volume_losing=0.01, volume=0.01):
        self.volume = volume
        self.client = client
        self.symbol = symbol
        self.crossover_threshold = crossover_threshold
        self.atr_threshold = atr_threshold
        self.profit_threshold = profit_threshold
        self.second_profit_threshold = second_profit_threshold
        self.loss_threshold = loss_threshold
        self.partial_close_volume_profitable = partial_close_volume_profitable
        self.partial_close_volume_losing = partial_close_volume_losing
        self.trade_just_opened = False
        self.last_trade_action = 'None'
        self.data_log = pd.DataFrame()

        # New additions for rate limiting and action queue
        self.last_action_time = time.time()
        self.action_queue = deque()
        self.min_action_interval = 5  # Minimum time between actions in seconds

        # Initialize attributes for indicators and prices
        self.prices = None
        self.latest_open = None
        self.latest_close = None
        self.highs = None
        self.lows = None
        self.volume_data = None
        self.positions = None
        self.atr_value = None
        self.macd_histogram_1m = None

        # Initialize profit history tracking for dynamic TP/SL
        self.trade_profit_history = {}  # Store the last two profit values for each trade

        # Fetch initial data
        self.fetch_and_prepare_data()

        self.trade_profit_timestamps = {}  # Track profit timestamps for each trade

    def fetch_and_prepare_data(self):
        # Fetch 1-minute data
        response_1m = get_last_period_prices(self.client, self.symbol, period=1)
        if not response_1m or len(response_1m) != 6:
            print("Failed to fetch 1-minute data.")
            time.sleep(5)  # Add delay to avoid frequent requests
            return False

        prices_1m, latest_open_1m, latest_close_1m, highs_1m, lows_1m, volume_1m = response_1m

        # Ensure sufficient data for MACD calculation (at least 26 candles)
        if len(prices_1m) < 26:
            print("Not enough data points for MACD calculation.")
            time.sleep(5)  # Add delay to avoid frequent requests
            return False

        # Calculate MACD for 1-minute data
        macd_line_1m, signal_line_1m, histogram_1m = calculate_macd(pd.DataFrame(prices_1m, columns=['close'])['close'])

        # Extract the last 3 histogram values for momentum analysis
        self.macd_histogram_1m = histogram_1m[-3:].values  # Last 3 histogram values

        # Calculate ATR for risk management
        atr_1m = calculate_atr(highs_1m, lows_1m, prices_1m)

        # Store the latest close price, highs, lows, and ATR value
        self.latest_close = latest_close_1m
        self.highs = highs_1m  # Store highs for later use
        self.lows = lows_1m  # Store lows for later use
        self.atr_value = atr_1m.iloc[-1]  # Store the most recent ATR value

        time.sleep(1)

        # Fetch current positions
        self.positions = get_current_positions(self.client)

        # Add a delay after fetching data to avoid rate-limiting
        time.sleep(2)

        return True

    def open_position(self, position_type, order_type='market', entry_price=None):
        # Check that highs and lows are available
        if self.highs is None or self.lows is None:
            print("Highs or lows data not available, cannot open position.")
            return

        recent_high, recent_low = max(self.highs[-10:]), min(self.lows[-10:])
        recent_range = recent_high - recent_low
        offset = round(5.0 * recent_range, 1)

        print(f"Recent high: {recent_high}, recent low: {recent_low}")
        print(f"ATR value: {self.atr_value}")
        print(f"Latest close: {self.latest_close}")

        if order_type == 'market':
            entry_price = self.latest_close
        elif order_type == 'pending' and entry_price is None:
            entry_price = self.latest_close + (-0.5 if position_type == 'long' else 0.5) * self.atr_value
            print(
                f"{position_type.capitalize()} position calculation: {self.latest_close} {'-' if position_type == 'long' else '+'} 0.5 * {round(self.atr_value, 1)} = {round(entry_price, 1)}")

        entry_price = round(entry_price, 1)
        print(f"Position type: {position_type}")
        print(f"Calculated entry price: {entry_price}")

        tp_value = entry_price + (1.8 if position_type == 'long' else -1.8) * recent_range
        sl_value = entry_price + (-1.2 if position_type == 'long' else 1.2) * recent_range
        trade_direction = self.volume if position_type == 'long' else -self.volume

        time.sleep(2)

        open_trade(self.client, self.symbol, trade_direction, entry_price, self.latest_close, offset, tp_value,
                   sl_value, order_type)
        print(
            f"Opening {position_type} position as {order_type} order with volume {self.volume}, Entry Price: {round(entry_price, 2)}, TP: {round(tp_value, 2)}, SL: {round(sl_value, 2)}")
        self.last_trade_action = f"{position_type.capitalize()} {order_type.capitalize()} Opened"

    def close_partial_position(self, direction, reason):
        min_trade_size = 0.01
        close_volume = 0.01

        profits = self.positions[f'{direction}_profits']
        if profits:
            trade_to_close = profits[0]
            order_id = trade_to_close.get('order')
            current_volume = trade_to_close.get('volume')
            if order_id and current_volume >= min_trade_size:
                # Ensure close_volume is at least min_trade_size and not more than current_volume
                close_volume = max(min(close_volume, current_volume), min_trade_size)
                cmd = 0 if direction == 'long' else 1  # 0 for closing long, 1 for closing short
                response = partial_close_trade(self.client, self.symbol, order_id, close_volume, cmd)
                print(
                    f"Attempting to partially close {direction} position with order ID {order_id} due to total {reason}. Close volume: {close_volume}.")
                print(f"Response: {response}")
            else:
                print(
                    f"Cannot partially close {direction} trade {order_id}; current volume {current_volume} is less than minimum trade size {min_trade_size}.")
        else:
            print(f"No {direction} positions to partially close.")

    from collections import deque

    def monitor_and_reduce_tp(self):
        """
        Check if any trades' profits haven't increased over the last two recorded profits
        and adjust both take profit (TP) and stop loss (SL).
        """
        # Ensure self.positions has the latest data
        if not self.positions:
            print("No position data available.")
            return

        # Loop through both long and short trades
        for direction in ['long_profits', 'short_profits']:
            for trade in self.positions[direction]:
                order_id = trade['order']
                current_profit = trade['profit']
                current_tp = trade.get('tp', (self.latest_close + 8) if direction == 'long_profits' else (
                            self.latest_close - 8))
                current_sl = trade.get('sl', (self.latest_close - 5) if direction == 'long_profits' else (
                            self.latest_close + 5))

                # If this is the first time seeing this trade, initialize its profit history
                if order_id not in self.trade_profit_history:
                    self.trade_profit_history[order_id] = deque(maxlen=2)  # Store up to 2 last profits

                # Get the last two recorded profits (if they exist)
                last_two_profits = list(self.trade_profit_history[order_id])

                # Compare current profit with the last two recorded profits (if any)
                if len(last_two_profits) == 2 and current_profit <= max(last_two_profits):
                    # The profit hasn't increased, so we adjust the TP and SL
                    print(f"Trade {order_id}: Profit hasn't increased compared to the last two records.")
                    print(f"Current TP: {current_tp}, Current SL: {current_sl}")

                    # Offset to avoid overloading the server with too many requests at once
                    time.sleep(2)

                    # Adjust take profit and stop loss based on direction
                    if direction == 'long_profits':
                        # Decrease TP and tighten SL for long trades
                        new_tp = current_tp - round(0.3 * self.atr_value, 1)
                        new_sl = current_sl + round(0.1 * self.atr_value, 1)  # Tighten SL by increasing it
                        print(f"Decreasing TP for long trade {order_id}. New TP: {new_tp}")
                        print(f"Tightening SL for long trade {order_id}. New SL: {new_sl}")
                    elif direction == 'short_profits':
                        # Increase TP and tighten SL for short trades
                        new_tp = current_tp + round(0.3 * self.atr_value, 1)
                        new_sl = current_sl - round(0.1 * self.atr_value, 1)  # Tighten SL by decreasing it
                        print(f"Increasing TP for short trade {order_id}. New TP: {new_tp}")
                        print(f"Tightening SL for short trade {order_id}. New SL: {new_sl}")

                    # Ensure values are rounded properly
                    new_tp = round(new_tp, 1)
                    new_sl = round(new_sl, 1)

                    # Use modify_trade to update both TP and SL
                    modify_response = modify_trade(self.client, order_id, 0, new_sl, new_tp, 0.01)
                    print(
                        f"Modified trade {order_id}: adjusted TP to {new_tp} and SL to {new_sl}. Response: {modify_response}")

                # Always update the profit history with the current profit
                self.trade_profit_history[order_id].append(current_profit)

    def log_data(self, current_time):
        vwap = self.vwap if self.vwap is not None else 0
        total_long_profit = sum(trade['profit'] for trade in self.positions['long_profits'])
        total_short_profit = sum(trade['profit'] for trade in self.positions['short_profits'])

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
            'Total Long Profit': round(total_long_profit, 2),
            'Total Short Profit': round(total_short_profit, 2),
            'Overall Total Profit': round(total_long_profit + total_short_profit, 2),
            'Trade Executed': self.last_trade_action
        }
        new_entry = pd.DataFrame([data])
        self.data_log = pd.concat([self.data_log, new_entry], ignore_index=True)
        if len(self.data_log) % 5 == 0:
            self.data_log.to_csv('C:/Users/Asus/OneDrive/Pulpit/Rozne/Python/XTB/_script/excel/trading_log.csv',
                                 index=False)
            print("Data log saved to Excel.")

    def manage_positions(self):
        long_profit = sum(trade['profit'] for trade in self.positions['long_profits'])
        short_profit = sum(trade['profit'] for trade in self.positions['short_profits'])

        print(f"Total Long Profit: {round(long_profit, 2)}")
        print(f"Total Short Profit: {round(short_profit, 2)}")

        current_time = time.time()
        if current_time - self.last_action_time < self.min_action_interval:
            print(
                f"Waiting {self.min_action_interval - (current_time - self.last_action_time):.2f} seconds before next action")
            return

        if long_profit <= -60:
            self.action_queue.append(('long', 'loss'))
        elif long_profit >= 90:
            self.action_queue.append(('long', 'profit'))

        if short_profit <= -60:
            self.action_queue.append(('short', 'loss'))
        elif short_profit >= 90:
            self.action_queue.append(('short', 'profit'))

        if self.action_queue:
            direction, reason = self.action_queue.popleft()
            self.close_partial_position(direction, reason)
            self.last_action_time = time.time()

    def run(self):
        last_trade_time = datetime.min
        reconnection_attempts = 0
        retry_attempts = 3

        while True:
            try:
                self.last_trade_action = 'None'
                data_ready = self.fetch_and_prepare_data()
                if not data_ready:
                    print("Data not ready, skipping iteration.")
                    time.sleep(2)
                    continue

                current_time = datetime.now()
                print("-" * 50)
                print(f"Checking conditions at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Latest Close: {round(self.latest_close, 2)}")
                print(f"ATR: {round(self.atr_value, 2)}")
                print(f"MACD Histogram (1m): {self.macd_histogram_1m}")

                self.manage_positions()

                # Check and adjust TP and SL dynamically based on profit trends
                self.monitor_and_reduce_tp()

                # Ensure we have 3 histogram values for momentum analysis
                if len(self.macd_histogram_1m) == 3:
                    h1, h2, h3 = self.macd_histogram_1m  # h1 is the oldest, h3 is the most recent

                    # No trade condition: if all three histogram values are within ±0.3
                    if all(abs(h) < 0.3 for h in [h1, h2, h3]):
                        print("All histogram values are below the |0.3| threshold. No trade.")
                        continue

                    # Short Trade: If the histogram is positive but momentum is decreasing or reverting
                    if h3 > 0 and (h2 - h1) > (h3 - h2):
                        # Place a short pending order
                        self.open_position('short', 'pending')
                        print("Placed short pending order based on decreasing positive MACD momentum.")
                        last_trade_time = current_time

                    # Long Trade: If the histogram is negative but losing downward momentum or reverting
                    elif h3 < 0 and (h2 - h1) < (h3 - h2):
                        # Place a long pending order
                        self.open_position('long', 'pending')
                        print("Placed long pending order based on decreasing negative MACD momentum.")
                        last_trade_time = current_time

                    else:
                        print("No trade signal based on MACD momentum.")
                else:
                    print("Not enough histogram data for decision-making.")

                # Slightly increase the sleep time to avoid hitting the rate limit
                sleep_time = seconds_until_next_minute() + 3  # Increased sleep time by 3 seconds
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
                self.client, _ = login_to_xtb(userId, password)
                if not self.client:
                    print("Failed to re-login. Exiting...")
                    break


if __name__ == "__main__":
    userId = os.environ.get("XTB_USERID")
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if client and ssid:
        bot = TradingBot(client, "US500", volume=0.01)
        bot.run()