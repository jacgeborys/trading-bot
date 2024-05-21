from xAPIConnector import *
import time
import os
import math
import traceback
import pandas as pd

from fetch_data import get_last_period_prices, get_current_positions, seconds_until_next_minute, get_historical_data
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap, calculate_sma
from login import login_to_xtb
from trade import open_trade, close_all_trades, close_trade
from datetime import datetime, timedelta

class TradingBot:
    def __init__(self, client, symbol, crossover_threshold=0.1, atr_threshold=1, profit_threshold=15, second_profit_threshold=40, loss_threshold=-20, trailing_multiplier=2.0, volume=0.01, leverage=20, point_value=22.27):
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
        self.trailing_multiplier = trailing_multiplier
        self.prev_histogram = None
        self.trade_just_opened = False
        self.last_trade_action = 'None'
        self.data_log = pd.DataFrame()
        self.open_trades = []
        self.pending_orders = []
        self.trade_history = []
        self.leverage = leverage
        self.point_value = point_value
        self.prices, self.latest_open, self.latest_close, self.highs, self.lows, self.volume_data, self.positions = self.fetch_and_prepare_data()

    def fetch_and_prepare_data(self):
        # Fetch 1-minute data
        response = get_last_period_prices(self.client, self.symbol, period=1)
        if not response or len(response) != 6:
            print("Failed to fetch complete data or received incorrect data format.")
            return None, None, None, None, None, None

        prices, latest_open, latest_close, highs, lows, volume_data = response

        vwap = calculate_vwap(prices, volume_data)
        macd, signal, histogram = calculate_macd(prices)
        prices_5m, _, _, _, _, _ = get_last_period_prices(self.client, self.symbol, period=5)
        macd_5m, signal_5m, histogram_5m = calculate_macd(prices_5m)
        atr_value = calculate_atr(highs, lows, prices)
        sma = calculate_sma(prices, period=20)
        price_df = pd.DataFrame(prices, columns=['close'])
        rsi = calculate_rsi(price_df, window=15)

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
        self.rsi = rsi

        return prices, latest_open, latest_close, highs, lows, volume_data, self.positions

    def open_position(self, position_type, order_type='market', entry_price=None):
        volume = self.volume
        atr_value = self.atr_value

        tp_value = (entry_price + 1.0 * atr_value + 0.5) if position_type == 'long' else (entry_price - 1.0 * atr_value - 0.5)
        sl_value = (entry_price - 2.0 * atr_value) if position_type == 'long' else (entry_price + 2.0 * atr_value)
        trade_direction = volume if position_type == 'long' else -volume

        current_time = datetime.now()

        if order_type == 'market':
            self.open_trades.append({
                'type': position_type,
                'entry_price': entry_price,
                'tp': tp_value,
                'sl': sl_value,
                'volume': volume,
                'open_time': current_time,
                'status': 'open'
            })
            print(f"Simulated {position_type} position opened at {entry_price}, TP: {tp_value}, SL: {sl_value}")
        elif order_type == 'pending':
            self.pending_orders.append({
                'type': position_type,
                'entry_price': entry_price,
                'tp': tp_value,
                'sl': sl_value,
                'volume': volume,
                'status': 'pending',
                'order_time': current_time
            })
            print(f"Simulated pending {position_type} order set at {entry_price}, TP: {tp_value}, SL: {sl_value}")

    def check_pending_orders(self):
        current_time = datetime.now()
        new_pending_orders = []

        for order in self.pending_orders:
            # Check if order is older than 5 minutes
            if (current_time - order['order_time']).total_seconds() > 300:
                print(f"Pending {order['type']} order at {order['entry_price']} expired.")
                continue  # Skip adding this order to new_pending_orders

            if order['status'] == 'pending':
                if (order['type'] == 'long' and self.latest_low <= order['entry_price'] <= self.latest_high) or \
                   (order['type'] == 'short' and self.latest_high >= order['entry_price'] >= self.latest_low):
                    order['status'] = 'open'
                    order['open_time'] = current_time
                    order['entry_price'] = self.latest_close
                    self.open_trades.append(order)
                    print(f"Pending {order['type']} order triggered at {self.latest_close}")
                else:
                    new_pending_orders.append(order)

        self.pending_orders = new_pending_orders

    def update_trailing_stop(self, trade):
        atr_value = self.atr_value  # Use the current ATR value for trailing stop adjustment
        if trade['type'] == 'long':
            new_sl = self.latest_close - (self.trailing_multiplier * atr_value)
            trade['sl'] = max(trade['sl'], new_sl)
        elif trade['type'] == 'short':
            new_sl = self.latest_close + (self.trailing_multiplier * atr_value)
            trade['sl'] = min(trade['sl'], new_sl)

    def close_position(self, trade, close_price):
        if trade['status'] == 'closed':
            return

        trade['status'] = 'closed'
        trade['close_price'] = close_price
        trade['close_time'] = datetime.now()

        if trade['type'] == 'long':
            trade['profit'] = (close_price - trade['entry_price']) * trade['volume'] * self.point_value * self.leverage
        else:
            trade['profit'] = (trade['entry_price'] - close_price) * trade['volume'] * self.point_value * self.leverage

        self.trade_history.append(trade)
        print(f"Simulated {trade['type']} position closed at {close_price} with profit {trade['profit']}")

    def log_data(self, current_time):
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

    def backtest(self, start, end, period=1):
        close_prices, open_prices, high_prices, low_prices, volume = get_historical_data(self.client, self.symbol, period, start, end)

        if not close_prices:
            print("No historical data retrieved.")
            return

        print(f"Backtesting from {datetime.fromtimestamp(start / 1000)} to {datetime.fromtimestamp(end / 1000)}")

        for i in range(len(close_prices)):
            self.latest_close = close_prices[i]
            self.latest_open = open_prices[i]
            self.latest_high = high_prices[i]
            self.latest_low = low_prices[i]
            self.highs = high_prices[:i + 1]
            self.lows = low_prices[:i + 1]
            self.volume_data = volume[:i + 1]
            self.prices = close_prices[:i + 1]

            macd, signal, histogram = calculate_macd(self.prices)
            atr_value = calculate_atr(self.highs, self.lows, self.prices)
            sma = calculate_sma(self.prices, period=20)
            price_df = pd.DataFrame(self.prices, columns=['close'])
            rsi = calculate_rsi(price_df, window=15)
            vwap = calculate_vwap(self.prices, self.volume_data)

            self.macd = macd
            self.signal = signal
            self.histogram = histogram
            self.atr_value = atr_value
            self.sma = sma
            self.rsi = rsi
            self.vwap = vwap

            self.check_pending_orders()

            self.simulate_trading_logic(i)

        self.output_backtest_results()

    def simulate_trading_logic(self, index):
        if self.atr_value > 1:
            if self.prev_histogram is not None:
                if self.histogram > (self.prev_histogram + 0.01):
                    print(f"Simulated long trade at {self.latest_close} on bar {index}")
                    self.open_position('long', 'pending', self.latest_close + 1 * self.atr_value)
                elif self.histogram < (self.prev_histogram - 0.01):
                    print(f"Simulated short trade at {self.latest_close} on bar {index}")
                    self.open_position('short', 'pending', self.latest_close - 1 * self.atr_value)
            self.prev_histogram = self.histogram

        for trade in self.open_trades:
            if trade['status'] == 'open':
                self.update_trailing_stop(trade)
                if trade['type'] == 'long':
                    if self.latest_high >= trade['tp'] or self.latest_low <= trade['sl']:
                        self.close_position(trade, self.latest_close)
                elif trade['type'] == 'short':
                    if self.latest_low <= trade['tp'] or self.latest_high >= trade['sl']:
                        self.close_position(trade, self.latest_close)

    def output_backtest_results(self):
        total_profit = sum(trade['profit'] for trade in self.trade_history)
        num_trades = len(self.trade_history)
        win_trades = sum(1 for trade in self.trade_history if trade['profit'] > 0)
        loss_trades = sum(1 for trade in self.trade_history if trade['profit'] <= 0)
        win_rate = win_trades / num_trades if num_trades > 0 else 0
        max_drawdown = self.calculate_max_drawdown()

        print(f"Backtesting complete. Results:")
        print(f"Total Profit: {total_profit}")
        print(f"Number of Trades: {num_trades}")
        print(f"Winning Trades: {win_trades}")
        print(f"Losing Trades: {loss_trades}")
        print(f"Win Rate: {win_rate:.2%}")
        print(f"Max Drawdown: {max_drawdown}")

    def calculate_max_drawdown(self):
        peak = -float('inf')
        trough = float('inf')
        max_drawdown = 0

        for trade in self.trade_history:
            if trade['status'] == 'closed':
                peak = max(peak, trade['profit'])
                trough = min(trough, trade['profit'])
                drawdown = peak - trough
                max_drawdown = max(max_drawdown, drawdown)

        return max_drawdown

# Main execution logic for backtesting
if __name__ == "__main__":
    userId = os.environ.get("XTB_USERID")
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if client and ssid:
        bot = TradingBot(client, "US500", 0.01, 1)
        start_time = int(datetime(2024, 5, 17, 15, 30).timestamp() * 1000)
        end_time = int(datetime(2024, 5, 17, 21, 17).timestamp() * 1000)
        bot.backtest(start_time, end_time)