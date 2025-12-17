import threading
import time
from serial.tools import list_ports
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.widgets import RadioList, Label, Button, Dialog
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.styles import Style

class DynamicPortSelector:
    def __init__(self, title="SMU CONNECTION"):
        self.selected_port = None
        self.cancelled = False
        self.scanning = True
        
        # FIX: Initialize with a placeholder value to prevent AssertionError
        self.radio_list = RadioList(values=[('scanning', 'Scanning for devices...')])
        self.label = Label(text="Scanning...")

        self.connect_button = Button("Connect", handler=self._accept)
        self.exit_button = Button("Exit", handler=self._cancel)
        root = Dialog(
            title=title,
            body=HSplit([self.label, self.radio_list]),
            buttons=[
                self.connect_button,
                self.exit_button
            ],
            width=60
        )
        
        kb = KeyBindings()
        @kb.add("c-c")
        def _(event):
            self._cancel()

        self.app = Application(
            layout=Layout(root, focused_element=self.connect_button),
            key_bindings=kb,
            full_screen=True,
            mouse_support=True,
            style=Style.from_dict({
                'dialog': 'bg:#0000aa', 
                'dialog.body': 'bg:#aaaaaa #000000'
            })
        )

    def _accept(self):
        val = self.radio_list.current_value
        # Prevent selecting the placeholder
        if val == 'scanning' or val == 'none':
            return 

        self.selected_port = val
        self.scanning = False
        self.app.exit()

    def _cancel(self):
        self.cancelled = True
        self.scanning = False
        self.app.exit()

    def _update_loop(self):
        last_ports = []
        while self.scanning:
            try:
                raw = list_ports.comports()
                
                if not raw:
                    # Provide a placeholder if no ports found
                    new_vals = [('none', 'No devices found. Plug in SMU...')]
                    label_text = "No devices found."
                else:
                    new_vals = [(p.device, f"{p.device}: {p.description}") for p in raw]
                    label_text = "Select Device:"

                # Update only if changed
                if new_vals == last_ports: continue
                self.radio_list.values = new_vals
                
                # Auto-select the first real option if available
                if raw and (self.radio_list.current_value == 'scanning' or self.radio_list.current_value == 'none'):
                        self.radio_list.current_value = new_vals[0][0]
                
                self.label.text = label_text
                last_ports = new_vals
                self.app.invalidate()
            except Exception as e: 
                print(e) # actually log this somewhere
            time.sleep(0.5)

    def run(self):
        t = threading.Thread(target=self._update_loop, daemon=True)
        t.start()
        self.app.run()
        return self.selected_port if not self.cancelled else None