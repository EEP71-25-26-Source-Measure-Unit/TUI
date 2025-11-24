#!/usr/bin/env python3

import sys
import threading
import time
import argparse
import shlex
import atexit
import datetime
import random
from src.smulib.logging import SMULogger
from serial.tools import list_ports
from smulib import SMU
from prompt_toolkit.application import Application
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window, ScrollOffsets, VSplit
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import WindowAlign
from prompt_toolkit.widgets import HorizontalLine, TextArea, VerticalLine
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.shortcuts import radiolist_dialog

# class SMU(SMUBase):
#     def __init__(self, port: str, baudrate: int = 115200, timeout: float | None = 1.0):
#         self.__port = port
#         self.__baudrate = baudrate
#         self.__timeout = timeout
#         self._serial = None
#         self._connect_attempts: int = 0
#         self._last_connect_time: float = 0.0
#         self.max_backoff: float = 3.0
#         self.initial_backoff: float = 0.1

#         try:
#             self.connect()
#         except Exception:
#             logger.debug_logger.exception("Initial connect failed for %s", port)
#             self._serial = None

#     @property
#     def port(self) -> str:
#         return self.__port

#     def connect(self) -> None:
#         try:
#             # self._serial = serial.Serial(port=self.__port, baudrate=self.__baudrate, timeout=self.__timeout)
#             self._connect_attempts = 0
#             self._last_connect_time = time.monotonic()
#             logger.debug_logger.debug("Connected to SMU on %s", self.__port)
#         except Exception as e:
#             logger.debug_logger.exception("Failed to open serial port %s", self.__port)
#             self._serial = None
#             raise IOError(f"Could not open port {self.__port}: {e}") from e

#     def disconnect(self) -> None:
#         if self._serial is not None:
#             try:
#                 self._serial.close()
#             except Exception:
#                 logger.debug_logger.exception("Error while closing serial port")
#             finally:
#                 self._serial = None
#                 logger.debug_logger.debug("Disconnected from %s", self.__port)

#     def reconnect(self) -> None:
#         backoff = self.initial_backoff
#         attempts = 0
#         while True:
#             try:
#                 self.connect()
#                 return
#             except IOError:
#                 attempts += 1
#                 if backoff > self.max_backoff:
#                     raise IOError(f"Failed to reconnect after {attempts} attempts") from None
#                 logger.debug_logger.warning("Reconnect attempt %d failed, backing off %.2fs", attempts, backoff)
#                 time.sleep(backoff)
#                 backoff *= 2

#     def __write(self, command: str) -> None:
#         if self._serial is None:
#             raise IOError("Serial not connected")
#         self._serial.write((command + "\n").encode())

#     def __read(self, command: str) -> str:
#         if self._serial is None:
#             raise IOError("Serial not connected")
#         self.__write(command)
#         raw = self._serial.readline()
#         if isinstance(raw, bytes):
#             raw = raw.decode(errors='ignore')
#         return str(raw).strip()

#     def set_voltage(self, v: float) -> None:
#         self.__write(f":SOUR:VOLT {float(v)}")

#     def set_current(self, i: float) -> None:
#         self.__write(f":SOUR:CURR {float(i)}")

#     def voltage_limit(self) -> float:
#         return float(self.__read(":SOUR:VOLT:LIM?"))

#     def current_limit(self) -> float:
#         return float(self.__read(":SOUR:CURR:LIM?"))

#     def measure_voltage(self) -> float:
#         return float(self.__read(":MEAS:VOLT?"))

#     def measure_current(self) -> float:
#         return float(self.__read(":MEAS:CURR?"))
    
#     @staticmethod
#     def discover_ports() -> dict[str, str]:
#         """
#         :return: A list of port-devices (e.g., ['COM3', '/dev/ttyUSB0'])
#         """
#         ports = list_ports.comports()
#         return {port.device: port.description for port in ports}

__version__ = "0.2.0"

# --- Global Variables & Synchronization ---
smu_lock = threading.Lock()
smu_instance: SMU | None = None
logger: SMULogger
running = True

# Share the latest measurements
latest_voltage = 0.0
latest_current = 0.0
latest_output_state = "OFF"
smu_error: str | None = None
command_output_log: list[str] = [] # Buffer for command output

# The expected (sub)string in the *IDN? response to verify the SMU
EXPECTED_IDN_SUBSTRING = "SMU"

# --- Help Text (slightly adjusted) ---
HELP_TEXT = """Commands:

on, enable              Enable the output
off, disable            Disable the output
vmode <V> <I-lim>       Set voltage mode (e.g.: vmode 5.0 0.1)
cmode <I> <V-lim>       Set current mode (e.g.: cmode 0.05 15.0)
logdata <state>         Enable or disable data logging (e.g.: state on | off)

mode?                   Get mode (VOLT/CURR) and set values
  
help, h                 Show this help message
clear, cls              Clear the command log
exit, quit              Exit the CLI
"""

def enable_smu_data_logging():
    if not logger.smu:
        log_output("No SMU instance in logger object." \
        "Set it using logger.set_logging_parameters(smu=SMU)")
        logger.debug_logger.debug("No SMU instance in logger object." \
        "Set it using logger.set_logging_parameters(smu=SMU)")
        return False
    logger.start_data_logging()
    return True

def disable_smu_data_logging() -> bool:
    if not logger.smu:
        log_output("No SMU instance in logger object." \
        "Set it using logger.set_logging_parameters(smu=SMU)")
        logger.debug_logger.debug("No SMU instance in logger object." \
        "Set it using logger.set_logging_parameters(smu=SMU)")
        return False
    logger.stop_data_logging()
    return True
    
# --- Log Function ---
def log_output(message: str):
    message = str(message)
    cmd_timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    for line in message.splitlines():
        command_output_log.append(f"[{cmd_timestamp}] {line}")
    while len(command_output_log) > 200:
        command_output_log.pop(0)

# --- Updater Thread ---
def status_updater(app: Application, frequency: float):
    """
    A thread function that periodically requests the SMU status and
    invalidates the application UI (forces a redraw).
    """
    global latest_voltage, latest_current, latest_output_state, smu_error, running, smu_instance
    
    while running:
        if smu_instance is None:
            time.sleep(0.5)
            continue

        try:
            # Acquire the lock to communicate safely with the SMU
            with smu_lock:
                # logger.debug_logger.debug(latest_current)
                latest_voltage = smu_instance.measure_voltage()
                # logger.debug_logger.debug(latest_current)
                latest_current = smu_instance.measure_current()
                # We are now trying the :OUTP? command
                # latest_output_state = smu_instance.get_output_state() 
                smu_error = None

        except (ValueError, TypeError) as e:
            smu_error = f"DATA ERROR: Could not parse response. {e}"
        except Exception as e:
            smu_error = f"GENERAL ERROR in status updater: {e}"

        if smu_error: logger.debug_logger.error(smu_error)
        
        if not running:
            break

        # Invalidate the application to force the UI to update itself
        app.invalidate()
        
        time.sleep(frequency)

def process_command(cmd_str: str):
    """Process a single command line from the user."""
    global running, latest_output_state, smu_instance
    
    if smu_instance is None:
        log_output("Error: SMU is not initialized.")
        return

    try:
        args = shlex.split(cmd_str)
    except ValueError as e:
        log_output(f"Error in command syntax: {e}")
        return
    
    log_output(f"> {cmd_str}") # Echo the command to the log
    
    if not args:
        log_output(f"Unknown command: ''. Type 'help' for options.")
        return # Empty input
    
    command = args[0].lower()

    try:
        with smu_lock:
            if command in ("exit", "quit", "q"):
                running = False
                return
            
            elif command in ("help", "h", "?"):
                log_output(HELP_TEXT)
            
            elif command in ("clear", "cls"):
                command_output_log.clear()

            elif command in ("on", "enable"):
                # smu_instance.enable()
                latest_output_state = "ON" # Update the status immediately
                log_output("Output ENABLED (does nothing rn)")
            
            elif command in ("off", "disable"):
                # smu_instance.disable()
                latest_output_state = "OFF" # Update the status immediately
                log_output("Output DISABLED (does nothing rn)")

            # add limits
            elif command == "vmode":
                if len(args) != 3:
                    log_output("Usage: vmode <voltage> <current_limit>")
                    return
                v = float(args[1])
                i_lim = float(args[2])
                smu_instance.voltage_mode(v, i_lim)
                log_output(f"Mode -> Voltage: {v} V, Limit: {i_lim} A")
        
            elif command == "cmode":
                if len(args) != 3:
                    log_output("Usage: cmode <current> <voltage_limit>")
                    return
                i = float(args[1])
                v_lim = float(args[2])
                smu_instance.current_mode(i, v_lim)
                log_output(f"Mode -> Current: {i} A, Limit: {v_lim} V")

            elif command == "logdata":
                if len(args) != 2:
                    log_output("Usage: logdata <state> | state can be 'on' or 'off' ")
                    return
                new_state = str(args[1])
                if new_state == "on":
                    if not enable_smu_data_logging(): return
                elif new_state == "off":
                    if not disable_smu_data_logging(): return
                else:
                    log_output(f"Invalid state, state can be 'on' or 'off'")
                    return
                log_output(f"Logdata -> {new_state}")

            elif command == "mode?":
                # log_output(f"Current mode:  {smu_instance.mode()}")
                # log_output(f"Set voltage:   {smu_instance.set_voltage()} V")
                # log_output(f"Set current:   {smu_instance.set_current()} A")
                log_output(f"Voltage limit: {smu_instance.voltage_limit()} V")
                log_output(f"Current limit: {smu_instance.current_limit()} A")

            else:
                log_output(f"Unknown command: '{command}'. Type 'help' for options.")

    except Exception as e:
        print(f"SERIAL ERROR: {e}")
        log_output(f"SERIAL ERROR: {e}")
    except (ValueError, TypeError) as e:
        print("Argument Error: {e}")
        log_output(f"Argument Error: {e}")
    except Exception as e:
        print(f"GENERAL ERROR: {e}")
        log_output(f"GENERAL ERROR: {e}")

# --- Port Selection ---
def select_smu_port() -> SMU | None:
    """
    Shows an interactive menu to select and verify a serial port.
    This runs *before* the TUI starts.
    """
    while True:
        print("\nAvailable serial ports:")
        try:
            ports = SMU.discover_ports()
        except Exception as e:
            print(f"Error while scanning for ports: {e}")
            time.sleep(2)
            continue

        if not ports:
            print("  No ports found.")
            print("\nConnect the SMU and wait...")
            
            try:
                time.sleep(1) # Wait 1 second for the next scan
            except KeyboardInterrupt:
                return None
            continue # Go back to the start of the while-loop

        for i, port in enumerate(ports):
            print(f"  [{i}] {port}")
        
        print("\nOptions:")
        print("  [r] Rescan")
        print("  [q] Quit")
        
        choice = input("Make a choice (e.g., 0, 1, 2, r, q): ").strip().lower()

        if choice == 'q':
            return None
        if choice == 'r':
            continue

        try:
            index = int(choice)
            if not (0 <= index < len(ports)):
                raise IndexError
            
            selected_port = ports.get(f"{index}")
            if selected_port is None:
                return
            print(f"\nConnecting and verifying {selected_port}...")
            
            try:
                # Trying to connect
                temp_smu = SMU(port=selected_port)
                
                # Trying to identify
                idn_response = temp_smu.identify()
                
                # Verify
                if EXPECTED_IDN_SUBSTRING.upper() in idn_response.upper():
                    print(f"Success! Verified device: {idn_response}")
                    return temp_smu # This is the SMU
                else:
                    print(f"Error: Device on {selected_port} responded ({idn_response}),")
                    print(f"      but the response does not contain '{EXPECTED_IDN_SUBSTRING}'.")
                    temp_smu.close()
                    
            except Exception as e:
                print(f"Error: Could not communicate with {selected_port}.")
                print(f"      Details: {e}")

        except (ValueError, IndexError):
            print("Invalid choice, please try again.")
        
        time.sleep(1) # Short pause for the user to read

# --- TUI Main Application ---
def run_tui_app():
    global latest_voltage, latest_current, smu_instance, running

    # Log welcome message
    if not smu_instance:
        log_output("FATAL ERROR: SMU not initialized.")
        running = False
        return
    
    # --- Input Field (bottom) ---
    def accept_command(buffer: Buffer) -> bool:
        """Callback for when Enter is pressed."""
        try:
            process_command(buffer.document.text)
        except Exception as e:
            log_output(f"Unexpected error while processing command: {e}")
        
        if not running:
            app.exit() # Stop the application
        return False
    
        # --- Command Output Window (middle) ---
    def get_output_text() -> FormattedText:
        """Show the last lines of the log."""
        # Show only the last 50 lines to keep the window fast
        display_lines = command_output_log[-50:]
        return FormattedText([('', "\n".join(display_lines))])
    
    info_bar = Window(
        content=FormattedTextControl(FormattedText([
            ("", f"SMU CLI "),
            ("bg:ansipurple #ffffff", f"v{__version__}"),
            ("", f" - Connected to {smu_instance.port}\n"),
            ("", "Type 'help' for commands, 'exit' or Ctrl+C to quit.")
        ])),
        height=2
    )

    output_window = Window(
        content=FormattedTextControl(get_output_text),
        wrap_lines=True,
        scroll_offsets= ScrollOffsets(bottom=1), # Keep scrolling down,
    )

    def get_voltage_text() -> FormattedText:
        # Optional: acquire lock when reading shared variables to avoid races
        with smu_lock:
            v = latest_voltage
        # logger.debug_logger.debug("get voltage text")
        return FormattedText([
            ('bg:#ansiwhite #000000', f' Voltage: {v:8.3f} V'),
        ])

    def get_current_text() -> FormattedText:
        # logger.debug_logger.debug("get current text")
        with smu_lock:
            i = latest_current
        return FormattedText([
            ('bg:#ansiwhite #000000', f' Current: {i:8.4f} A'),
        ])

    voltage_output = Window(
        content=FormattedTextControl(get_voltage_text),
        height=1,
        style='bg:#ansiwhite #000000',
    )

    current_output = Window(
        content=FormattedTextControl(get_current_text),
        height=1,
        style='bg:#ansiwhite #000000',
        align=WindowAlign("LEFT")
    )

    vertical_bar = Window(
        content=FormattedTextControl(FormattedText([
            ('bg:#ansiwhite #000000', '|'),
        ])),
        height=1,
        width=1,
        style = 'bg:#ansiwhite #000000',
        align= WindowAlign("CENTER")
    )

    readout_values_container = VSplit(([
        voltage_output,
        vertical_bar,
        current_output
    ]))

    input_field = TextArea(
        height=1,
        prompt="> ",
        multiline=False,
        wrap_lines=False,
        accept_handler=accept_command,
    )

    root_container = HSplit([
        info_bar,
        HorizontalLine(),
        output_window,
        HorizontalLine(),
        readout_values_container,
        HorizontalLine(),
        # VerticalLine(),
        input_field,
    ])

    kb = KeyBindings()
    @kb.add("c-c")
    @kb.add("c-q")
    def _(event):
        """Stop the application with Ctrl+C or Ctrl+Q."""
        global running
        running = False
        event.app.exit()

    app = Application(
        layout=Layout(root_container, focused_element=input_field),
        key_bindings=kb,
        full_screen=True,
        mouse_support=True        
    )

    updater = threading.Thread(target=status_updater, args=(app, 0.1), daemon=True)
    updater.start()

    app.run()

def cleanup():
    """Called upon exit to close the connection."""
    global smu_instance, running
    running = False

    print("\nExiting...") 

    if smu_instance:
        print("Disabling output and closing serial connection...")
        try:
            # We don't need a lock, as the updater thread is stopping
            smu_instance.disconnect()
        except Exception as e:
            print(f"Error during cleanup: {e}")
        print("Connection closed. Goodbye!")
    else:
        print("No active connection to close. Goodbye!")

def main():
    global smu_instance, logger

    logger = SMULogger(smu=None, data_request_interval=0.5, log_voltage=True, log_current=True, batch_size=5, batch_timeout=0.1)
    
    parser = argparse.ArgumentParser(
        description="Interactive CLI for the Source Measure Unit (SMU).",
        epilog="Example: python smu_cli.py --port /dev/ttyUSB0 (or start without --port for a selection menu)"
    )
    parser.add_argument(
        "-p", "--port",
        required=False,
        default=None,
        help="Optional: The serial port of the SMU (skips the selection menu)"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"smu v{__version__} (requires 'prompt_toolkit')"
    )
    args = parser.parse_args()

    if args.port:
        try:
            print(f"Connecting to specified port: {args.port}...")
            smu_instance = SMU(port=args.port)
            # Verification check
            # try:
            #     idn = smu_instance.identify()
            #     if EXPECTED_IDN_SUBSTRING.upper() in idn.upper():
            #         print(f"Connected and verified: {idn}")
            #     else:
            #         print(f"Warning: Device on {args.port} ({idn}) does not seem to be an SMU.")
            # except Exception as e:
            #     print(f"Warning: Could not verify device (*IDN? failed). Error: {e}")

        except Exception as e:
            print(f"Error connecting to SMU: {e}")
            sys.exit(1)
    else:
        pass
        # No port specified, starting interactive menu
        # smu_instance = select_smu_port()

        ports = SMU.discover_ports()

        if not ports.items(): print("No devices connected, connect a SMU to the computer")
        while not ports.items():
            time.sleep(0.1)
            ports = SMU.discover_ports()

        time.sleep(1)
        ports = SMU.discover_ports()
            
        port = radiolist_dialog(
            title="SMU COM PORT SELECT",
            text="Which COM port is the SMU?",
            values=list(
                ports.items()
            )
        ).run()

        if port is None:
            print("Exited by user.")
            sys.exit(0)

        smu_instance = SMU(port=port)

        # smu_instance.connect()

        
        if smu_instance is None:
            print("Exited by user.")
            sys.exit(0)

    logger.set_logging_parameters(smu=smu_instance)

    try:
        # Register a cleanup function
        atexit.register(cleanup)
        # Start the TUI (this blocks until it closes)
        run_tui_app()
        
    except Exception as e:
        print(f"An unexpected error has occurred: {e}")
        # cleanup() is called via atexit
        sys.exit(1)

if __name__ == "__main__":
    main()