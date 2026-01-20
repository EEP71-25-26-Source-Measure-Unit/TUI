# Pico SMU Text-based User Interface

This repository contains the host-side control software for a custom Source Measure Unit (SMU), based on the Raspberry Pi Pico. The application provides a text-based user interface (TUI) for real-time monitoring, configuration, and data logging.

## Features

* **Text User Interface (TUI):** A lightweight, keyboard-driven interface built with `prompt_toolkit`.
* **Real-time Monitoring:** Displays voltage and current measurements with low latency.
* **Dynamic Connection:** Automatic port scanning, selection, and reconnection logic.
* **Safety Alerts:** Visual alerts for over-current trips and critical hardware disconnections.
* **Data Logging:** Capability to log measurement data to CSV.

## Installation

### Prerequisites

* Python 3.8 or higher
* A compatible SMU hardware device connected via USB

### Setup

1. **Clone the repository:**
```bash
git clone <repository_url>
cd <repository_name>

```


2. **Create a virtual environment (recommended):**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

```


3. **Install dependencies:**
The software requires `prompt_toolkit`, `pyserial` and `smulib`.
```bash
pip install requirements.txt

```


*Note: Ensure the `smulib` package (hardware driver) is present in your python path or project root.*

## Usage

### Running the Application

To start the main control dashboard:

```bash
python -m tui_app.main

```

**Optional Arguments:**

* `-p`, `--port`: Pre-select a specific COM port (e.g., `/dev/ttyACM0` or `COM3`) to bypass the selection screen.

### Interface Overview

The interface is divided into four sections:

1. **Status Bar:** Shows connection state and hardware status (e.g., Tripped/Active).
2. **Log Area:** Displays command history and system messages.
3. **Readout:** Shows real-time voltage and current measurements.
4. **Command Input:** Accepts user commands.

### Keyboard Shortcuts

* `Ctrl+C`: Safely disconnect and exit the application.

## Command Reference

Type the following commands into the input prompt to control the SMU:

| Command | Arguments | Description |
| --- | --- | --- |
| `vlimit` / `setv` | `[Voltage]` | Sets the voltage limit (e.g., `vlimit 5.0`). |
| `climit` | `[mA]` | Sets the current limit in milliamps (e.g., `climit 100`). |
| `output` | `on` / `off` | Enables or disables the power output. |
| `logdata` | `on` / `off` | Starts or stops logging measurement data to CSV. |
| `zero` | None | Performs a zero/tare operation on the measurements. |
| `mode?` | None | Queries and displays the current voltage and current limits. |
| `clear` / `cls` | None | Clears the log window. |
| `exit` / `quit` | None | Closes the application. |

## Architecture

* **`main.py`**: Entry point. Handles argument parsing and application lifecycle.
* **`main_window.py`**: Defines the TUI layout, rendering logic, and background update threads.
* **`state.py`**: Contains `AppState`, a thread-safe data structure holding shared system state.
* **`commands.py`**: processes text inputs and executes hardware logic.
* **`selector.py`**: Provides the interactive serial port selection menu.