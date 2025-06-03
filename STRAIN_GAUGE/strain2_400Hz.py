''' Almost No delay between the SPS and CSV Log '''
import time
import ADS1263
import RPi.GPIO as GPIO
import sys
import csv
from datetime import datetime
import os

REF = 5.00          

TEST_ADC1 = True
TEST_ADC2 = False
TEST_ADC1_RATE = False
TEST_RTD = False     

loc_fil = input('Sensor Location: ')

log_dir = "strain_logs"
os.makedirs(log_dir, exist_ok=True) 

filename = os.path.join(
    log_dir, f"{loc_fil}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
)

try:
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Timestamp", "Strain (V)"])

        print(f"Logging to {filename}...\nPress Ctrl+C to stop.")

        ADC = ADS1263.ADS1263()

        # Set to highest sample rate supported by your chip/hardware
        if (ADC.ADS1263_init_ADC1('ADS1263_400SPS') == -1):
            sys.exit()
        ADC.ADS1263_SetMode(0)  # 0 = singleChannel

        if TEST_ADC1:
            channelList = [0]  # Only channel 0 (IN0)
            counter = 0
            last_print = time.time()
            while True:
                ADC_Value = ADC.ADS1263_GetAll(channelList)
                value = ADC_Value[0]
                timestamp = datetime.now().isoformat()
                if (value >> 31 == 1):
                    voltage = (REF*2 - value * REF / 0x80000000)
                    voltage = -voltage
                else:
                    voltage = value * REF / 0x7fffffff

                writer.writerow([timestamp, voltage])
                counter += 1

                if time.time() - last_print >= 0.1:
                    print(f"Strain in Volts: {voltage:.6f}")
                    counter = 0
                    last_print = time.time()

            

        ADC.ADS1263_Exit()

except IOError as e:
    print(e)

except KeyboardInterrupt:
    print("ctrl + c:")
    print("Program end")
    try:
        ADC.ADS1263_Exit()
    except Exception:
        pass
    sys.exit()
