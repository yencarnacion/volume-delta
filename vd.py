#!/usr/bin/env python3
import os
import sys
import time
import threading
from datetime import datetime
import curses

from polygon import WebSocketClient
from polygon.websocket.models import EquityTrade, EquityQuote
# We no longer use termcolor since curses handles color

from dotenv import load_dotenv

# Load .env file if it exists, without overriding existing environment variables
load_dotenv()

# --- Configuration ---
API_KEY = os.getenv('POLYGON_API_KEY', 'YOUR_API_KEY_HERE')
if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} STOCK_TICKER")
    sys.exit(1)
TICKER = sys.argv[1].upper()

# --- Volume Delta Calculator Class ---
class VolumeDeltaCalculator:
    def __init__(self, ticker):
        self.ticker = ticker.upper()
        self.lock = threading.Lock()
        self.ask_volume = 0
        self.bid_volume = 0
        self.latest_quote = None  # Dict: {"bid": value, "ask": value}

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

# --- WebSocket Message Handler ---
def handle_message(msgs, delta_calculator):
    for msg in msgs:
        if isinstance(msg, EquityTrade):
            delta_calculator.update_trade(msg)
        elif isinstance(msg, EquityQuote):
            delta_calculator.update_quote(msg)

def run_websocket(api_key, ticker, delta_calculator):
    client = WebSocketClient(api_key=api_key)
    client.subscribe(f"T.{ticker}")
    client.subscribe(f"Q.{ticker}")
    client.run(lambda msgs: handle_message(msgs, delta_calculator))

# --- curses-based Main UI ---
def curses_main(stdscr):
    # Configure curses
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.clear()
    curses.start_color()
    curses.use_default_colors()
    # Define color pairs: pair 1 for positive (yellow), pair 2 for negative (red)
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)

    delta_calculator = VolumeDeltaCalculator(TICKER)
    ws_thread = threading.Thread(target=run_websocket, args=(API_KEY, TICKER, delta_calculator), daemon=True)
    ws_thread.start()

    field_width = 10  # Fixed field width for numeric columns

    # Initial alignment: wait until the next multiple of 5 seconds
    now = time.time()
    if now % 5 != 0:
        start_time = ((int(now) // 5) + 1) * 5
        time.sleep(start_time - now)
    else:
        start_time = now

    current_row = 0
    height, width = stdscr.getmaxyx()

    # Main loop: each iteration covers one 5-second window.
    while True:
        window_time_str = datetime.fromtimestamp(start_time).strftime("(%M:%S)")
        end_time = start_time + 5

        # Update the display on the current_row until the window ends.
        while time.time() < end_time:
            volume_delta, ask_vol, bid_vol = delta_calculator.get_volume_delta()
            raw_delta = f"{volume_delta:>{field_width},}"
            raw_ask = f"{ask_vol:>{field_width},}"
            raw_bid = f"{bid_vol:>{field_width},}"

            # Choose color based on volume_delta
            if volume_delta > 0:
                color = curses.color_pair(1)
            elif volume_delta < 0:
                color = curses.color_pair(2)
            else:
                color = curses.A_NORMAL

            output_str = f"vd {window_time_str}:{raw_delta}  |  Buy:{raw_ask}  |  Sell:{raw_bid}"
            # Clear the line and write the updated string at current_row
            stdscr.move(current_row, 0)
            stdscr.clrtoeol()
            stdscr.addstr(current_row, 0, output_str.ljust(width), color)
            stdscr.refresh()
            time.sleep(0.2)

        # End of window: print the final output on the current_row
        volume_delta, ask_vol, bid_vol = delta_calculator.get_volume_delta()
        raw_delta = f"{volume_delta:>{field_width},}"
        raw_ask = f"{ask_vol:>{field_width},}"
        raw_bid = f"{bid_vol:>{field_width},}"
        if volume_delta > 0:
            color = curses.color_pair(1)
        elif volume_delta < 0:
            color = curses.color_pair(2)
        else:
            color = curses.A_NORMAL
        final_str = f"vd {window_time_str}:{raw_delta}  |  Buy:{raw_ask}  |  Sell:{raw_bid}"
        stdscr.move(current_row, 0)
        stdscr.clrtoeol()
        stdscr.addstr(current_row, 0, final_str.ljust(width), color)
        stdscr.refresh()
        delta_calculator.reset()

        # Advance to the next line for the next window's final output.
        current_row += 1
        if current_row >= height:
            stdscr.scroll(1)
            current_row = height - 1

        # Set the next window's start_time to the previous window's end_time.
        start_time = end_time
        now = time.time()
        if now < start_time:
            time.sleep(start_time - now)

if __name__ == "__main__":
    try:
        curses.wrapper(curses_main)
    except KeyboardInterrupt:
        # When curses is active, it's best to end curses cleanly.
        curses.endwin()
        print("\nProgram terminated by user.")
