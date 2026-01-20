import sys
import argparse
import atexit
import time
import threading 

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
        buttons=[] 
    )

    style = Style.from_dict({
        'dialog': 'bg:#880000 #ffffff',        
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

    t = threading.Thread(target=close_timer, daemon=True)
    t.start()
    
    app.run()

def main():
    state = AppState()
    logger = SMULogger(smu=None)
    state.logger = logger

    def cleanup():
        print("Shutting down...")
        if state.smu: state.smu.disconnect()
        logger.shutdown()

    atexit.register(cleanup)

    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", help="Pre-select port")
    args = parser.parse_args()
    pre_port = args.port

    # Main Application Loop
    while True:
        port = pre_port
        if not port:
            title = "SMU SELECT" if state.connection_status == "Disconnected" else "RECONNECT SMU"
            port = DynamicPortSelector(title=title).run()
            if not port:
                sys.exit(0)
        
        pre_port = None 

        try:
            print(f"Initializing {port}...")
            if state.smu: state.smu.disconnect()
            
            state.smu = SMU(port=port)
            state.connection_status = "Connected"
            logger.set_logging_parameters(smu=state.smu)
            state.log_message_to_state_history(f"Connected to {port}")

        except Exception as e:
            print(f"Failed: {e}")
            time.sleep(2)
            continue

        state.running = True
        
        # This blocks until the user quits OR the SMU disconnects
        exit_code = run_main_tui(state)

        if exit_code != EXIT_CRITICAL_DISCONNECT:
            break 
        
        state.connection_status = "Disconnected"
        
        current_port = state.smu.port if state.smu else "Unknown"
        show_disconnect_alert(current_port)

if __name__ == "__main__":
    main()