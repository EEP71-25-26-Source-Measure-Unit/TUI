import threading
import time
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, WindowAlign
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
        
        # Add Trip Status
        trip_status = " [TRIPPED] " if app_state.over_current_tripped else ""
        trip_style = "bg:ansired bold #ffffff" if app_state.over_current_tripped else ""
        
        return FormattedText([
            ("", " SMU CLI "),
            ("bg:ansipurple #ffffff", " Pro "),
            ("", " Status: "),
            (f"{color} #000000", f" {c} "),
            (trip_style, trip_status),
            ("", f" ({app_state.smu.port if app_state.smu else '-'}) ")
        ])
    
    info_bar = Window(content=FormattedTextControl(get_status_text), height=1)

    # 2. Log Window (TextArea for auto-scroll)
    log_area = TextArea(text="", read_only=True, scrollbar=True, focusable=False)

    # 3. Measurements
    def get_measure_text():
        with app_state.lock:
            v = app_state.latest_voltage
            i = app_state.latest_current
        return FormattedText([
            ('bg:#ansiwhite #000000', ' Measure: '),
            ('bg:#ansiwhite #000000', f'{v:8.3f} V'),
            ('', '    '),
            ('bg:#ansiwhite #000000', f'{(i * 1000):8.3f} mA')
        ])
    
    def get_source_text():
        with app_state.lock:
            # Use source_voltage (target) if available in State
            v = getattr(app_state, 'source_voltage', 0.0) 
            enabled = getattr(app_state, 'output_enabled', False)
            
        status_char = "*" if enabled else "x"
        status_color = "ansigreen" if enabled else "ansired"
        
        return FormattedText([
            ('bg:#ansiwhite #000000', ' Source: '),
            (f'fg:{status_color} bg:#ansiwhite', f'[{status_char}]'),
            ('bg:#ansiwhite #000000', f' {v:8.4f} V ')
        ])
    
    readout = Window(content=FormattedTextControl(get_measure_text), height=1, style='bg:#ansiwhite #000000', align=WindowAlign("LEFT"))
    source = Window(content=FormattedTextControl(get_source_text), height=1, style='bg:#ansiwhite #000000', align=WindowAlign("LEFT"))

    # 4. Input
    def on_enter(buff):
        process_command(buff.document.text, app_state, lambda: app.exit(EXIT_USER_QUIT))
        return False # Keep focus
        
    input_field = TextArea(height=1, prompt="> ", multiline=False, accept_handler=on_enter)

    vertical_bar = Window(
        content=FormattedTextControl(FormattedText([
            ('bg:#ansiwhite #000000', '|'),
        ])),
        height=1,
        width=1,
        style = 'bg:#ansiwhite #000000',
        align= WindowAlign("CENTER")
    )

    # readout_source_values_container = VSplit([
    #     readout,
    #     vertical_bar,
    #     source
    # ])

    # --- Layout ---
    root = HSplit([
        info_bar,
        HorizontalLine(),
        log_area,
        HorizontalLine(),
        # readout_source_values_container,
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

    # --- Background Updater Thread (OPTIMIZED) ---
    def worker():
        last_log_count = 0
        
        def sync_logs_to_tui():
            nonlocal last_log_count
            # 1. LOG OPTIMIZATION: Only rebuild string if new logs arrived
            # This significantly reduces CPU usage by skipping string ops on idle frames
            current_log_count = 0
            with app_state.lock:
                current_log_count = len(app_state.command_log)
            
            if current_log_count != last_log_count:
                with app_state.lock:
                    logs = list(app_state.command_log)
                new_text = "\n".join(logs)

                if log_area.text != new_text:
                    log_area.text = new_text
                    log_area.buffer.cursor_position = len(new_text) # Auto-scroll
                
                last_log_count = current_log_count
                return True
            return False

            # 2. HARDWARE POLLING
        while app_state.running:
            needs_redraw = False

            if sync_logs_to_tui(): needs_redraw = True
            
            if app_state.smu:
                try:
                    # These calls are now non-blocking on the hardware side (if using new Pico FW)
                    # But the serial read still takes a few ms.
                    v = app_state.smu.measure_voltage()
                    i = app_state.smu.measure_current()

                    # app_state.log_message_to_state_history(f'{v}, {i}')
                    
                    # Update state
                    with app_state.lock:
                        app_state.latest_voltage = v
                        app_state.latest_current = i
                        app_state.connection_status = "Connected"
                        
                        # Update new fields if available via commands (optional enhancement)
                        # e.g. status = app_state.smu.get_status()
                    
                    # Force redraw for readouts
                    needs_redraw = True
                    
                except Exception as e:
                    # print(e)
                    # 3. NON-BLOCKING RECONNECT LOGIC
                    app_state.log_message_to_state_history(f"Disconnected, disabling output!!")
                    # app_state.smu.set_output(False)
                    app_state.log_message_to_state_history(f"Disconnect: {e}")
                    with app_state.lock: app_state.connection_status = "Reconnecting..."

                    sync_logs_to_tui()
                    app.invalidate()
                    
                    reconnected = False
                    backoff = 0.5
                    max_attempts = 5
                    
                    # UI Thread handles the loop, keeping app responsive
                    for attempt in range(1, max_attempts + 1):
                        if not app_state.running: break
                        
                        try:
                            # Driver.connect() is single-shot now\
                            app_state.smu.connect()
                            app_state.smu.set_output(False)
                            reconnected = True
                            app_state.log_message_to_state_history("Reconnected!")
                            sync_logs_to_tui()
                            break
                        except Exception as retry_err:
                            # Sleep in small chunks to allow clean exit during backoff
                            sleep_accum = 0
                            while sleep_accum < backoff:
                                if not app_state.running: break
                                time.sleep(0.1)
                                sleep_accum += 0.1
                            
                            backoff = min(backoff * 1.5, 3.0)

                    if not reconnected:
                        # Only exit if user didn't quit manually
                        if app_state.running:
                            app.exit(EXIT_CRITICAL_DISCONNECT)
                        return

            # CPU Control: 10Hz Refresh
            # Decreasing this to 0.2 (5Hz) drops CPU usage further if needed
            if needs_redraw: app.invalidate()

            time.sleep(0.1)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    
    return app.run()