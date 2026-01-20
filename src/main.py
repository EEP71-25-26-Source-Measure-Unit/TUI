import sys
import argparse
import atexit
import time
import threading # <--- Ensure this is imported

# Add these prompt_toolkit imports:
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.widgets import Dialog, Label
from prompt_toolkit.styles import Style

from smulib import SMU
from smulib.logging import SMULogger
from tui_app.core.state import AppState
from tui_app.ui.selector import DynamicPortSelector
from tui_app.ui.main_window import run_main_tui, EXIT_CRITICAL_DISCONNECT

def show_disconnect_alert(port_name: str):
    """
    Displays a blocking pop-up for 4 seconds alerting the user of the disconnect.
    """
    dialog = Dialog(
        title="CRITICAL DISCONNECT",
        body=Label(
            text=f"\nSMU on port {port_name} unexpectedly disconnected!\n\n"
                 f"Going to reconnect screen in 4 seconds...",
            style="bold"
        ),
        width=60,
        buttons=[] # No buttons, it auto-closes
    )

    # Style it RED to indicate an error
    style = Style.from_dict({
        'dialog': 'bg:#880000 #ffffff',        # Dark red background, white text
        'dialog.body': 'bg:#880000 #ffffff',
        'frame.label': '#ffffff bold',
        'shadow': 'bg:#000000',
    })

    app = Application(
        layout=Layout(dialog),
        full_screen=True,
        style=style,
        mouse_support=False
    )

    def close_timer():
        time.sleep(4)
        app.exit()

    # Run the timer in a background thread so the UI renders
    t = threading.Thread(target=close_timer, daemon=True)
    t.start()
    
    app.run()

def main():
    # 1. Setup State
    state = AppState()
    
    # 2. Setup Logger
    logger = SMULogger(smu=None)
    state.logger = logger

    def cleanup():
        print("Shutting down...")
        if state.smu: state.smu.disconnect()
        logger.shutdown()

    atexit.register(cleanup)

    # 3. Parse Args
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", help="Pre-select port")
    args = parser.parse_args()
    pre_port = args.port

    # 4. Main Application Loop
    while True:
        # --- Connection Phase ---
        port = pre_port
        if not port:
            title = "SMU SELECT" if state.connection_status == "Disconnected" else "RECONNECT SMU"
            port = DynamicPortSelector(title=title).run()
            if not port:
                sys.exit(0)
        
        pre_port = None 

        try:
            print(f"Initializing {port}...")
            # Ensure previous instance is closed
            if state.smu: state.smu.disconnect()
            
            state.smu = SMU(port=port)
            state.connection_status = "Connected"
            logger.set_logging_parameters(smu=state.smu)
            state.log_message_to_state_history(f"Connected to {port}")

        except Exception as e:
            print(f"Failed: {e}")
            time.sleep(2)
            continue

        # --- TUI Phase ---
        state.running = True
        
        # This blocks until the user quits OR the SMU disconnects
        exit_code = run_main_tui(state)

        if exit_code != EXIT_CRITICAL_DISCONNECT:
            break # User quit normally
        
        # --- CRITICAL DISCONNECT HANDLING ---
        # 1. Update status
        state.connection_status = "Disconnected"
        
        # 2. Show the Pop-up Alert (New Code)
        # Use the port name from state, or 'Unknown' if unavailable
        current_port = state.smu.port if state.smu else "Unknown"
        show_disconnect_alert(current_port)
        
        # 3. Loop restarts, sending user back to DynamicPortSelector...
        # time.sleep(0.01)

if __name__ == "__main__":
    main()