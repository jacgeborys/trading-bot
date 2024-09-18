from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def open_trade(client, symbol, volume, price, latest_close, offset, tp_value=0.0, sl_value=0.0, order_type='market'):
    """
    Open a trade with specified parameters, supporting both market and pending orders.

    :param client: Trading client.
    :param symbol: Trading symbol (e.g., 'EURUSD').
    :param volume: Amount of the asset to trade (positive for buy, negative for sell).
    :param price: Entry price for pending orders.
    :param latest_close: The latest close price to determine the order type.
    :param offset: Price offset for setting tp and sl values more accurately.
    :param tp_value: Take profit value.
    :param sl_value: Stop loss value.
    :param order_type: 'market' for market orders, 'pending' for pending orders.
    """
    global trade_opened
    trade_time = datetime.datetime.now()
    formatted_trade_time = trade_time.strftime('%Y-%m-%d %H:%M:%S')

    # Calculate offset for stop loss and take profit
    offset = int(10 * offset)
    tp_value = round(tp_value, 1)
    sl_value = round(sl_value, 1)

    # Determine the command value based on the type of order and volume sign
    if order_type == 'market':
        cmd_value = 0 if volume > 0 else 1
    elif order_type == 'pending':
        if volume > 0:  # This is a buy order
            cmd_value = 4 if price > latest_close else 2  # Buy Stop if price is above latest close else Buy Limit
        else:  # This is a sell order
            cmd_value = 5 if price < latest_close else 3  # Sell Stop if price is below latest close else Sell Limit
        expiration_time = trade_time + datetime.timedelta(minutes=3)  # Set expiration time to 5 minutes from now
        expiration = int(expiration_time.timestamp() * 1000)  # Convert to milliseconds

    volume = abs(volume)  # Volume should always be a positive number

    # Debugging statements to check the tp and sl values
    print(f"Debug: Trading operation being attempted at {formatted_trade_time}")
    print(f"Debug: TP: {tp_value}, SL: {sl_value}, Offset: {offset}, Volume: {volume}, Cmd: {cmd_value}, Order Type: {order_type}")

    # Trade transaction information
    trade_info = {
        "cmd": cmd_value,
        "customComment": "Trading based on MA crossover",
        "offset": offset,
        "price": price,  # Use price for both market and pending types if needed
        "sl": sl_value,
        "symbol": symbol,
        "tp": tp_value,
        "type": 0,  # Type for order execution, adjust if needed by API
        "volume": volume,
        "expiration": expiration if order_type == 'pending' else 0  # Set expiration only for pending orders
    }

    request = {
        "command": "tradeTransaction",
        "arguments": {
            "tradeTransInfo": trade_info
        }
    }

    response = client.execute(request)
    return {
        "trade_time": formatted_trade_time,
        "response": response
    }

def modify_trade(client, order_id, offset, sl_value, tp_value):
    """
    Modify an existing trade with specified parameters.

    :param client: Trading client.
    :param order_id: The ID of the trade to modify.
    :param offset: New trailing offset.
    :param sl_value: New stop loss value.
    :param tp_value: New take profit value.
    """
    trade_info = {
        "cmd": 3,  # MODIFY command
        "order": order_id,
        "offset": offset,
        "sl": sl_value,
        "tp": tp_value,
        "symbol": "US500",  # Adjust this if necessary
        "type": 3  # Modify type
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
                    "type": 2,  # Close order
                    "price": close_price,
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


def close_trade(client, position_type, volume_per_trade, min_profit=None, max_loss=None):
    print(
        f"Attempting to close trade: Type {position_type}, Volume {volume_per_trade}, Min Profit {min_profit}, Max Loss {max_loss}")
    trades_response = client.execute({"command": "getTrades", "arguments": {"openedOnly": True}})
    trades = trades_response.get("returnData", [])

    if not trades:
        print("No trades to close.")
        return "No trades available"

    close_responses = []

    for trade in trades:
        if trade["cmd"] == position_type:
            trade_volume = trade["volume"]
            symbol = trade["symbol"]
            order = trade["order"]
            trade_profit = trade.get("profit", 0)

            should_close = False
            if min_profit is not None and trade_profit >= min_profit:
                should_close = True
            elif max_loss is not None and trade_profit <= max_loss:
                should_close = True

            if should_close and trade_volume >= volume_per_trade:
                payload = {
                    "command": "tradeTransaction",
                    "arguments": {
                        "tradeTransInfo": {
                            "type": 2,  # Always 2 for closing
                            "order": order,
                            "price": 1.0,  # Placeholder value greater than 0
                            "symbol": symbol,
                            "volume": volume_per_trade
                        }
                    }
                }
                response = client.execute(payload)
                close_responses.append(response)
            else:
                print(f"Conditions not met to close trade: {trade}")

    if not close_responses:
        print("No trades were closed.")
        return "No matching trades were closed"

    return close_responses


def partial_close_trade(client, symbol, order_id, close_volume, cmd):
    if close_volume <= 0:
        print(f"Error: Cannot close trade with volume {close_volume}. Volume must be greater than 0.")
        return {"status": False, "errorCode": "INVALID_VOLUME", "errorDescr": "Close volume must be greater than 0"}

    trade_info = {
        "cmd": cmd,
        "customComment": "Partial close",
        "expiration": 0,
        "order": order_id,
        "price": 1,
        "sl": 0,
        "tp": 0,
        "symbol": symbol,
        "type": 2,
        "volume": close_volume
    }

    request = {
        "command": "tradeTransaction",
        "arguments": {
            "tradeTransInfo": trade_info
        }
    }

    # Print the payload
    import json
    print("Payload being sent to API:")
    print(json.dumps(request, indent=4))

    response = client.execute(request)

    if response['status']:
        print(f"Partially closed trade {order_id} with volume {close_volume}")
    else:
        print(f"Failed to partially close trade {order_id}. Error: {response.get('errorCode')} - {response.get('errorDescr')}")

    return response
