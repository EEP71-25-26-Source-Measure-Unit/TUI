import threading
import time
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.widgets import HorizontalLine, TextArea
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.formatted_text import FormattedText

from ..core.state import AppState
from ..core.commands import process_command

EXIT_USER_QUIT = 0
EXIT_CRITICAL_DISCONNECT = 1

def run_main_tui(app_state: AppState) -> int:
    """
    Sets up and runs the main dashboard.
    Returns an exit code (0 for quit, 1 for restart/disconnect).
    """
    
    # --- UI Components ---
    
    # 1. Status Bar
    def get_status_text():
        # Determine color based on state
        c = app_state.connection_status
        color = "bg:ansigreen" if c == "Connected" else "bg:ansired"
        if "Reconnecting" in c: color = "bg:ansiyellow"
        
        return FormattedText([
            ("", " SMU CLI "),
            ("bg:ansipurple #ffffff", " Pro "),
            ("", " Status: "),
            (f"{color} #000000", f" {c} "),
            ("", f" ({app_state.smu.port if app_state.smu else '-'}) ")
        ])
    
    info_bar = Window(content=FormattedTextControl(get_status_text), height=1)

    # 2. Log Window (TextArea for auto-scroll)
    log_area = TextArea(text="", read_only=True, scrollbar=True, focusable=False)

    # 3. Measurements
    def get_meas_text():
        with app_state.lock:
            v = app_state.latest_voltage
            i = app_state.latest_current
        return FormattedText([
            ('bg:#ansiwhite #000000', f' V: {v:8.3f} V '),
            ('', '  '),
            ('bg:#ansiwhite #000000', f' I: {i:8.4f} A ')
        ])
    
    readout = Window(content=FormattedTextControl(get_meas_text), height=1, style='bg:#ansiwhite #000000')

    # 4. Input
    def on_enter(buff):
        process_command(buff.document.text, app_state, lambda: app.exit(EXIT_USER_QUIT))
        return False # Keep focus
        
    input_field = TextArea(height=1, prompt="> ", multiline=False, accept_handler=on_enter)

    # --- Layout ---
    root = HSplit([
        info_bar,
        HorizontalLine(),
        log_area,
        HorizontalLine(),
        readout,
        HorizontalLine(),
        input_field
    ])

    kb = KeyBindings()
    @kb.add("c-c")
    def _(event):
        app_state.running = False
        event.app.exit(EXIT_USER_QUIT)

    app = Application(layout=Layout(root, focused_element=input_field), key_bindings=kb, full_screen=True, mouse_support=True)

    # --- Background Updater Thread ---
    def worker():
        while app_state.running:
            # Sync Log Buffer to UI
            # We copy the list under lock to avoid modification during iteration issues
            with app_state.lock:
                logs = list(app_state.command_log)
            
            new_text = "\n".join(logs)
            if log_area.text != new_text:
                log_area.text = new_text
                log_area.buffer.cursor_position = len(new_text) # Auto-scroll

            # Hardware Polling
            if app_state.smu:
                try:
                    v = app_state.smu.measure_voltage()
                    i = app_state.smu.measure_current()
                    with app_state.lock:
                        app_state.latest_voltage = v
                        app_state.latest_current = i
                        app_state.connection_status = "Connected"
                except Exception as e:
                    app_state.log_message(f"Disconnect: {e}")
                    with app_state.lock: app_state.connection_status = "Reconnecting..."
                    app.invalidate()
                    
                    try:
                        app_state.smu.reconnect()
                        app_state.log_message("Reconnected!")
                    except:
                        # Critical failure
                        app.exit(EXIT_CRITICAL_DISCONNECT)
                        return

            app.invalidate()
            time.sleep(0.1)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    
    return app.run()