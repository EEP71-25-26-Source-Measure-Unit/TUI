import sys
import atexit
import time
from textual.app import App
from smu_app.core.state import AppState
from smu_app.hardware.driver import SMU
from smu_app.logging.recorder import SMULogger
from smu_app.ui.screens import ConnectionScreen, DashboardScreen, DisconnectModal

class SMUTool(App):
    CSS_PATH = "smu_app/ui/styles.tcss"
    SCREENS = {
        "connection": ConnectionScreen,
    }

    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.state.logger = SMULogger(smu=None)

    def on_mount(self):
        atexit.register(self.cleanup)
        self.push_screen("connection")

    def connect_smu(self, port: str) -> bool:
        """Attempts to connect. Verification is now inside the Driver."""
        
        # 1. Clean old reference
        if self.state.smu:
            try: self.state.smu.disconnect()
            except: pass
            self.state.smu = None

        # 2. Reset UI Data
        with self.state.lock:
            self.state.latest_voltage = 0.0
            self.state.latest_current = 0.0
            self.state.connection_status = "Connecting..."
        
        # 3. Connection Loop (Handle Windows Permission Errors)
        attempts = 2 
        last_error = None
        
        for i in range(attempts):
            new_smu = None
            try:
                new_smu = SMU(port=port)
                
                # This calls Open -> *IDN? -> Verify "SMU"
                # If it fails, it raises IOError and auto-closes the port.
                new_smu.connect() 
                
                # If we reached here, it is a valid SMU.
                self.state.smu = new_smu
                self.state.connection_status = "Connected"
                self.state.logger.set_logging_parameters(smu=self.state.smu)
                return True
                
            except Exception as e:
                # Ensure object is cleaned up if it was created
                if new_smu: 
                    new_smu.disconnect()
                
                last_error = e
                # Retry only on PermissionError (e.g. previous handle still closing)
                if "PermissionError" in str(e) or "Access is denied" in str(e):
                    time.sleep(0.5)
                    continue
                else:
                    # Timeouts or Wrong IDs are fatal -> break immediately
                    break
        
        self.notify(f"Connection Failed: {last_error}", severity="error")
        return False

    def handle_critical_disconnect(self, port_name: str):
        self.state.connection_status = "Disconnected"
        if self.state.smu:
            try: self.state.smu.disconnect()
            except: pass
            self.state.smu = None
        
        def on_dismiss(result):
            while len(self.screen_stack) > 1:
                self.pop_screen()
            if not isinstance(self.screen, ConnectionScreen):
                self.push_screen("connection")

        self.push_screen(DisconnectModal(port_name), callback=on_dismiss)

    def cleanup(self):
        if self.state.smu:
            self.state.smu.disconnect()
        if self.state.logger:
            self.state.logger.shutdown()

if __name__ == "__main__":
    app = SMUTool()
    app.run()