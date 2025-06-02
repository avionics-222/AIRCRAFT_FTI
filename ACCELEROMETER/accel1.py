'''USING QWIIC KX13X LIBRARY'''
'''Current Data Rate: 200Hz'''

import qwiic_kx13x
import time
import sys
import csv
from datetime import datetime
import os

def runExample():
    print("\nSparkFun KX13X Accelerometer Example 1 - CSV Logging\n")
    myKx = qwiic_kx13x.QwiicKX134()  # If using KX134
    # myKx = qwiic_kx13x.QwiicKX132()  # If using KX132

    if not myKx.connected:
        print("The Qwiic KX13X Accelerometer device isn't connected to the system. Please check your connection", file=sys.stderr)
        return

    if myKx.begin():
        print("Ready.")
    else:
        print("Make sure you're using the KX132 and not the KX134")

    if myKx.software_reset():
        print("Reset")

    
    myKx.enable_accel(False)
    myKx.set_output_data_rate(0x09)
    myKx.set_range(myKx.KX134_RANGE32G)  # If using the KX134
    # myKx.set_range(myKx.KX132_RANGE16G)
    myKx.enable_data_engine()
    myKx.enable_accel()
    loc_fil = input('Sensor Location')

    log_dir = "logs"  # No leading slash unless it's an absolute path
    os.makedirs(log_dir, exist_ok=True)  # Create directory if it doesn't exist

    filename = os.path.join(log_dir,str(loc_fil)+'_'+f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    try:
        with open(filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "X (g)", "Y (g)", "Z (g)"])

            print(f"Logging to {filename}...\nPress Ctrl+C to stop.")
            while True:
                if myKx.data_ready():
                    myKx.get_accel_data()
                    x = myKx.kx134_accel.x
                    y = myKx.kx134_accel.y
                    z = myKx.kx134_accel.z
                    timestamp = datetime.now().isoformat()
                    print(f"X: {x}g Y: {y}g Z: {z}g")
                    writer.writerow([timestamp, x, y, z])
                    time.sleep(0.003)  # Delay = 1 / ODR = 1/50Hz = 0.02s

    except KeyboardInterrupt:
        print("\nLogging stopped. File saved.")
    except Exception as e:
        print(f"Error occurred: {e}")
        sys.exit(1)

if __name__ == '__main__':
    runExample()
