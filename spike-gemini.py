#!/usr/bin/env python3
import os
import sys
import time
import threading
import math
import curses
from datetime import datetime

from polygon import WebSocketClient
from polygon.websocket.models import EquityTrade, EquityQuote
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
        self.latest_quote = None  # Dictionary holding {"bid": value, "ask": value}
        self.last_traded_price = None  # Store the most recent trade price

    def update_quote(self, quote: EquityQuote):
        if quote.symbol.upper() != self.ticker:
            return
        with self.lock:
            self.latest_quote = {"bid": quote.bid_price, "ask": quote.ask_price}

    def update_trade(self, trade: EquityTrade):
        if trade.symbol.upper() != self.ticker:
            return

        price = trade.price
        volume = trade.size
        EPSILON = 1e-3  # Tolerance for floating point comparison

        with self.lock:
            # Always update the last traded price even if no quote is available.
            self.last_traded_price = price
            # If we haven't received a quote yet, skip volume delta calculation.
            if self.latest_quote is None:
                return
            bid = self.latest_quote["bid"]
            ask = self.latest_quote["ask"]

        # --- Volume assignment logic (combined from both versions) ---
        # Use epsilon checks for exact matches first.
        if abs(price - ask) < EPSILON:
            with self.lock:
                self.ask_volume += volume
        elif abs(price - bid) < EPSILON:
            with self.lock:
                self.bid_volume += volume
        # If the price is clearly above or below the quoted range.
        elif price > ask + EPSILON:
            with self.lock:
                self.ask_volume += volume
        elif price < bid - EPSILON:
            with self.lock:
                self.bid_volume += volume
        else:
            # If the price lies between the bid and ask, assign based on which is closer.
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

    def get_last_traded_price(self):
        with self.lock:
            return self.last_traded_price

    def reset(self):
        with self.lock:
            self.ask_volume = 0
            self.bid_volume = 0
            # Do not reset last_traded_price; we need it for spike reference

# --- WebSocket Message Handler ---
def handle_message(msgs, delta_calculator):
    for msg in msgs:
        if isinstance(msg, EquityTrade):
            delta_calculator.update_trade(msg)
        elif isinstance(msg, EquityQuote):
            delta_calculator.update_quote(msg)

# --- WebSocket Connection with Retry ---
def run_websocket(api_key, ticker, delta_calculator):
    max_retries = 3
    delay = 10  # seconds to wait before retrying
    remaining_retries = max_retries

    while True:
        try:
            client = WebSocketClient(api_key=api_key)
            client.subscribe(f"T.{ticker}")
            client.subscribe(f"Q.{ticker}")
            print(f"WebSocket connected, subscribed to T.{ticker} and Q.{ticker}")
            client.run(lambda msgs: handle_message(msgs, delta_calculator))
            print("WebSocket client ended or disconnected gracefully.")
            remaining_retries = max_retries  # Reset the retry counter on graceful exit

        except KeyboardInterrupt:
            print("KeyboardInterrupt detected in WebSocket thread. Shutting down.")
            break

        except ConnectionResetError:
            print("WebSocket connection reset by peer. Retrying in {} seconds...".format(delay))
            time.sleep(delay)

        except Exception as e:
            remaining_retries -= 1
            if remaining_retries > 0:
                print(f"WebSocket error: {e}. Retrying in {delay} seconds... ({remaining_retries} retries left)")
                time.sleep(delay)
            else:
                print(f"WebSocket error: {e}. No more retries left. Shutting down.")
                break

        finally:
            if 'client' in locals() and hasattr(client, 'close') and client.ws and client.ws.connected:
                try:
                    client.close()
                    print("WebSocket client closed.")
                except Exception as close_e:
                    print(f"Error closing WebSocket client: {close_e}")

# --- curses-based Main UI ---
def curses_main(stdscr):
    # Configure curses settings
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.clear()
    curses.start_color()
    curses.use_default_colors()
    # Color pairs: Green for positive spike, Yellow for negative
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)

    delta_calculator = VolumeDeltaCalculator(TICKER)
    ws_thread = threading.Thread(target=run_websocket, args=(API_KEY, TICKER, delta_calculator), daemon=True)
    ws_thread.start()

    spike_field_width = 10  # Field width for spike display with sign and decimals
    volume_field_width = 10  # Field widths for volume numbers
    max_lines = 4  # Maximum number of historical lines to display
    display_lines = []  # List to store (line_string, color_attribute) tuples

    # --- Get Initial Price ---
    print("Waiting for initial market data...")
    initial_price = None
    for _ in range(10):  # Wait up to ~2 seconds
        initial_price = delta_calculator.get_last_traded_price()
        if initial_price is not None:
            break
        time.sleep(0.2)
    if initial_price is None:
        print(f"Warning: Could not get initial price for {TICKER}. Spike calculations may be delayed.")
    previous_window_close = initial_price

    # Align the start time to the next 5-second boundary
    now = time.time()
    start_time = math.ceil(now / 5.0) * 5.0
    if start_time - now > 0:
        time.sleep(start_time - now)

    # --- Main Loop (each iteration is a 5-second window) ---
    while True:
        window_time_str = datetime.fromtimestamp(start_time).strftime("%H:%M:%S")
        end_time = start_time + 5.0

        # Capture the price at the start of the window for spike reference.
        current_window_start_price = delta_calculator.get_last_traded_price()
        if current_window_start_price is not None:
            previous_window_close = current_window_start_price

        # Reset volume counters for the new window.
        delta_calculator.reset()

        current_update_str = ""
        current_color_attr = curses.A_NORMAL

        # --- Live Update Loop Within the 5-Second Window ---
        while time.time() < end_time:
            height, width = stdscr.getmaxyx()

            volume_delta, ask_vol, bid_vol = delta_calculator.get_volume_delta()
            current_price = delta_calculator.get_last_traded_price()

            spike_value = 0.0
            if previous_window_close and current_price is not None and previous_window_close != 0:
                try:
                    price_delta = current_price - previous_window_close
                    price_delta_percent = price_delta / previous_window_close
                    spike_value = price_delta_percent * abs(volume_delta)
                    if math.isnan(spike_value):
                        spike_value = 0.0
                except ZeroDivisionError:
                    spike_value = 0.0
                except Exception:
                    spike_value = 0.0

            # Determine color based on the sign of the spike.
            if spike_value > 1e-9:
                current_color_attr = curses.color_pair(1)  # Green for positive spike
            elif spike_value < -1e-9:
                current_color_attr = curses.color_pair(2)  # Yellow for negative spike
            else:
                current_color_attr = curses.A_NORMAL

            # Format the columns with fixed widths.
            raw_spike = f"{spike_value:>{spike_field_width},.0f}"
            raw_ask   = f"{ask_vol:>{volume_field_width},}"
            raw_bid   = f"{bid_vol:>{volume_field_width},}"
            raw_delta = f"{volume_delta:>{volume_field_width},}"

            current_update_str = f"Spike({window_time_str}):{raw_spike} | Buy:{raw_ask} | Sell:{raw_bid} | VD:{raw_delta}"

            stdscr.erase()
            # Display previous finalized lines.
            start_row = max(0, len(display_lines) - max_lines)
            for i, (line, col) in enumerate(display_lines[start_row:]):
                try:
                    stdscr.addstr(i, 0, line.ljust(width)[:width-1], col)
                except curses.error:
                    pass
            # Display current live update.
            try:
                stdscr.addstr(len(display_lines), 0, current_update_str.ljust(width)[:width-1], current_color_attr)
            except curses.error:
                pass
            stdscr.refresh()

            # Check for user input (e.g., press 'q' to quit)
            if stdscr.getch() == ord('q'):
                return

            time.sleep(0.2)

        # --- End-of-Window Final Calculation ---
        volume_delta, ask_vol, bid_vol = delta_calculator.get_volume_delta()
        current_price = delta_calculator.get_last_traded_price()

        spike_value = 0.0
        if previous_window_close and current_price is not None and previous_window_close != 0:
            try:
                price_delta = current_price - previous_window_close
                price_delta_percent = price_delta / previous_window_close
                spike_value = price_delta_percent * abs(volume_delta)
                if math.isnan(spike_value):
                    spike_value = 0.0
            except ZeroDivisionError:
                spike_value = 0.0
            except Exception:
                spike_value = 0.0

        final_color_attr = curses.A_NORMAL
        if spike_value > 1e-9:
            final_color_attr = curses.color_pair(1)
        elif spike_value < -1e-9:
            final_color_attr = curses.color_pair(2)

        raw_spike = f"{spike_value:>{spike_field_width},.0f}"
        raw_ask   = f"{ask_vol:>{volume_field_width},}"
        raw_bid   = f"{bid_vol:>{volume_field_width},}"
        raw_delta = f"{volume_delta:>{volume_field_width},}"
        final_str = f"Spike({window_time_str}):{raw_spike} | Buy:{raw_ask} | Sell:{raw_bid} | VD:{raw_delta}"

        display_lines.append((final_str, final_color_attr))
        if len(display_lines) > max_lines + 1:
            display_lines.pop(0)

        # Prepare start time for the next window.
        start_time = end_time
        now = time.time()
        sleep_time = start_time - now
        if sleep_time > 0:
            time.sleep(sleep_time)

if __name__ == "__main__":
    if API_KEY == 'YOUR_API_KEY_HERE' or not API_KEY:
        print("Error: POLYGON_API_KEY environment variable not set.")
        sys.exit(1)

    try:
        curses.wrapper(curses_main)
    except KeyboardInterrupt:
        curses.endwin()
        print("\nProgram terminated by user (KeyboardInterrupt).")
    except Exception as e:
        curses.endwin()
        print(f"\nAn unexpected error occurred: {e}")
    finally:
        try:
            curses.nocbreak()
            curses.echo()
            curses.endwin()
        except:
            pass
