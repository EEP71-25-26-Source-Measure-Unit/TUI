import threading
from dataclasses import dataclass, field
from typing import Optional, List

# Use TYPE_CHECKING to avoid circular imports at runtime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..hardware.driver import SMU
    from ..logging.recorder import SMULogger

@dataclass
class AppState:
    """
    Central shared state for the application.
    Replaces global variables for thread-safety and modularity.
    """
    # Hardware & Logging
    smu: Optional['SMU'] = None
    logger: Optional['SMULogger'] = None
    
    # Synchronization
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = True
    
    # Measurement Data (Shared between Thread and UI)
    latest_voltage: float = 0.0
    latest_current: float = 0.0
    connection_status: str = "Disconnected"
    
    # UI Buffers
    command_log: List[str] = field(default_factory=list)
    
    def log_message(self, message: str):
        """Thread-safe logging to the UI buffer."""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        with self.lock:
            for line in str(message).splitlines():
                self.command_log.append(f"[{timestamp}] {line}")
            # Keep buffer size manageable
            if len(self.command_log) > 200:
                self.command_log = self.command_log[-200:]