import time
import threading
import queue
import csv
import os
import sys
from datetime import datetime
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import Spi_kx13x

# Configuration constants
REF = 5.0
ACCEL_RATE = 0.01
STRAIN_RATE = 0.01
LOG_DIR = "sensor_logs"

# User-configurable sensor counts (change these to test fewer sensors)
NUM_ACCEL = 2  # Number of accelerometers to use (1-5)
NUM_STRAIN = 2  # Number of strain gauges to use (1-4)

# Full sensor configurations (max values)
MAX_ACCEL = 5
MAX_STRAIN = 4
ACCEL_LABELS_FULL = ["Accel1", "Accel2", "Accel3", "Accel4", "Accel5"]
STRAIN_LABEL_FULL = "Strain"
ACCEL_CS_PINS_FULL = [20, 21, 19, 12, 13]

# Validate input
if NUM_ACCEL < 1 or NUM_ACCEL > MAX_ACCEL:
    raise ValueError(f"NUM_ACCEL must be between 1 and {MAX_ACCEL}")
if NUM_STRAIN < 1 or NUM_STRAIN > MAX_STRAIN:
    raise ValueError(f"NUM_STRAIN must be between 1 and {MAX_STRAIN}")

# Dynamic sensor labels and pins based on NUM_ACCEL and NUM_STRAIN
ACCEL_LABELS = ACCEL_LABELS_FULL[:NUM_ACCEL]
STRAIN_LABEL = STRAIN_LABEL_FULL
ACCEL_CS_PINS = ACCEL_CS_PINS_FULL[:NUM_ACCEL]

# Dynamic CSV header based on sensor counts
CSV_HEADER = ["Timestamp"]
for i in range(NUM_ACCEL):
    CSV_HEADER.extend([
        f"{ACCEL_LABELS[i]}_X (g)", f"{ACCEL_LABELS[i]}_Y (g)", f"{ACCEL_LABELS[i]}_Z (g)"
    ])
for i in range(NUM_STRAIN):
    CSV_HEADER.append(f"Strain{i+1} (V)")

def accel_thread(data_queue, stop_event, spi_lock, sensor, accel_idx, label):
    try:
        print(f"Initializing KX134 accelerometer {accel_idx} on SPI bus 0, CS GPIO {ACCEL_CS_PINS[accel_idx-1]}...")
        with spi_lock:
            who_am_i = sensor.read_register(0x13)
        print(f"[{label}] WHO_AM_I = 0x{who_am_i:02X}")
        
        with spi_lock:
            sensor.enable_accel(False)
            sensor.set_output_data_rate(0x06)
            sensor.set_range(0x00)
            sensor.enable_accel(True)
        
        while not stop_event.is_set():
            with spi_lock:
                x, y, z = sensor.get_accel_data()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            data_queue.put((f"accel{accel_idx}", timestamp, x, y, z, None))
            time.sleep(ACCEL_RATE)
            
    except Exception as e:
        print(f"[{label}] Error: {e}")
        stop_event.set()

def strain_thread(data_queue, stop_event, i2c_lock, ads, channels, label="strain"):
    try:
        while not stop_event.is_set():
            voltages = []
            with i2c_lock:
                for i in range(NUM_STRAIN):
                    try:
                        voltage = channels[i].voltage
                        voltages.append(voltage)
                    except Exception as e:
                        print(f"[{label}] Error reading channel {i}: {e}")
                        voltages.append(None)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            data_queue.put(("strain", timestamp, None, None, None, voltages))
            time.sleep(STRAIN_RATE)
            
    except Exception as e:
        print(f"[{label}] Error: {e}")
        stop_event.set()

def csv_writer_thread(data_queue, filename, stop_event):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(CSV_HEADER)
            print(f"Logging to {filename}... Press Ctrl+C to stop.")
            
            last_data = {f"accel{i+1}": None for i in range(NUM_ACCEL)}
            last_data["strain"] = None
            last_print_time = time.time()
            
            while not stop_event.is_set():
                try:
                    sensor_type, timestamp, x, y, z, voltages = data_queue.get(timeout=0.01)
                    last_data[sensor_type] = (timestamp, x, y, z, voltages)
                    
                    if all(last_data[f"accel{i+1}"] for i in range(NUM_ACCEL)) and last_data["strain"]:
                        latest_timestamp = max(
                            *[data[0] for data in last_data.values()]
                        )
                        row = [latest_timestamp]
                        for i in range(NUM_ACCEL):
                            accel_data = last_data[f"accel{i+1}"]
                            row.extend([
                                accel_data[1] if accel_data[1] is not None else "",
                                accel_data[2] if accel_data[2] is not None else "",
                                accel_data[3] if accel_data[3] is not None else ""
                            ])
                        strain_data = last_data["strain"]
                        voltages = strain_data[4] if strain_data[4] is not None else ["" for _ in range(NUM_STRAIN)]
                        row.extend(voltages)
                        
                        writer.writerow(row)
                        
                        current_time = time.time()
                        if current_time - last_print_time >= 0.1:
                            print_str = f"[{latest_timestamp}] "
                            for i in range(NUM_ACCEL):
                                accel_data = last_data[f"accel{i+1}"]
                                x = accel_data[1] if accel_data[1] is not None else 0.0
                                y = accel_data[2] if accel_data[2] is not None else 0.0
                                z = accel_data[3] if accel_data[3] is not None else 0.0
                                print_str += f"{ACCEL_LABELS[i]}_X: {x:.3f} g | {ACCEL_LABELS[i]}_Y: {y:.3f} g | {ACCEL_LABELS[i]}_Z: {z:.3f} g | "
                            for i, v in enumerate(voltages):
                                v = v if v is not None else 0.0
                                print_str += f"Strain{i+1}: {v:.6f} V | "
                            print(print_str.rstrip(" | "))
                            last_print_time = current_time
                        
                except queue.Empty:
                    continue
                    
    except Exception as e:
        print(f"[CSV Writer] Error: {e}")
        stop_event.set()

def main():
    i2c = None
    sensors = []
    try:
        # Initialize I2C and ADS1115
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        ads.gain = 2/3
        channels = [
            AnalogIn(ads, ADS.P0),
            AnalogIn(ads, ADS.P1),
            AnalogIn(ads, ADS.P2),
            AnalogIn(ads, ADS.P3)
        ]
        
        # Create timestamped filename with dynamic labels
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(LOG_DIR, f"{'_'.join(ACCEL_LABELS)}_{STRAIN_LABEL}_log_{timestamp}.csv")
        
        # Create stop event, queue, locks
        stop_event = threading.Event()
        data_queue = queue.Queue()
        spi_lock = threading.Lock()
        i2c_lock = threading.Lock()
        
        # Create sensors based on NUM_ACCEL
        for i in range(NUM_ACCEL):
            cs_pin = ACCEL_CS_PINS[i]
            sensor = Spi_kx13x.KX134_SPI(bus=0, cs_pin=cs_pin)
            sensors.append(sensor)
        
        # Create threads based on NUM_ACCEL
        accel_threads = []
        for i in range(NUM_ACCEL):
            accel_t = threading.Thread(
                target=accel_thread,
                args=(data_queue, stop_event, spi_lock, sensors[i], i+1, ACCEL_LABELS[i]),
                daemon=True
            )
            accel_threads.append(accel_t)
        strain_t = threading.Thread(
            target=strain_thread,
            args=(data_queue, stop_event, i2c_lock, ads, channels, STRAIN_LABEL),
            daemon=True
        )
        writer_t = threading.Thread(
            target=csv_writer_thread,
            args=(data_queue, filename, stop_event),
            daemon=True
        )
        
        # Start threads
        for accel_t in accel_threads:
            accel_t.start()
        strain_t.start()
        writer_t.start()
        
        # Keep main thread alive
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping program...")
        stop_event.set()
        
        # Join threads with timeout
        for accel_t in accel_threads:
            accel_t.join(timeout=5.0)
        strain_t.join(timeout=5.0)
        writer_t.join(timeout=5.0)
        
        if any(accel_t.is_alive() for accel_t in accel_threads) or strain_t.is_alive() or writer_t.is_alive():
            print("Some threads did not exit cleanly; forcing shutdown.")
        
        print("Program terminated. Data saved to CSV.")
        
    except Exception as e:
        print(f"Main error: {e}")
        
    finally:
        if i2c:
            try:
                i2c.deinit()
            except:
                pass
        for sensor in sensors:
            sensor.close()
        sys.exit(0)

if __name__ == "__main__":
    main()