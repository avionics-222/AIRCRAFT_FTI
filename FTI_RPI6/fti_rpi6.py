import time
import csv
import threading
import queue
import os
from datetime import datetime
import logging
from pymodbus.client import ModbusSerialClient
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from gpiozero import Button
import traceback

# ---- Config ----
RS485_PORT = '/dev/ttyAMA0'
BAUD_RATE = 9600
REF = 3.3
FLOW_SENSOR_PINS = [23, 24]
FLOW_FACTORS = [9.9, 9.89]
DEV_IDS = [1, 2, 3, 4]

pulse_counts = [0, 0]
off_t = [0.0, 0.0, 0.0, 0.0]

LOG_DIR = "logs"
CSV_HEADER = [
    "Timestamp",
    "Pressure1_Bar", "Pressure2_Bar", "Pressure3_Bar", "Pressure4_Bar",
    "Flow1_Lpm", "Flow2_Lpm",
    "Temp1_C", "Temp2_C", "Temp3_C", "Temp4_C"
]

# ---- Logging ----
logging.basicConfig(level=logging.ERROR)
logging.getLogger("pymodbus").setLevel(logging.ERROR)
logging.getLogger("pymodbus.logging").setLevel(logging.ERROR)
logging.getLogger("serial").setLevel(logging.ERROR)

# ---- Locks ----
modbus_lock = threading.Lock()
i2c_lock = threading.Lock()
flow_lock = threading.Lock()

# ---- Flow sensor ----
def pulse_inc_0():
    with flow_lock:
        pulse_counts[0] += 1

def pulse_inc_1():
    with flow_lock:
        pulse_counts[1] += 1

flow_sensors = [
    Button(FLOW_SENSOR_PINS[0], pull_up=True),
    Button(FLOW_SENSOR_PINS[1], pull_up=True)
]
flow_sensors[0].when_pressed = pulse_inc_0
flow_sensors[1].when_pressed = pulse_inc_1

def calc_flow(pulse_count, factor):
    return round(pulse_count / factor, 2)

# ---- Threads ----
def flow_thread(data_queue, stop_event, flow_lock):
    try:
        while not stop_event.is_set():
            time.sleep(1)
            with flow_lock:
                flow_rates = [calc_flow(pulse_counts[i], FLOW_FACTORS[i]) for i in range(2)]
                pulse_counts[0] = 0
                pulse_counts[1] = 0
            ts = datetime.now()
            data_queue.put(("flow", ts, flow_rates))
    except Exception as e:
        print(f"Flow thread error: {e}")
        traceback.print_exc()
        stop_event.set()

def pressure_thread(data_queue, stop_event, i2c_lock, ads, channels):
    try:
        while not stop_event.is_set():
            pressures = []
            with i2c_lock:
                for i in range(4):
                    try:
                        voltage = channels[i].voltage
                        if voltage < 0.5:
                            psi = 0.0
                        elif voltage > (REF - 0.8):
                            psi = 100.0
                        else:
                            psi = ((voltage - 0.5) / (REF - 0.5)) * 100.0
                        bar = psi * 0.0689
                        bar = 0 if (0.82 * bar - 0.017) < 0 else (0.82 * bar - 0.017)
                        pressures.append(bar)
                    except Exception as e:
                        print(f"Error reading channel {i}: {e}")
                        pressures.append(-1.0)
                    time.sleep(0.1)
            ts = datetime.now()
            data_queue.put(("pressure", ts, pressures))
            time.sleep(0.5)
    except Exception as e:
        print(f"Pressure thread error: {e}")
        traceback.print_exc()
        stop_event.set()

def rs485_temp_thread(data_queue, stop_event, modbus_lock):
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
            temperatures = []
            for dev_id in DEV_IDS:
                with modbus_lock:
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
                    temperatures.append(temp)
                time.sleep(0.3)
            ts = datetime.now()
            data_queue.put(("temp", ts, temperatures))
            time.sleep(0.5)
    except Exception as e:
        print(f"RS485 temp thread error: {e}")
        traceback.print_exc()
        stop_event.set()
    finally:
        if client:
            client.close()

def csv_writer_thread(data_queue, filename, stop_event):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(CSV_HEADER)
            print(f"Logging to {filename}... Press Ctrl+C to stop.")
            
            last_data = {"pressure": None, "flow": None, "temp": None}
            last_print_time = time.time()
            print_interval = 0.1  # Follow reference code's 10Hz print rate
            
            while not stop_event.is_set():
                try:
                    sensor_type, ts, values = data_queue.get(timeout=0.01)
                    last_data[sensor_type] = (ts, values)
                    
                    if all(last_data[k] for k in last_data):
                        latest_ts = max(data[0] for data in last_data.values())
                        p = last_data["pressure"][1]
                        f = last_data["flow"][1]
                        t_raw = last_data["temp"][1]
                        t = [t_raw[i] - off_t[i] for i in range(4)]
                        
                        ts_str = latest_ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                        row = [ts_str] + p + f + t
                        writer.writerow(row)
                        
                        current_time = time.time()
                        if current_time - last_print_time >= print_interval:
                            print_str = f"[{ts_str}] "
                            for i, v in enumerate(p, 1):
                                print_str += f"Pressure{i}: {v:.3f} Bar | "
                            for i, v in enumerate(f, 1):
                                print_str += f"Flow{i}: {v:.2f} Lpm | "
                            for i, v in enumerate(t, 1):
                                print_str += f"Temp{i}: {v:.2f} °C | "
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
    i2c = None
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        ads.gain = 1
        channels = [
            AnalogIn(ads, ADS.P0),
            AnalogIn(ads, ADS.P1),
            AnalogIn(ads, ADS.P2),
            AnalogIn(ads, ADS.P3)
        ]

        timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(LOG_DIR, f"sensor_log_{timestamp_suffix}.csv")

        stop_event = threading.Event()
        data_queue = queue.Queue()

        pressure_t = threading.Thread(target=pressure_thread, args=(data_queue, stop_event, i2c_lock, ads, channels), daemon=True)
        flow_t = threading.Thread(target=flow_thread, args=(data_queue, stop_event, flow_lock), daemon=True)
        temp_t = threading.Thread(target=rs485_temp_thread, args=(data_queue, stop_event, modbus_lock), daemon=True)
        writer_t = threading.Thread(target=csv_writer_thread, args=(data_queue, filename, stop_event), daemon=True)

        pressure_t.start()
        flow_t.start()
        temp_t.start()
        writer_t.start()

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping program...")
        stop_event.set()
        
        pressure_t.join(timeout=5.0)
        flow_t.join(timeout=5.0)
        temp_t.join(timeout=5.0)
        writer_t.join(timeout=5.0)
        
        if pressure_t.is_alive() or flow_t.is_alive() or temp_t.is_alive() or writer_t.is_alive():
            print("Some threads did not exit cleanly; forcing shutdown.")
        
        print("Program terminated. Data saved to CSV.")
        
    except Exception as e:
        print(f"Main error: {e}")
        traceback.print_exc()
        
    finally:
        if i2c:
            try:
                i2c.deinit()
            except:
                pass

if __name__ == "__main__":
    main()
