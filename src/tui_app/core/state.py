import threading
from dataclasses import dataclass, field
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from smulib.smu import SMU
    from smulib.logging import SMULogger

@dataclass
class AppState:
    """
    Central shared state for the application.
    """
    # Hardware & Logging
    smu: Optional['SMU'] = None
    logger: Optional['SMULogger'] = None
    
    # Synchronization
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = True
    
    # Measurement Data
    latest_voltage: float = 0.0
    latest_current: float = 0.0
    connection_status: str = "Disconnected"
    
    # System Status (New fields for Pico firmware)
    output_enabled: bool = False
    over_current_tripped: bool = False
    voltage_limit: float = 0.0
    current_limit: float = 0.0
    
    # UI Buffers
    command_log: List[str] = field(default_factory=list)
    
    def log_message_to_state_history(self, message: str):
        """Thread-safe logging to the UI buffer."""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        with self.lock:
            for line in str(message).splitlines():
                self.command_log.append(f"[{timestamp}] {line}")
            if len(self.command_log) > 200:
                self.command_log = self.command_log[-195:]