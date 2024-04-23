from xAPIConnector import *
import time
import os
import math
from datetime import datetime, timedelta
import traceback

from fetch_data import get_last_period_prices, get_current_positions, seconds_until_next_minute
from file_ops import write_to_csv
from indicators import calculate_macd, calculate_atr, calculate_rsi, calculate_vwap, calculate_sma
from login import login_to_xtb
from trade import open_trade, close_all_trades, close_trade

class TradingBot:
    def __init__(self, client, symbol, crossover_threshold=0.1, atr_threshold=1, profit_threshold=15, second_profit_threshold=40, loss_threshold=-20, partial_close_volume_profitable=0.01, partial_close_volume_losing=0.01, volume=0.03):
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
        self.prev_macd = None
        self.prev_signal = None
        self.prev_histogram = None
        self.prev_prev_histogram = None
        self.trade_just_opened = False
        self.prices, self.latest_open, self.latest_close, self.highs, self.lows, self.volume_data, self.positions = self.fetch_and_prepare_data()

    def fetch_and_prepare_data(self):
        response = get_last_period_prices(self.client, self.symbol, period=1)
        if not response or len(response) != 6:
            print("Failed to fetch complete data or received incorrect data format.")
            return None, None, None, None, None, None  # Return None for each expected value

        prices, latest_open, latest_close, highs, lows, volume_data = response
        macd, signal, histogram = calculate_macd(prices)
        atr_value = calculate_atr(highs, lows, prices)
        vwap = calculate_vwap(prices[-60:], volume_data[-60:])
        positions = get_current_positions(self.client)
        sma = calculate_sma(prices, period=20)

        self.macd = macd
        self.signal = signal
        self.histogram = histogram
        self.atr_value = atr_value
        self.vwap = vwap
        self.positions = positions
        self.sma = sma
        self.latest_open = latest_open
        self.latest_close = latest_close

        return prices, latest_open, latest_close, highs, lows, volume_data, positions

    def open_position(self, position_type):
        volume = self.volume
        atr_value = self.atr_value  # Use the ATR value computed during data fetch
        tp_value = (self.latest_close + 0.8 * atr_value) if position_type == 'long' else (
                    self.latest_close - 0.8 * atr_value)
        sl_value = (self.latest_close - 3 * atr_value) if position_type == 'long' else (
                    self.latest_close + 3 * atr_value)
        trade_direction = volume if position_type == 'long' else -volume

        time.sleep(2)  # Wait for 2 seconds before sending the trade request
        open_trade(self.client, self.symbol, trade_direction, tp_value, sl_value)
        print(
            f"Opening {position_type} position with volume {volume}, TP: {round(tp_value, 2)}, SL: {round(sl_value, 2)}")

    def get_macd_status(self, period):
        """Fetch prices for the specified period and determine if MACD is bullish or bearish."""
        prices, _, _, _, _, _ = get_last_period_prices(self.client, self.symbol, period)
        macd, signal, _ = calculate_macd(prices)
        return "bullish" if macd > signal else "bearish"

    def run(self):
        last_trade_time = datetime.min
        while True:
            try:
                response = self.fetch_and_prepare_data()
                if response is None:
                    print("Waiting before the next data request due to previous failure...")
                    time.sleep(2)  # Wait a bit longer if the data fetch failed
                    continue

                current_time = datetime.now()
                print("-" * 50)
                print(f"Checking conditions at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Latest Close: {round(self.latest_close, 2) if self.latest_close else 'Data Unavailable'}")
                print(
                    f"ATR: {round(self.atr_value, 2) if self.atr_value else 'Data Unavailable'}, VWAP: {round(self.vwap, 2) if self.vwap else 'Data Unavailable'}, SMA: {round(self.sma, 2) if self.sma else 'Data Unavailable'}")
                print(
                    f"MACD: {round(self.macd, 2) if self.macd else 'Data Unavailable'}, Signal: {round(self.signal, 2) if self.signal else 'Data Unavailable'}, Histogram: {round(self.histogram, 2) if self.histogram else 'Data Unavailable'}")

                # Print current open positions
                if self.positions:
                    print(
                        f"Open long positions: {self.positions['long_count']}, Open short positions: {self.positions['short_count']}")
                    print(
                        f"Long profits: {self.positions['long_profits']}, Short profits: {self.positions['short_profits']}")

                if (current_time - last_trade_time).total_seconds() >= 119:
                    macd_status_1m = self.get_macd_status(1)
                    macd_status_5m = self.get_macd_status(5)
                    print(f"MACD Status 1m: {macd_status_1m}, MACD Status 5m: {macd_status_5m}")

                    if macd_status_1m == "bullish" and macd_status_5m == "bullish":
                        self.open_position('long')
                        print("Opened a long position.")
                    elif macd_status_1m == "bearish" and macd_status_5m == "bearish":
                        self.open_position('short')
                        print("Opened a short position.")
                    else:
                        print("No trade executed. Conditions not met.")

                    last_trade_time = current_time

                sleep_time = seconds_until_next_minute() + 1
                print(f"Sleeping for {sleep_time} seconds.")
                time.sleep(sleep_time)

            except Exception as e:
                print(f"An unexpected error occurred: {str(e)}")
                traceback.print_exc()
                break


# Main execution logic
if __name__ == "__main__":
    userId = os.environ.get("XTB_USERID")
    password = os.environ.get("XTB_PASSWORD")
    client, ssid = login_to_xtb(userId, password)
    if client and ssid:
        bot = TradingBot(client, "US500", 0.01, 1)
        bot.run()  # Start the trading bot
