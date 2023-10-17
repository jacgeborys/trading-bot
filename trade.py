from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def open_trade(client, symbol, volume, offset, tp_value = 0.0, sl_value = 0.0):

    offset = int(10 * offset)
    tp_value = round(tp_value, 1)
    sl_value = round(sl_value, 1)

    if volume > 0:
        cmd_value = 0  # BUY
    else:
        cmd_value = 1  # SELL
        volume = abs(volume)

    trade_info = {
        "cmd": cmd_value,
        "customComment": "Trading based on MA crossover",  # An example custom comment
        "expiration": 0,  # If you're not using pending orders, you can set this to 0
        "offset": offset,
        "order": 0,  # 0 for opening new trades
        "price": 1,  # Assuming market order, otherwise provide a price
        "sl": sl_value,
        "symbol": symbol,
        "tp": tp_value,
        "type": 0,  # Since we're opening a new order
        "volume": volume
    }

    request = {
        "command": "tradeTransaction",
        "arguments": {
            "tradeTransInfo": trade_info
        }
    }

    response = client.execute(request)
    return response

def close_all_trades(client):
    # Get all open trades
    trades_response = client.execute({"command": "getTrades", "arguments": {"openedOnly": True}})
    trades = trades_response.get("returnData", [])

    if not trades:
        print("No trades to close.")
        return

    for trade in trades:
        # Extract trade details
        close_price = trade["close_price"]
        symbol = trade["symbol"]
        order = trade["order"]
        volume = trade["volume"]

        # Prepare closing payload
        payload = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": {
                    "cmd": 0,  # Assuming you are buying to close (adjust as per your need)
                    "type": 2,  # Close order
                    "price": close_price,
                    # "sl": 0.0,
                    # "tp": 0.0,
                    "symbol": symbol,
                    "volume": volume,
                    "order": order,
                    "customComment": f"Closing {symbol} Trade"
                }
            }
        }

        # Execute trade close command
        response = client.execute(payload)

        if response['status']:
            print(f"Trade with order ID {order} closed successfully.")
        else:
            print(f"Failed to close trade with order ID {order}. Error: {response.get('errorCode')} - {response.get('errorDescr')}")