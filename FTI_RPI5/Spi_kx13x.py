import spidev
import lgpio

class KX134_SPI:
    def __init__(self, bus=0, device=1, speed=100000, cs_pin=None):
        self.spi = spidev.SpiDev()
        self.cs_pin = cs_pin
        self.use_gpio_cs = cs_pin is not None

        if self.use_gpio_cs:
            self.gpio_handle = lgpio.gpiochip_open(0)
            if self.gpio_handle < 0:
                raise RuntimeError("Failed to open GPIO chip")
            err = lgpio.gpio_claim_output(self.gpio_handle, self.cs_pin, 1)  # Initial high
            if err < 0:
                raise RuntimeError(f"Failed to claim GPIO {self.cs_pin}")
            self.spi.open(bus, 1)
        else:
            self.spi.open(bus, device)

        self.spi.max_speed_hz = speed
        self.spi.mode = 0b00

    def _select(self):
        if self.use_gpio_cs:
            lgpio.gpio_write(self.gpio_handle, self.cs_pin, 0)

    def _deselect(self):
        if self.use_gpio_cs:
            lgpio.gpio_write(self.gpio_handle, self.cs_pin, 1)

    def write_register(self, reg, value):
        self._select()
        self.spi.xfer2([reg & 0x7F, value])
        self._deselect()

    def read_register(self, reg):
        self._select()
        response = self.spi.xfer2([reg | 0x80, 0x00])
        self._deselect()
        return response[1]

    def read_multiple(self, start_reg, length):
        self._select()
        response = self.spi.xfer2([start_reg | 0x80] + [0x00]*length)
        self._deselect()
        return response[1:]

    def enable_accel(self, enable=True):
        cntl1 = self.read_register(0x1B)
        if enable:
            cntl1 |= 0x80
        else:
            cntl1 &= ~0x80
        self.write_register(0x1B, cntl1)

    def get_accel_state(self):
        CNTL1 = 0x1B
        reg_val = self.read_register(CNTL1)
        return (reg_val & 0x80) >> 7

    def set_output_data_rate(self, rate):
        if rate < 0 or rate > 15:
            return False
        accel_state = self.get_accel_state()
        self.enable_accel(False)
        reg_val = self.read_register(0x21)
        reg_val &= 0xF0
        reg_val |= rate
        self.write_register(0x21, reg_val)
        self.enable_accel(accel_state)
        return True

    def set_range(self, range_setting):
        if range_setting < 0 or range_setting > 3:
            return
        accel_state = self.get_accel_state()
        self.enable_accel(False)
        cntl1 = self.read_register(0x1B)
        cntl1 &= ~0x18
        cntl1 |= (range_setting << 3)
        self.write_register(0x1B, cntl1)
        self.enable_accel(accel_state)
        sensitivities = [4096, 2048, 1024, 512]  # for 8,16,32,64g
        self.sensitivity = sensitivities[range_setting]

    def get_accel_data(self):
        raw = self.read_multiple(0x08, 6)
        x = self._convert_data(raw[1] << 8 | raw[0])
        y = self._convert_data(raw[3] << 8 | raw[2])
        z = self._convert_data(raw[5] << 8 | raw[4])
        return (x, y, z)

    def _convert_data(self, val):
        if val > 32767:
            val -= 65536
        return val / self.sensitivity

    def close(self):
        print(f"Closing SPI and GPIO for CS pin {self.cs_pin}")
        self.spi.close()
        if self.use_gpio_cs:
            lgpio.gpiochip_close(self.gpio_handle)