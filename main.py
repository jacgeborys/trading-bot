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
            time.sleep(5)
            return False

        prices_1m, latest_open_1m, latest_close_1m, highs_1m, lows_1m, volume_1m = response_1m

        # Store basic price data
        self.latest_close = latest_close_1m
        self.highs = highs_1m
        self.lows = lows_1m

        # Calculate ATR separately
        prices_df = pd.DataFrame(prices_1m, columns=['close'])
        self.atr_value = calculate_atr(highs_1m, lows_1m, prices_df['close']).iloc[-1]
        print(f"Calculated ATR value: {self.atr_value}")  # Debug print

        # Add delay before fetching 15-minute data
        time.sleep(2)

        # Fetch 15-minute data
        response_15m = get_last_period_prices(self.client, self.symbol, period=15)
        if not response_15m or len(response_15m) != 6:
            print("Failed to fetch 15-minute data.")
            time.sleep(5)
            return False

        prices_15m = response_15m[0]

        # Calculate MACD for both timeframes
        try:
            # 1-minute MACD
            macd_line_1m, signal_line_1m, histogram_1m = calculate_macd(pd.Series(prices_1m))
            if histogram_1m is not None:
                self.macd_histogram_1m = histogram_1m.values[-3:]
            else:
                print("Warning: 1m MACD calculation returned None")
                return False

            # 15-minute MACD
            macd_line_15m, signal_line_15m, histogram_15m = calculate_macd(pd.Series(prices_15m))
            if histogram_15m is not None:
                self.macd_histogram_15m = histogram_15m.values[-1]
                self.macd_15m = macd_line_15m.values[-1]
                self.signal_15m = signal_line_15m.values[-1]
            else:
                print("Warning: 15m MACD calculation returned None")
                return False

            # Debug prints
            print(f"1m MACD Histogram (last 3): {self.macd_histogram_1m}")
            print(f"15m MACD Histogram (latest): {self.macd_histogram_15m}")

        except Exception as e:
            print(f"Error in MACD calculations: {e}")
            return False

        time.sleep(1)

        # Fetch current positions
        self.positions = get_current_positions(self.client)

        time.sleep(1)

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

        tp_value = entry_price + (2.0 if position_type == 'long' else -2.0) * recent_range
        sl_value = entry_price + (-1.2 if position_type == 'long' else 1.2) * recent_range
        trade_direction = self.volume if position_type == 'long' else -self.volume

        time.sleep(1)

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
        Monitor trades and adjust TP/SL based on profit conditions:
        1. Reduce TP if profit isn't increasing
        2. Move SL to break-even + 0.5 when profit > 5
        """
        if not self.positions:
            print("No position data available.")
            return

        # Loop through both long and short trades
        for direction in ['long_profits', 'short_profits']:
            for trade in self.positions[direction]:
                order_id = trade['order']
                current_profit = trade['profit']
                current_tp = trade['tp']
                current_sl = trade['sl']
                opening_price = trade['open_price']

                # Initialize profit history if needed
                if order_id not in self.trade_profit_history:
                    self.trade_profit_history[order_id] = deque(maxlen=2)

                # Get last two recorded profits
                last_two_profits = list(self.trade_profit_history[order_id])

                # Check if we should move stop loss to break-even + 0.5
                if current_profit > 5:
                    is_long = direction == 'long_profits'
                    new_sl = opening_price + (0.5 if is_long else -0.5)

                    print(f"Trade {order_id} profit > 5 check:")
                    print(f"Direction: {direction}, Is Long: {is_long}")
                    print(f"Current profit: {current_profit}")
                    print(f"Current SL: {current_sl}")
                    print(f"Opening price: {opening_price}")
                    print(f"Calculated new SL: {round(new_sl, 1)}")

                    # Only modify if the new SL is better than current SL
                    sl_is_better = (is_long and new_sl > current_sl) or (not is_long and new_sl < current_sl)
                    print(f"SL is better? {sl_is_better}")
                    print(
                        f"For {'long' if is_long else 'short'} trade: {new_sl} {'>' if is_long else '<'} {current_sl}")

                    if sl_is_better:
                        print(f"Moving SL to break-even + 0.5 for trade {order_id}")
                        print(f"Opening price: {opening_price}, New SL: {round(new_sl, 1)}")
                        time.sleep(2)

                        # Modified trade command structure
                        modify_response = self.client.execute({
                            "command": "tradeTransaction",
                            "arguments": {
                                "tradeTransInfo": {
                                    "cmd": 0,  # Modify trade
                                    "order": order_id,
                                    "price": self.latest_close,
                                    "sl": round(new_sl, 1),
                                    "tp": current_tp,
                                    "symbol": self.symbol,
                                    "type": 3,  # Modification type
                                    "volume": trade['volume']
                                }
                            }
                        })
                        print(f"Modified SL to {round(new_sl, 1)}. Response: {modify_response}")
                        continue
                    else:
                        print(
                            f"Not modifying SL as new SL ({round(new_sl, 1)}) is not better than current SL ({current_sl})")
                else:
                    print(f"Trade {order_id} profit ({current_profit}) not > 5, skipping SL modification")

                # Check if profit hasn't increased - rest of the code remains the same
                if len(last_two_profits) == 2 and current_profit <= max(last_two_profits):
                    print(f"Trade {order_id}: Profit hasn't increased compared to the last two records.")
                    print(f"Current TP: {current_tp}, Current SL: {current_sl}")

                    time.sleep(2)

                    # Adjust take profit and stop loss based on direction
                    if direction == 'long_profits':
                        new_tp = current_tp - round(0.2 * self.atr_value, 1)
                        new_sl = current_sl + round(0.05 * self.atr_value, 1)
                        print(f"Decreasing TP for long trade {order_id}. New TP: {new_tp}")
                        print(f"Tightening SL for long trade {order_id}. New SL: {new_sl}")
                    else:  # short_profits
                        new_tp = current_tp + round(0.2 * self.atr_value, 1)
                        new_sl = current_sl - round(0.05 * self.atr_value, 1)
                        print(f"Increasing TP for short trade {order_id}. New TP: {new_tp}")
                        print(f"Tightening SL for short trade {order_id}. New SL: {new_sl}")

                    # Ensure values are rounded properly
                    new_tp = round(new_tp, 1)
                    new_sl = round(new_sl, 1)

                    # Use the same structure for modifying trades based on profit trend
                    modify_response = self.client.execute({
                        "command": "tradeTransaction",
                        "arguments": {
                            "tradeTransInfo": {
                                "cmd": 0,  # Modify trade
                                "order": order_id,
                                "price": self.latest_close,
                                "sl": new_sl,
                                "tp": new_tp,
                                "symbol": self.symbol,
                                "type": 3,  # Modification type
                                "volume": trade['volume']
                            }
                        }
                    })
                    print(
                        f"Modified trade {order_id}: adjusted TP to {new_tp} and SL to {new_sl}. Response: {modify_response}")

                # Update profit history
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
        last_check_minute = None

        while True:
            try:
                current_time = datetime.now()
                current_minute = current_time.replace(second=0, microsecond=0)

                # Only proceed if we're in a new minute
                if current_minute == last_check_minute:
                    remaining_seconds = 60 - current_time.second
                    print(f"Waiting for next minute... {remaining_seconds} seconds remaining")
                    time.sleep(min(remaining_seconds, 5))  # Sleep max 5 seconds at a time
                    continue

                print("-" * 50)
                print(f"Starting new minute check at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

                # Fetch new data
                self.last_trade_action = 'None'
                data_ready = self.fetch_and_prepare_data()
                if not data_ready:
                    print("Data not ready, skipping iteration.")
                    time.sleep(1)
                    continue

                # Print current market conditions
                print(f"Latest Close: {round(self.latest_close, 2)}")
                print(f"ATR: {round(self.atr_value, 2)}")
                print(f"MACD Histogram (1m): {self.macd_histogram_1m}")
                print(f"MACD Histogram (15m): {round(self.macd_histogram_15m, 3)}")

                # Run all minute-based operations
                self.manage_positions()
                self.monitor_and_reduce_tp()

                # Check trading conditions
                if len(self.macd_histogram_1m) == 3:
                    h1, h2, h3 = self.macd_histogram_1m

                    if all(abs(h) < 0.3 for h in [h1, h2, h3]):
                        print("All histogram values are below the |0.3| threshold. No trade.")
                    else:
                        # Check 15m trend strength
                        is_15m_strongly_bearish = self.macd_histogram_15m < -1.0
                        is_15m_strongly_bullish = self.macd_histogram_15m > 1.0

                        print(
                            f"15m MACD status - Strongly bearish: {is_15m_strongly_bearish}, Strongly bullish: {is_15m_strongly_bullish}")

                        # Trading logic
                        if h3 > 0 and (h2 - h1) > (h3 - h2):
                            if is_15m_strongly_bullish:
                                print("Skipping short trade due to strong bullish 15m trend")
                            else:
                                self.open_position('short', 'pending')
                                print("Placed short pending order based on decreasing positive MACD momentum.")
                                last_trade_time = current_time

                        elif h3 < 0 and (h2 - h1) < (h3 - h2):
                            if is_15m_strongly_bearish:
                                print("Skipping long trade due to strong bearish 15m trend")
                            else:
                                self.open_position('long', 'pending')
                                print("Placed long pending order based on decreasing negative MACD momentum.")
                                last_trade_time = current_time
                        else:
                            print("No trade signal based on MACD momentum.")
                else:
                    print("Not enough histogram data for decision-making.")

                # Update last check minute
                last_check_minute = current_minute

                # Calculate sleep time until next minute
                next_minute = current_minute + timedelta(minutes=1)
                sleep_time = (next_minute - datetime.now()).total_seconds() + 3
                print(f"All operations completed. Sleeping for {sleep_time:.2f} seconds until next minute.")
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