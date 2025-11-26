import logging
import time
import threading
import serial
from serial.tools import list_ports
from .base import SMUBase

_LOG = logging.getLogger(__name__)

class SMU(SMUBase):
    def __init__(self, port: str, baudrate: int = 115200, timeout: float | None = 1.0):
        self.__port = port
        self.__baudrate = baudrate
        self.__timeout = timeout
        self._serial = None
        self._serial_lock = threading.Lock()
        self.max_backoff = 3.0

        try:
            self.connect()
        except Exception:
            _LOG.exception("Initial connect failed for %s", port)
            self._serial = None

    @property
    def port(self) -> str:
        return self.__port

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self) -> None:
        with self._serial_lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            try:
                self._serial = serial.Serial(port=self.__port, baudrate=self.__baudrate, timeout=self.__timeout)
                _LOG.debug("Connected to SMU on %s", self.__port)
            except Exception as e:
                self._serial = None
                raise IOError(f"Could not open port {self.__port}: {e}") from e

    def disconnect(self) -> None:
        with self._serial_lock:
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                finally:
                    self._serial = None

    def reconnect(self) -> None:
        backoff = 0.1
        attempts = 0
        while True:
            try:
                self.connect()
                return
            except IOError:
                attempts += 1
                if backoff > self.max_backoff:
                    raise IOError(f"Failed to reconnect after {attempts} attempts")
                time.sleep(backoff)
                backoff *= 2

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
            if not raw: raise IOError("No data received")
            return raw.decode(errors='ignore').strip()
        except Exception as e:
            self._serial = None
            raise IOError(f"Read failed: {e}")

    # ... Include set_voltage, set_current, etc. exactly as they were ...
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

    @staticmethod
    def discover_ports() -> dict[str, str]:
        ports = list_ports.comports()
        return {port.device: port.description for port in ports}