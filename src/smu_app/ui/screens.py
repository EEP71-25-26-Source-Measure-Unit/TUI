import time
import threading
from serial.tools import list_ports
from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen, ModalScreen
# REMOVED: Footer from imports
from textual.widgets import Header, Button, Label, Input, RichLog, OptionList, Static

from ..core.commands import process_command

# --- 1. Disconnect Alert (Modal) ---
class DisconnectModal(ModalScreen):
    def __init__(self, port_name: str):
        super().__init__()
        self.port_name = port_name

    def compose(self) -> ComposeResult:
        with Container(id="alert-box"):
            yield Label(f"CRITICAL DISCONNECT\n", classes="title")
            yield Label(f"SMU on port {self.port_name} disconnected unexpectedly!")
            yield Label("\nReturning to connection screen in 3 seconds...")

    def on_mount(self) -> None:
        self.set_timer(3.0, self.dismiss_and_reset)

    def dismiss_and_reset(self) -> None:
        self.dismiss(result=True)

# --- 2. Connection Screen ---
class ConnectionScreen(Screen):
    CSS_PATH = "styles.tcss"

    def on_mount(self) -> None:
        self.current_port_list = []
        self._stop_scanning = threading.Event()
        self._scan_thread = None
        self.start_scanning()

    def on_screen_resume(self) -> None:
        self.start_scanning()

    def on_unmount(self) -> None:
        self.stop_scanning()

    def start_scanning(self):
        self._stop_scanning.clear()
        if self._scan_thread is None or not self._scan_thread.is_alive():
            self._scan_thread = threading.Thread(target=self.scan_ports, daemon=True)
            self._scan_thread.start()

    def stop_scanning(self):
        self._stop_scanning.set()

    def compose(self) -> ComposeResult:
        with Container(id="connect-dialog"):
            yield Label("SMU CONNECTION", classes="header")
            yield Label("Scanning...", id="scan-label")
            yield OptionList(id="port-list")
            with Horizontal(classes="buttons"):
                yield Button("Connect", id="btn-connect", variant="primary")
                yield Button("Exit", id="btn-exit", variant="error")

    def scan_ports(self):
        while not self._stop_scanning.is_set():
            try:
                raw_ports = list_ports.comports()
                options = [f"{p.device}: {p.description}" for p in raw_ports]
                if not self._stop_scanning.is_set():
                    self.app.call_from_thread(self.update_list, options)
            except Exception:
                pass
            
            for _ in range(10):
                if self._stop_scanning.is_set(): return
                time.sleep(0.1)

    def update_list(self, options: list[str]):
        if options == self.current_port_list: return
        self.current_port_list = options 
        
        try:
            opt_list = self.query_one("#port-list", OptionList)
            lbl = self.query_one("#scan-label", Label)
        except: return 

        old_idx = opt_list.highlighted or 0
        opt_list.clear_options()
        
        if not options:
            lbl.update("No devices found.")
            opt_list.add_option("Scanning...")
            opt_list.disabled = True
        else:
            lbl.update("Select a Device:")
            for opt in options:
                opt_list.add_option(opt)
            opt_list.disabled = False
            if options:
                target_idx = old_idx if old_idx < len(options) else 0
                opt_list.highlighted = target_idx

    @on(Button.Pressed, "#btn-exit")
    def exit_app(self):
        self.app.exit()

    @on(OptionList.OptionSelected)
    def on_list_enter(self, event: OptionList.OptionSelected):
        if event.option and not self.query_one("#port-list").disabled:
            self.initiate_connection(str(event.option.prompt))

    @on(Button.Pressed, "#btn-connect")
    def on_btn_connect(self):
        opt_list = self.query_one("#port-list", OptionList)
        if opt_list.disabled or opt_list.highlighted is None:
            self.notify("Please select a port.", severity="warning")
            return
        selection_text = str(opt_list.get_option_at_index(opt_list.highlighted).prompt)
        self.initiate_connection(selection_text)

    def initiate_connection(self, selection_text: str):
        self.stop_scanning()
        port = selection_text.split(":")[0].strip()
        success = self.app.connect_smu(port)
        if success:
            self.app.push_screen(DashboardScreen())
        else:
            self.start_scanning()

# --- 3. Dashboard Screen ---
class DashboardScreen(Screen):
    CSS_PATH = "styles.tcss"
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log-area", highlight=True, markup=True)
        with Container(id="readout-bar"):
            yield Static("VOLTAGE: --.-- V", id="lbl-volt", classes="readout")
            yield Static("CURRENT: --.-- A", id="lbl-curr", classes="readout")
        yield Input(placeholder="Enter command...", id="input-bar")
        # REMOVED: yield Footer()

    def on_mount(self):
        self.query_one("#input-bar").focus()
        port = getattr(self.app.state.smu, 'port', 'Unknown')
        
        # Restore History
        log_widget = self.query_one("#log-area", RichLog)
        with self.app.state.lock:
            for msg in self.app.state.log_history:
                log_widget.write(msg)
        
        # Reset Readouts
        self.query_one("#lbl-volt", Static).update("VOLTAGE: --.-- V")
        self.query_one("#lbl-curr", Static).update("CURRENT: --.-- A")
        
        self.log_message(f"[green]Dashboard connected to {port}[/]")
        
        self._stop_polling = threading.Event()
        self._poll_thread = threading.Thread(target=self.poll_hardware, daemon=True)
        self._poll_thread.start()

    def on_unmount(self):
        self._stop_polling.set()

    def log_message(self, msg: str):
        self.app.state.append_log(msg)
        try:
            log = self.query_one("#log-area", RichLog)
            log.write(msg)
        except Exception:
            pass 

    @on(Input.Submitted)
    def handle_command(self, event: Input.Submitted):
        cmd = event.value
        event.input.value = ""
        screen_self = self 
        
        class UIAdapter:
            def log_message(self, m): screen_self.log_message(m)
            @property
            def smu(self): return screen_self.app.state.smu
            @property
            def lock(self): return screen_self.app.state.lock
            @property
            def running(self): return True
            @running.setter
            def running(self, v): 
                if not v: screen_self.app.exit()
            @property
            def logger(self): return screen_self.app.state.logger

        process_command(cmd, UIAdapter())

    def poll_hardware(self):
        state = self.app.state
        my_smu = state.smu 
        time.sleep(0.2)

        while not self._stop_polling.is_set():
            if not state.smu or state.smu != my_smu:
                break

            try:
                v = state.smu.measure_voltage()
                i = state.smu.measure_current()
                
                with state.lock:
                    state.latest_voltage = v
                    state.latest_current = i
                    state.connection_status = "Connected"
                
                self.app.call_from_thread(self.update_readouts, v, i)
                time.sleep(0.1)

            except Exception as e:
                # Auto-Reconnect
                with state.lock: state.connection_status = "Reconnecting..."
                
                self.app.call_from_thread(self.log_message, f"[bold red]Connection Lost: {e}[/]")
                self.app.call_from_thread(self.log_message, "[yellow]Attempting to auto-reconnect...[/]")
                
                reconnected = False
                backoff = 0.5
                max_attempts = 5
                
                for attempt in range(1, max_attempts + 1):
                    if self._stop_polling.is_set(): return 

                    try:
                        state.smu.connect()
                        reconnected = True
                        self.app.call_from_thread(self.log_message, "[bold green]Reconnection Successful![/]")
                        break
                    except Exception as recon_err:
                        self.app.call_from_thread(self.log_message, f"Reconnect attempt {attempt} failed ({recon_err})")
                        
                        for _ in range(int(backoff * 10)):
                            if self._stop_polling.is_set(): return
                            time.sleep(0.1)
                        backoff = min(backoff * 1.5, 3.0)

                if not reconnected:
                    if not self._stop_polling.is_set():
                        self.app.call_from_thread(self.trigger_critical_disconnect)
                    return 

    def update_readouts(self, v, i):
        try:
            self.query_one("#lbl-volt", Static).update(f"VOLTAGE: {v:8.3f} V")
            self.query_one("#lbl-curr", Static).update(f"CURRENT: {i:8.4f} A")
        except Exception:
            pass

    def trigger_critical_disconnect(self):
        port = getattr(self.app.state.smu, 'port', 'Unknown')
        self.app.handle_critical_disconnect(port)