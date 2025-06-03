'''Logs after printing hence, the logs are slower '''
import time
import ADS1263
import RPi.GPIO as GPIO

REF = 5.00          # Modify according to your actual reference voltage

TEST_ADC1 = True
TEST_ADC2 = False
TEST_ADC1_RATE = False
TEST_RTD = False     

try:
    ADC = ADS1263.ADS1263()
    
    if (ADC.ADS1263_init_ADC1('ADS1263_400SPS') == -1):
        exit()
    ADC.ADS1263_SetMode(0) # 0 is singleChannel, 1 is diffChannel

    if(TEST_ADC1):       # ADC1 Test
        channelList = [0]  # Only channel 0 (IN0)
        while True:
            ADC_Value = ADC.ADS1263_GetAll(channelList)    # get ADC1 value
            value = ADC_Value[0]
            if (value >> 31 == 1):
                            voltage = (REF*2 - value * REF / 0x80000000)
                print("ADC1 IN0 = -%lf" % voltage)
            else:
                voltage = value * REF / 0x7fffffff
                print("ADC1 IN0 = %lf" % voltage)   # 32bit
            time.sleep(0.5)  # Optional: slow down the print rate

    ADC.ADS1263_Exit()

except IOError as e:
    print(e)
   
except KeyboardInterrupt:
    print("ctrl + c:")
    print("Program end")
    ADC.ADS1263_Exit()
    exit()
