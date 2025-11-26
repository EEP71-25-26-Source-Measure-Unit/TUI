from __future__ import annotations
import threading
import logging
import time
import os
import csv
from datetime import datetime, timezone, date
from typing import Dict, Any, Optional
from logging.handlers import RotatingFileHandler

# Import locally to avoid circular imports if package structure allows, 
# otherwise assume smu class is available
# from ..smu import SMU 

CSV_HEADERS = ["timestamp_utc", "timestamp_epoch_ms", "voltage_v", "current_a"]

class SMULogger:
    def __init__(self,
                 smu, # Type: SMU | None
                 data_request_interval: float = 1.0,
                 log_voltage: bool = True,
                 log_current: bool = True,
                 data_dir: str | None = None,
                 batch_size: int = 100,
                 batch_timeout: float = 0.5,
                 debug_log_dir: str | None = None,
                 debug_max_file_size_bytes: int = 5 * 1024 * 1024,
                 debug_backup_count: int = 5,
                 encoding: str = 'utf-8'):

        self.smu = smu
        self.data_request_interval = data_request_interval
        self.log_voltage = log_voltage
        self.log_current = log_current
        self.encoding = encoding
        
        # Determine initial safe port name
        if self.smu:
             self.safe_port = str(getattr(self.smu, 'port', 'unknown')).replace('/', '_').replace('\\', '_')
        else:
             self.safe_port = "unknown"

        if data_dir is None: self.data_dir = os.path.join(os.path.abspath('.'), "data")
        else: self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)

        if not debug_log_dir: debug_log_dir = os.path.join(os.path.abspath('.'), "logs")
        self._debug_log_path = os.path.join(debug_log_dir, 'smu_debug.log')
        os.makedirs(debug_log_dir, exist_ok=True)

        handler = RotatingFileHandler(
            self._debug_log_path,
            maxBytes=debug_max_file_size_bytes,
            backupCount=debug_backup_count,
            encoding=self.encoding
        )
        formatter = logging.Formatter('%(asctime)s - %(levelname)s\t- %(message)s')
        handler.setFormatter(formatter)

        self.debug_logger = logging.getLogger(f'smu.debug')
        self.debug_logger.propagate = False
        # Clean up existing handlers
        if self.debug_logger.hasHandlers():
            self.debug_logger.handlers.clear()
            
        self.debug_logger.addHandler(handler)
        self.debug_logger.setLevel(logging.DEBUG)

        # threads and control
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._stop_event = threading.Event()
        self._running_event = threading.Event()
        self._settings_lock = threading.Lock()

    def start_data_logging(self) -> bool:
        if self.smu is None:
            self.debug_logger.debug('No SMU selected, cannot start logging')
            return False
        
        self._stop_event.clear()
        
        if not self._poll_thread.is_alive():
            # Create new thread if old one died or hasn't started
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
            
        self._running_event.set()
        self.debug_logger.info('Data logging started')
        return True

    def stop_data_logging(self):
        self.debug_logger.info('Stopping data logging...')
        self._running_event.clear() # Pause logic
        self.debug_logger.info('Data logging paused/stopped')

    def shutdown(self):
        """Completely stop threads for application exit"""
        self._running_event.clear()
        self._stop_event.set()
        try:
            self._poll_thread.join(timeout=1)
        except Exception:
            pass

    def set_logging_parameters(self, smu = None, log_voltage: Optional[bool] = None, log_current: Optional[bool] = None, data_request_interval: Optional[float] = None):
        with self._settings_lock:
            if smu is not None:
                self.smu = smu
                # Update safe port for filename
                self.safe_port = str(getattr(self.smu, 'port', 'unknown')).replace('/', '_').replace('\\', '_')
            if log_voltage is not None:
                self.log_voltage = log_voltage
            if log_current is not None:
                self.log_current = log_current
            if data_request_interval is not None:
                self.data_request_interval = data_request_interval
        
        self.debug_logger.debug('Parameters updated. SMU: %s', "Attached" if self.smu else "None")

    def _poll_loop(self):
        file_header = None
        csv_writer = None
        current_date = None

        def close_current_file():
            nonlocal file_header
            if file_header:
                try:
                    file_header.flush()
                    file_header.close()
                except Exception:
                    pass
                file_header = None

        def open_todays_file():
            nonlocal current_date, file_header, csv_writer
            close_current_file()

            current_date = datetime.now(timezone.utc).date()
            self._ensure_header_for_date(current_date)
            file_name = self._current_filename_for_date(current_date)
            try:
                file_header = open(file_name, 'a', encoding=self.encoding, newline='')
                csv_writer = csv.DictWriter(file_header, fieldnames=CSV_HEADERS)
            except Exception as e:
                self.debug_logger.error(f"Failed to open log file {file_name}: {e}")
                file_header = None

        self.debug_logger.debug('Poller thread running')
        open_todays_file()

        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            
            # 1. Check if we should be logging
            if not self._running_event.is_set():
                time.sleep(0.2)
                continue
                
            # 2. Check date rotation
            if datetime.now(timezone.utc).date() != current_date:
                open_todays_file()

            # 3. Snapshot settings
            with self._settings_lock:
                current_smu = self.smu
                log_v = self.log_voltage
                log_c = self.log_current
                interval = self.data_request_interval

            if current_smu is None:
                time.sleep(0.5)
                continue

            # 4. Measure
            now = datetime.now(timezone.utc)
            row: Dict[str, Any] = {
                CSV_HEADERS[0]: now.isoformat(),
                CSV_HEADERS[1]: int(now.timestamp() * 1000),
                CSV_HEADERS[2]: '',
                CSV_HEADERS[3]: ''
            }
            
            valid_read = False
            try:
                # We check connected status first to avoid timeouts if known dead
                # but SMU methods also throw IOErrors if dead.
                if log_v:
                    row['voltage_v'] = current_smu.measure_voltage()
                if log_c:
                    row['current_a'] = current_smu.measure_current()
                valid_read = True
            except Exception:
                # If reading fails (disconnect), we just skip writing this row.
                # We do NOT reconnect here; the Main UI thread handles reconnection logic.
                # We just wait to be told to resume or for the SMU object to be swapped.
                pass

            # 5. Write if valid
            if valid_read and file_header and csv_writer:
                try:
                    csv_writer.writerow(row)
                    file_header.flush()
                except Exception:
                    pass

            # 6. Sleep remaining time
            elapsed = time.monotonic() - loop_start
            to_sleep = max(0.0, interval - elapsed)
            if self._stop_event.wait(to_sleep):
                break

        close_current_file()
        self.debug_logger.debug('Poller thread exiting')

    def _current_filename_for_date(self, d: date) -> str:
        # Uses self.safe_port which is updated in set_logging_parameters
        return os.path.join(self.data_dir, f"{self.safe_port}-{d.isoformat()}.csv")

    def _ensure_header_for_date(self, d: date):
        filename = self._current_filename_for_date(d)
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            if os.path.exists(filename) and os.path.getsize(filename) != 0: return
            with open(filename, 'a', encoding=self.encoding, newline='') as fh:
                writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS)
                writer.writeheader()
        except Exception:
            self.debug_logger.exception('Failed to ensure header for %s', filename)