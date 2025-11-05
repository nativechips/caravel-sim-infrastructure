import cocotb
from cocotb.triggers import Timer, FallingEdge, NextTimeStep, RisingEdge, ReadOnly
from caravel_cocotb.interfaces.caravel import Caravel_env

class VirtualGPIOModel:
    def __init__(self, caravel):
        self.caravel = caravel
        self.dut = caravel.dut
        self.clk = caravel.clk
        self.gpio_output = 0x0000
        self.gpio_input = 0x0000
        self.gpio_address = 0x30FFFFFC
        self.monitor_task = None
        self.dut._log.info(f"VirtualGPIOModel initialized with address: 0x{self.gpio_address:08x}")
        self.dut._log.info(f"  Bits [15:0]  = OUTPUT from Caravel (CPU writes)")
        self.dut._log.info(f"  Bits [31:16] = INPUT to Caravel (CPU reads)")

    async def start_monitoring(self):
        self.dut._log.info("Starting Wishbone interface monitoring...")

        while True:
            await RisingEdge(self.clk)
            await ReadOnly()

            try:
                cyc = self.dut.uut.chip_core.mprj.wbs_cyc_i.value.integer
                stb = self.dut.uut.chip_core.mprj.wbs_stb_i.value.integer
                we = self.dut.uut.chip_core.mprj.wbs_we_i.value.integer
                adr = self.dut.uut.chip_core.mprj.wbs_adr_i.value.integer
            except ValueError:
                continue

            valid = cyc and stb

            if valid and adr == self.gpio_address:
                if we:
                    try:
                        bin_str = self.dut.uut.chip_core.mprj.wbs_dat_i.value.binstr
                        if bin_str and len(bin_str) >= 16:
                            dat_i = int(bin_str[-16:], 2)
                        else:
                            continue
                    except (ValueError, TypeError, AttributeError):
                        self.dut._log.warning(f"[GPIO MODEL] invalid data {self.dut.uut.chip_core.mprj.wbs_dat_i.value} to write to")
                        continue
                    self.gpio_output = dat_i & 0xFFFF
                    self.dut._log.info(f"[GPIO MODEL] Write OUTPUT[15:0]: 0x{self.gpio_output:04x}")
                else:
                    self.dut._log.info(f"[GPIO MODEL] Read: OUTPUT[15:0]=0x{self.gpio_output:04x}, INPUT[31:16]=0x{self.gpio_input:04x}")

                await RisingEdge(self.clk)
                self.dut.uut.chip_core.mprj.wbs_ack_o.value = 1

                if not we:
                    read_data = (self.gpio_input << 16) | self.gpio_output
                    self.dut.uut.chip_core.mprj.wbs_dat_o.value = read_data

                await RisingEdge(self.clk)
                self.dut.uut.chip_core.mprj.wbs_ack_o.value = 0
                self.dut.uut.chip_core.mprj.wbs_dat_o.value = 0

    def start(self):
        self.monitor_task = cocotb.start_soon(self.start_monitoring())

    def get_output(self):
        return self.gpio_output

    async def wait_output(self, val):
        while True:
            if (val & 0xFFFF) == self.get_output():
                break
            await RisingEdge(self.clk)

    def set_input(self, value):
        self.gpio_input = value & 0xFFFF
        self.dut._log.info(f"[GPIO MODEL] Testbench set INPUT[31:16] to: 0x{self.gpio_input:04x}")