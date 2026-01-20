import shlex
from .state import AppState

HELP_TEXT = """
logdata [on|off]        Enable/Disable CSV logging
output  [on|off]        Enable/Disable SMU output
vlimit  [V]             Set voltage (e.g.: vlimit 5.0)
climit  [mA]            Set current (e.g.: climit 75)
mode?                   Get limits

clear, cls              Clear the terminal screen
help, h, ?              Show this message

exit, quit, q           Exit
"""

UNKNOWN_COMMAND_MESSAGE = f"Unknown command:"
UNKNOWN_COMMAND_HELP_MESSAGE = f"Type 'help' for a list of available commands."

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
        app_state.log_message_to_state_history(f">")
        app_state.log_message_to_state_history(f"{UNKNOWN_COMMAND_MESSAGE} ' '")
        app_state.log_message_to_state_history(UNKNOWN_COMMAND_HELP_MESSAGE)
        return
    
    app_state.log_message_to_state_history(f"> {cmd_str}")
    cmd = args[0].lower()

    try:
        if cmd in ("exit", "quit", "q"):
            app_state.running = False
            if ui_exiter: ui_exiter() 
            
        elif cmd in ("help", "h", "?"):
            app_state.log_message_to_state_history(HELP_TEXT)
            
        elif cmd in ("clear", "cls"):
            with app_state.lock:
                app_state.command_log.clear()

        elif cmd == "vlimit":
            if len(args) != 2: app_state.log_message_to_state_history("Usage: vlimit <voltage>")
            else:
                app_state.smu.set_voltage(float(args[1]))
                app_state.log_message_to_state_history(f"Set Voltage: {args[1]} V")

        elif cmd == "setv":
            if len(args) != 2: app_state.log_message_to_state_history("Usage: setv <voltage>")
            else:
                app_state.smu.set_voltage(float(args[1]))
                app_state.log_message_to_state_history(f"Set Voltage: {args[1]} V")

        elif cmd == "climit":
            if len(args) != 2: app_state.log_message_to_state_history("Usage: climit <current>")
            else:
                app_state.smu.set_current(float(args[1]))
                app_state.log_message_to_state_history(f"Set Current: {args[1]} mA")

        elif cmd == "logdata":
            if len(args) != 2: app_state.log_message_to_state_history("Usage: logdata <on|off>")
            elif args[1].lower() == "on":
                if app_state.logger: app_state.logger.start_data_logging()
            elif args[1].lower() == "off":
                if app_state.logger: app_state.logger.stop_data_logging()

        elif cmd == "output":
            if len(args) != 2 or args[1].lower() not in ["on", "off"]:
                app_state.log_message_to_state_history("Wrong command usage. Usage: output <on|off>")
                return
            elif args[1].lower() == "on": app_state.smu.set_output(True)
            elif args[1].lower() == "off": app_state.smu.set_output(False)
            app_state.log_message_to_state_history(f"Output changed to {args[1].lower() }")

        elif cmd == "mode?":
            v_lim = app_state.smu.voltage_limit()
            i_lim = app_state.smu.current_limit()
            app_state.log_message_to_state_history(f"Limits -> {v_lim} V, {i_lim} mA")

        elif cmd == "zero":
            app_state.smu.zero_tare()
            app_state.log_message_to_state_history(f"Zeroed")
            
        else:
            app_state.log_message_to_state_history(f"{UNKNOWN_COMMAND_MESSAGE} '{cmd}'")
            app_state.log_message_to_state_history(UNKNOWN_COMMAND_HELP_MESSAGE)

    except Exception as e:
        app_state.log_message_to_state_history(f"Execution Error: {e}")