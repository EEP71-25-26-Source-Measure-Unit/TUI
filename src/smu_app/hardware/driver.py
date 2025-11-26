import logging
import threading
import serial
from serial.tools import list_ports
from .base import SMUBase

_LOG = logging.getLogger(__name__)

class SMU(SMUBase):
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.2):
        self.__port = port
        self.__baudrate = baudrate
        self.__timeout = timeout 
        self._serial = None
        self._serial_lock = threading.Lock()

    @property
    def port(self) -> str:
        return self.__port

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self) -> None:
        """
        Opens the port AND verifies identity.
        Raises IOError if port cannot open OR if device is not an SMU.
        """
        with self._serial_lock:
            # 1. Cleanup previous state
            if self._serial:
                try: self._serial.close()
                except Exception: pass
                self._serial = None

            # 2. Open Serial Port
            try:
                self._serial = serial.Serial(
                    port=self.__port, 
                    baudrate=self.__baudrate, 
                    timeout=self.__timeout,
                    write_timeout=self.__timeout,
                    exclusive=True
                )
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
            except Exception as e:
                self._serial = None
                raise IOError(f"Could not open port {self.__port}: {e}") from e

            # 3. VERIFICATION (Handshake)
            try:
                # We access the internal write/read directly here since we hold the lock
                self._serial.write(b"*IDN?\n")
                
                # Readline blocks until \n or timeout
                raw = self._serial.readline()
                
                if not raw:
                    raise IOError("Device did not respond (Timeout). Is it an SMU?")
                
                identity = raw.decode(errors='ignore').strip()
                
                if "SMU" not in identity:
                    raise IOError(f"Device is not an SMU. ID: '{identity}'")
                
                _LOG.debug(f"Verified SMU on {self.__port}: {identity}")

            except Exception as e:
                # If handshake fails, CLOSE the port immediately!
                self._serial.close()
                self._serial = None
                raise IOError(f"Handshake failed: {e}")

    def disconnect(self) -> None:
        with self._serial_lock:
            if self._serial:
                try:
                    self._serial.cancel_read()
                    self._serial.cancel_write()
                except Exception:
                    pass
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._serial = None

    def __write(self, command: str) -> None:
        if self._serial is None: raise IOError("Serial not connected")
        try:
            self._serial.write((command + "\n").encode())
        except Exception as e:
            self._serial = None
            raise IOError(f"Write failed: {e}")

    def __read(self, command: str) -> str:
        if self._serial is None: raise IOError("Serial not connected")
        try:
            self.__write(command)
            raw = self._serial.readline()
            if not raw: 
                raise IOError("No data received (timeout)")
            return raw.decode(errors='ignore').strip()
        except Exception as e:
            raise IOError(str(e))

    # Standard Commands
    def set_voltage(self, v: float) -> None:
        with self._serial_lock: self.__write(f":SOUR:VOLT {float(v)}")

    def set_current(self, i: float) -> None:
        with self._serial_lock: self.__write(f":SOUR:CURR {float(i)}")

    def voltage_limit(self) -> float:
        with self._serial_lock: return float(self.__read(":SOUR:VOLT:LIM?"))

    def current_limit(self) -> float:
        with self._serial_lock: return float(self.__read(":SOUR:CURR:LIM?"))

    def measure_voltage(self) -> float:
        with self._serial_lock: return float(self.__read(":MEAS:VOLT?"))

    def measure_current(self) -> float:
        with self._serial_lock: return float(self.__read(":MEAS:CURR?"))