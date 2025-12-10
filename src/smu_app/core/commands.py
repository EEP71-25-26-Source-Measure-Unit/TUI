import shlex
from .state import AppState

HELP_TEXT = """Commands:
vmode <V>               Set voltage (e.g.: vmode 5.0)
cmode <I>               Set current (e.g.: cmode 0.05)
logdata <on|off>        Enable/Disable CSV logging
mode?                   Get limits
exit, quit              Exit
"""

def process_command(cmd_str: str, app_state: AppState, ui_exiter=None):
    """
    Parses string commands and applies them to the AppState.
    """
    if not app_state.smu:
        app_state.log_message_to_state_history("Error: SMU not initialized.")
        return

    try:
        args = shlex.split(cmd_str)
    except ValueError as e:
        app_state.log_message_to_state_history(f"Syntax Error: {e}")
        return
    
    if not args:
        app_state.log_message_to_state_history(f"Unknown command: '' type 'help' for a list of commands.")
        return
    
    app_state.log_message_to_state_history(f"> {cmd_str}")
    cmd = args[0].lower()

    try:
        if cmd in ("exit", "quit", "q"):
            app_state.running = False
            if ui_exiter: ui_exiter() # Call the UI exit callback
            
        elif cmd in ("help", "h", "?"):
            app_state.log_message_to_state_history(HELP_TEXT)
            
        elif cmd in ("clear", "cls"):
            with app_state.lock:
                app_state.command_log.clear()

        elif cmd == "vmode":
            if len(args) != 2: app_state.log_message_to_state_history("Usage: vmode <voltage>")
            else:
                app_state.smu.set_voltage(float(args[1]))
                app_state.log_message_to_state_history(f"Set Voltage: {args[1]} V")

        elif cmd == "cmode":
            if len(args) != 2: app_state.log_message_to_state_history("Usage: cmode <current>")
            else:
                app_state.smu.set_current(float(args[1]))
                app_state.log_message_to_state_history(f"Set Current: {args[1]} A")

        elif cmd == "logdata":
            if len(args) != 2: app_state.log_message_to_state_history("Usage: logdata <on|off>")
            elif args[1].lower() == "on":
                if app_state.logger: app_state.logger.start_data_logging()
            elif args[1].lower() == "off":
                if app_state.logger: app_state.logger.stop_data_logging()

        elif cmd == "mode?":
            v_lim = app_state.smu.voltage_limit()
            i_lim = app_state.smu.current_limit()
            app_state.log_message_to_state_history(f"Limits -> V: {v_lim} V, I: {i_lim} A")
            
        else:
            app_state.log_message_to_state_history(f"Unknown command: '{cmd}' type 'help' for a list of commands.")

    except Exception as e:
        app_state.log_message_to_state_history(f"Execution Error: {e}")