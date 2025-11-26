import threading
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class AppState:
    smu: Optional[object] = None 
    logger: Optional[object] = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    
    # Data
    latest_voltage: float = 0.0
    latest_current: float = 0.0
    connection_status: str = "Disconnected"
    
    # Persistent Log History
    # We store the markup strings here so they can be re-written to the RichLog
    log_history: List[str] = field(default_factory=list)

    def append_log(self, msg: str):
        """Thread-safe append to history."""
        with self.lock:
            self.log_history.append(msg)
            # Keep only last 200 lines to save memory
            if len(self.log_history) > 200:
                self.log_history.pop(0)