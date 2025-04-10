#!/usr/bin/env python3
import os
import sys
import time
import threading
from datetime import datetime

from polygon import WebSocketClient
from polygon.websocket.models import EquityTrade, EquityQuote
from termcolor import colored

from dotenv import load_dotenv

# Load .env file if it exists, without overriding existing environment variables
load_dotenv()

# --- Configuration ---
# Replace with your Polygon API key or set the POLYGON_API_KEY environment variable
API_KEY = os.getenv('POLYGON_API_KEY', 'YOUR_API_KEY_HERE')

# Get the ticker from the command-line arguments.
if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} STOCK_TICKER")
    sys.exit(1)
TICKER = sys.argv[1].upper()  # Convert to uppercase to meet API requirements.

# --- Volume Delta Calculator Class ---
class VolumeDeltaCalculator:
    def __init__(self, ticker):
        self.ticker = ticker.upper()
        self.lock = threading.Lock()
        self.ask_volume = 0
        self.bid_volume = 0
        self.latest_quote = None  # Stored as dict: {"bid": value, "ask": value}

    def update_quote(self, quote):
        if quote.symbol.upper() != self.ticker:
            return
        with self.lock:
            self.latest_quote = {"bid": quote.bid_price, "ask": quote.ask_price}

    def update_trade(self, trade):
        if trade.symbol.upper() != self.ticker:
            return
        with self.lock:
            if self.latest_quote is None:
                return
            bid = self.latest_quote["bid"]
            ask = self.latest_quote["ask"]

        price = trade.price
        volume = trade.size
        EPSILON = 1e-3

        if abs(price - ask) < EPSILON:
            with self.lock:
                self.ask_volume += volume
        elif abs(price - bid) < EPSILON:
            with self.lock:
                self.bid_volume += volume
        elif price > (ask + EPSILON):
            with self.lock:
                self.ask_volume += volume
        elif price < (bid - EPSILON):
            with self.lock:
                self.bid_volume += volume
        else:
            # In-between trade: decide based on proximity.
            if abs(price - ask) < abs(price - bid):
                with self.lock:
                    self.ask_volume += volume
            else:
                with self.lock:
                    self.bid_volume += volume

    def get_volume_delta(self):
        with self.lock:
            delta = self.ask_volume - self.bid_volume
            return delta, self.ask_volume, self.bid_volume

    def reset(self):
        with self.lock:
            self.ask_volume = 0
            self.bid_volume = 0

# --- Polygon WebSocket Message Handler ---
def handle_message(msgs, delta_calculator):
    for msg in msgs:
        if isinstance(msg, EquityTrade):
            delta_calculator.update_trade(msg)
        elif isinstance(msg, EquityQuote):
            delta_calculator.update_quote(msg)

# Start the websocket client.
def run_websocket(api_key, ticker, delta_calculator):
    client = WebSocketClient(api_key=api_key)
    client.subscribe(f"T.{ticker}")
    client.subscribe(f"Q.{ticker}")
    client.run(lambda msgs: handle_message(msgs, delta_calculator))

# --- Main Loop ---
#
# Instead of using a helper to wait for a boundary, we now compute the next
# window start explicitly. This ensures that every window (multiples of 5 seconds)
# is always used.
def main():
    delta_calculator = VolumeDeltaCalculator(TICKER)
    ws_thread = threading.Thread(target=run_websocket, args=(API_KEY, TICKER, delta_calculator), daemon=True)
    ws_thread.start()

    field_width = 10  # fixed field width for output alignment

    # Initial alignment: compute the next multiple of 5 seconds.
    now = time.time()
    if now % 5 != 0:
        start_time = ((int(now) // 5) + 1) * 5
        time.sleep(start_time - now)
    else:
        start_time = now

    # Main loop: each iteration covers one 5-second window.
    while True:
        window_time_str = datetime.fromtimestamp(start_time).strftime("(%M:%S)")
        end_time = start_time + 5

        # Update the display until the window ends.
        while time.time() < end_time:
            volume_delta, ask_vol, bid_vol = delta_calculator.get_volume_delta()
            raw_delta = f"{volume_delta:>{field_width},}"
            raw_ask = f"{ask_vol:>{field_width},}"
            raw_bid = f"{bid_vol:>{field_width},}"

            if volume_delta > 0:
                colored_delta = colored(raw_delta, 'yellow')
            elif volume_delta < 0:
                colored_delta = colored(raw_delta, 'red')
            else:
                colored_delta = raw_delta

            output_str = f"\rvd {window_time_str}:{colored_delta}  |  Buy:{raw_ask}  |  Sell:{raw_bid}"
            print(output_str, end='', flush=True)
            time.sleep(0.2)  # refresh rate

        # End of window: print final output and reset counters.
        volume_delta, ask_vol, bid_vol = delta_calculator.get_volume_delta()
        raw_delta = f"{volume_delta:>{field_width},}"
        raw_ask = f"{ask_vol:>{field_width},}"
        raw_bid = f"{bid_vol:>{field_width},}"

        if volume_delta > 0:
            colored_delta = colored(raw_delta, 'yellow')
        elif volume_delta < 0:
            colored_delta = colored(raw_delta, 'red')
        else:
            colored_delta = raw_delta

        print(f"\rvd {window_time_str}:{colored_delta}  |  Buy:{raw_ask}  |  Sell:{raw_bid}")
        delta_calculator.reset()

        # Set the start time for the next window to exactly end_time.
        start_time = end_time
        # If processing was very fast and we're ahead of time, wait until the next boundary.
        now = time.time()
        if now < start_time:
            time.sleep(start_time - now)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
