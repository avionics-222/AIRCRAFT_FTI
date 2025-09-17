import time
import csv
import multiprocessing
import queue
import os
import sys
from datetime import datetime
import logging
from pymodbus.client import ModbusSerialClient
import traceback

# ---- Config ----
RS485_PORT = '/dev/ttyAMA0'
BAUD_RATE = 9600
LOG_DIR = "FTI_logs"
SENSOR_LABELS = ["Temp8", "Temp6", "Temp9", "Temp10"]  # Custom labels for each PT100 sensor
temperatures_offsets = [0.0, 0.0, 0.0, 0.0]  # Calibration offsets for each sensor; adjust as needed

# ---- Logging ----
logging.basicConfig(level=logging.ERROR)
logging.getLogger("pymodbus").setLevel(logging.ERROR)
logging.getLogger("pymodbus.logging").setLevel(logging.ERROR)
logging.getLogger("serial").setLevel(logging.ERROR)

# ---- RS485 Temp process ----
def rs485_temp_process(data_queue, stop_event):
    client = None
    try:
        client = ModbusSerialClient(
            port=RS485_PORT, baudrate=BAUD_RATE,
            parity='N', stopbits=1, bytesize=8, timeout=3
        )
        if not client.connect():
            print("Could not connect to RS485")
            return
        while not stop_event.is_set():
            temps = []
            for idx, dev_id in enumerate([1, 2, 3, 4]):
                if hasattr(client, "socket") and hasattr(client.socket, "reset_input_buffer"):
                    try:
                        client.socket.reset_input_buffer()
                    except:
                        pass
                rr = client.read_holding_registers(address=0, count=1, device_id=dev_id)
                temp = 0.0
                if not rr.isError():
                    raw = rr.registers[0]
                    temp = (raw - 65536)/10 if (raw & 0x8000) else raw/10
                temps.append(temp)
                time.sleep(0.3)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            data_queue.put((timestamp, temps))
            time.sleep(0.5)
    except Exception as e:
        print(f"RS485 temp process error: {e}")
        traceback.print_exc()
    finally:
        if client:
            client.close()

# ---- CSV Writer process ----
def csv_writer_process(data_queue, filename, stop_event):
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp"] + [f"{label}_C" for label in SENSOR_LABELS])
            print(f"Logging to {filename}... Press Ctrl+C to stop.")
            
            last_print_time = time.time()
            
            while not stop_event.is_set():
                try:
                    timestamp, temps = data_queue.get(timeout=0.5)
                    adjusted_temps = [temps[i] - temperatures_offsets[i] for i in range(4)]
                    writer.writerow([timestamp] + adjusted_temps)
                    file.flush()
                    
                    current_time = time.time()
                    if current_time - last_print_time >= 1.0:
                        print_str = f"[{timestamp}] "
                        for i, label in enumerate(SENSOR_LABELS):
                            print_str += f"{label}: {adjusted_temps[i]:.2f} °C | "
                        print(print_str.rstrip(" | "))
                        last_print_time = current_time
                        
                except queue.Empty:
                    continue
                    
    except Exception as e:
        print(f"[CSV Writer] Error: {e}")
        traceback.print_exc()
        stop_event.set()

# ---- Main ----
def main():
    try:
        timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(LOG_DIR, f"pt100_log_{timestamp_suffix}.csv")

        stop_event = multiprocessing.Event()
        data_queue = multiprocessing.Queue()
        
        temp_p = multiprocessing.Process(
            target=rs485_temp_process,
            args=(data_queue, stop_event),
            daemon=True
        )
        writer_p = multiprocessing.Process(
            target=csv_writer_process,
            args=(data_queue, filename, stop_event),
            daemon=True
        )
        
        temp_p.start()
        writer_p.start()
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping program...")
        stop_event.set()
        
        temp_p.join(timeout=5.0)
        writer_p.join(timeout=5.0)
        
        if temp_p.is_alive() or writer_p.is_alive():
            print("Some processes did not exit cleanly; forcing shutdown.")
            temp_p.terminate()
            writer_p.terminate()
        
        print("Program terminated. Data saved to CSV.")
        
    except Exception as e:
        print(f"Main error: {e}")
        traceback.print_exc()
        
    finally:
        sys.exit(0)

if __name__ == "__main__":
    main()
