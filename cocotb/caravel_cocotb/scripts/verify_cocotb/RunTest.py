import os
import shutil
import subprocess
from caravel_cocotb.scripts.verify_cocotb.read_defines import GetDefines
import re
import logging
import caravel_cocotb
import hashlib


class RunTest:
    COMPILE_LOCK = set()

    def __init__(self, args, paths, test, logger) -> None:
        self.args = args
        self.paths = paths
        self.test = test
        self.logger = logger

    def run_test(self):
        if self.hex_generate() == "hex_generated":  # run test only if hex is generated
            self.runTest()
        if not self.args.compile_only:
            self.test.end_of_test()


    def hex_riscv_command_gen(self):
        # Use system PATH to find cross-compiler tools
        GCC_PREFIX = "riscv32-unknown-elf"
        GCC_COMPILE = GCC_PREFIX
        
        # Get additional firmware C files
        additional_c_files = self.get_firmware_c_files()
        additional_files_str = " ".join(additional_c_files) if additional_c_files else ""
        
        SOURCE_FILES = (
            f"{self.paths.FIRMWARE_PATH}/crt0_vex.S {self.paths.FIRMWARE_PATH}/isr.c {additional_files_str}"
        ).strip()

        LINKER_SCRIPT = f"-Wl,-Bstatic,-T,{self.test.linker_script_file},--strip-debug "
        CPUFLAGS = "-O2 -g -march=rv32i_zicsr -mabi=ilp32 -D__vexriscv__ -ffreestanding -nostdlib"
        # CPUFLAGS = "-O2 -g -march=rv32imc_zicsr -mabi=ilp32 -D__vexriscv__ -ffreestanding -nostdlib"
        includes = [
            f"-I{ip}" for ip in self.get_ips_fw()
        ] + [
            f"-I{self.paths.FIRMWARE_PATH}",
            f"-I{self.paths.FIRMWARE_PATH}/APIs",
            f"-I{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb",
            f"-I{self.paths.VERILOG_PATH}/dv/generated",
            f"-I{self.paths.VERILOG_PATH}/dv/",
            f"-I{self.paths.VERILOG_PATH}/common/",
        ]
        includes = f" -I{self.paths.FIRMWARE_PATH} -I{self.paths.FIRMWARE_PATH}/APIs -I{self.paths.VERILOG_PATH}/dv/generated  -I{self.paths.VERILOG_PATH}/dv/ -I{self.paths.VERILOG_PATH}/common"
        includes += f" -I{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb {' '.join([f'-I{ip}' for ip in self.get_ips_fw()])}"
        elf_command = (
            f"{GCC_COMPILE}-gcc  {includes} {CPUFLAGS} {LINKER_SCRIPT}"
            f" -o {self.hex_dir}/{self.test.name}.elf {SOURCE_FILES} {self.c_file}"
        )
        lst_command = f"{GCC_COMPILE}-objdump -d -S {self.hex_dir}/{self.test.name}.elf > {self.hex_dir}/{self.test.name}.lst "
        hex_command = f"{GCC_COMPILE}-objcopy -O verilog {self.hex_dir}/{self.test.name}.elf {self.hex_dir}/{self.test.name}.hex "
        sed_command = f'sed -ie "s/@10/@00/g" {self.hex_dir}/{self.test.name}.hex'
        return f" {elf_command} && {lst_command} && {hex_command} && {sed_command}"

    def hex_arm_command_gen(self):
        GCC_COMPILE = "arm-none-eabi"
        SOURCE_FILES = f"{self.paths.FIRMWARE_PATH}/cm0_start.s"
        LINKER_SCRIPT = f"-T {self.test.linker_script_file}"
        CPUFLAGS = "-O2 -Wall -nostdlib -nostartfiles -ffreestanding -mcpu=cortex-m0 -Wno-unused-value"
        includes = f"-I{self.paths.FIRMWARE_PATH} -I{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb"
        elf_command = (
            f"{GCC_COMPILE}-gcc  {includes} {CPUFLAGS} {LINKER_SCRIPT}"
            f" -o {self.hex_dir}/{self.test.name}.elf {SOURCE_FILES} {self.c_file}"
        )
        lst_command = f"{GCC_COMPILE}-objdump -d -S {self.hex_dir}/{self.test.name}.elf > {self.hex_dir}/{self.test.name}.lst "
        hex_command = f"{GCC_COMPILE}-objcopy -O verilog {self.hex_dir}/{self.test.name}.elf {self.hex_dir}/{self.test.name}.hex "
        sed_command = f'sed -ie "s/@10/@00/g" {self.hex_dir}/{self.test.name}.hex'
        return f" {elf_command} &&{lst_command}&& {hex_command}&& {sed_command}"

    def hex_generate(self) -> str:
        # get the test path from dv/cocotb
        test_path = self.test_path()
        # Create a new hex_files directory because it does not exist
        if not os.path.exists(f"{self.paths.SIM_PATH}/hex_files"):
            os.makedirs(f"{self.paths.SIM_PATH}/hex_files")
        self.hex_dir = f"{self.paths.SIM_PATH}/hex_files/"
        self.c_file = f"{test_path}/{self.test.name}.c"
        if self.args.cpu_type == "ARM":
            command = self.hex_arm_command_gen()
        else:
            command = self.hex_riscv_command_gen()

        # Run directly without Docker, assuming cross-compilation tools are installed
        if not self.check_cross_compile_tools():
            raise RuntimeError(
                f"{bcolors.FAIL}Error:{bcolors.ENDC} Cross-compilation tools not found. "
                f"Please install {'arm-none-eabi-gcc' if self.args.cpu_type == 'ARM' else 'riscv32-unknown-elf-gcc'}"
            )
        cmd = command
        hex_gen_state = self.run_command_write_to_file(
            cmd,
            self.test.hex_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )
        self.firmware_log = open(self.test.hex_log, "a")
        if hex_gen_state != 0:
            # open(self.test.firmware_log, "w").write(stdout)
            raise RuntimeError(
                f"{bcolors.FAIL}Error:{bcolors.ENDC} Fail to compile the C code for more info refer to {bcolors.OKCYAN }{self.test.hex_log}{bcolors.ENDC } "
            )
            self.firmware_log.write("Error: when generating hex")
            self.firmware_log.close()
            return "hex_error"
        self.firmware_log.write("Pass: hex generation")
        self.firmware_log.close()
        # move hex file to the test
        shutil.copyfile(
            f"{self.test.hex_dir}/{self.test.name}.hex",
            f"{self.test.test_dir}/firmware.hex",
        )
        return "hex_generated"

    def get_ips_fw(self, flag_type="-I"):
        fw_list = []
        if not os.path.exists(f"{self.paths.USER_PROJECT_ROOT}/ip"):
            return fw_list
        for file in os.listdir(f"{self.paths.USER_PROJECT_ROOT}/ip"):
            if os.path.isdir(f"{self.paths.USER_PROJECT_ROOT}/ip/{file}"):
                for f in os.listdir(f"{self.paths.USER_PROJECT_ROOT}/ip/{file}"):
                    if f == "fw":
                        fw_list.append(os.path.realpath(f"{self.paths.USER_PROJECT_ROOT}/ip/{file}/{f}"))
        # send it as string
        # ips_fw = f"{flag_type}" + f" {flag_type}".join(fw_list)
        return fw_list

    def get_firmware_c_files(self):
        """Find all firmware C files in the firmware path and IP directories"""
        c_files = []
        
        # Check main firmware path for C files (excluding isr.c as it's already included)
        if hasattr(self.paths, 'FIRMWARE_PATH') and os.path.exists(self.paths.FIRMWARE_PATH):
            for file in os.listdir(self.paths.FIRMWARE_PATH):
                if file.endswith('.c') and file != 'isr.c':
                    c_files.append(os.path.join(self.paths.FIRMWARE_PATH, file))
        
        # Check firmware APIs directory
        if hasattr(self.paths, 'FIRMWARE_PATH'):
            apis_path = os.path.join(self.paths.FIRMWARE_PATH, 'APIs')
            if os.path.exists(apis_path):
                for file in os.listdir(apis_path):
                    if file.endswith('.c'):
                        c_files.append(os.path.join(apis_path, file))
        
        # Check IP firmware directories
        if hasattr(self.paths, 'USER_PROJECT_ROOT') and os.path.exists(f"{self.paths.USER_PROJECT_ROOT}/ip"):
            for ip_dir in os.listdir(f"{self.paths.USER_PROJECT_ROOT}/ip"):
                ip_path = f"{self.paths.USER_PROJECT_ROOT}/ip/{ip_dir}"
                if os.path.isdir(ip_path):
                    fw_path = os.path.join(ip_path, "fw")
                    if os.path.exists(fw_path):
                        for file in os.listdir(fw_path):
                            if file.endswith('.c'):
                                c_files.append(os.path.join(fw_path, file))
        
        return c_files

    def test_path(self, test_name=None):
        if test_name is None:
            test_name = self.test.name
        c_file_name = test_name + ".c"
        tests_path_user = os.path.abspath(
            f"{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb"
        )
        test_file = self.find(c_file_name, tests_path_user)
        test_path = os.path.dirname(test_file)
        return test_path

    def runTest(self):
        os.environ["COCOTB_RESULTS_FILE"] = f"{self.test.test_dir}/seed.xml"
        if self.args.iverilog:
            self.runTest_iverilog()
        elif self.args.vcs:
            self.runTest_vcs()
        # elif self.args.verilator:
        # self.runTest_verilator()

    # iverilog function
    def runTest_iverilog(self):
        if self.test.sim == "GL_SDF":
            raise RuntimeError(
                f"{bcolors.FAIL}iverilog can't run SDF for test {self.test.name} Please use anothor simulator like cvc{bcolors.ENDC}"
            )
            return
        self.write_iverilog_includes_file()
        if not os.path.isfile(f"{self.test.compilation_dir}/sim.vvp"):
            print(f"{bcolors.OKCYAN}Compiling as sim.vvp not found{bcolors.ENDC}")
            self.iverilog_compile()
            self.write_hash(self.test.netlist)
        elif self.args.compile:
            print(f"{bcolors.OKCYAN}Compiling as compile flag is set{bcolors.ENDC}")
            self.iverilog_compile()
            self.write_hash(self.test.netlist)
        elif not self.is_same_hash(self.test.netlist) and f"{self.test.compilation_dir}/sim.vvp" not in RunTest.COMPILE_LOCK:
            print(f"{bcolors.OKCYAN}Compiling since netlist has changed{bcolors.ENDC}")
            self.iverilog_compile()
        else:
            if f"{self.test.compilation_dir}/sim.vvp" not in RunTest.COMPILE_LOCK:
                print(f"{bcolors.OKGREEN}Skipping compilation as netlist has not changed{bcolors.ENDC}")
        RunTest.COMPILE_LOCK.add(f"{self.test.compilation_dir}/sim.vvp")  # locked means if it is copiled for the first time then it will not be compiled again even if netlist changes
        if not self.args.compile_only:
            self.iverilog_run()

    def write_iverilog_includes_file(self):
        self.iverilog_dirs = " "
        self.iverilog_dirs += f"-I {self.paths.USER_PROJECT_ROOT}/verilog/rtl"
        self.test.set_user_project()
        for include_dir in self.test.include_dirs:
            self.iverilog_dirs += f" -I {include_dir}"

    def iverilog_compile(self):
        if os.path.isfile(f"{self.test.compilation_dir}/sim.vvp"):
            os.remove(f"{self.test.compilation_dir}/sim.vvp")
        macros = " -D" + " -D".join(self.test.macros)
        compile_command = (
            f"cd {self.test.compilation_dir} &&"
            f"iverilog -g2012 -Ttyp {macros} {self.iverilog_dirs} -o {self.test.compilation_dir}/sim.vvp -s caravel_top"
            f" {self.paths.CARAVEL_VERILOG_PATH}/rtl/toplevel_cocotb.v"
        )
        # Set up environment variables for direct execution
        self.setup_environment_vars()
        # Use direct command since Docker is not required
        self.run_command_write_to_file(
            compile_command,
            self.test.compilation_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )

    def iverilog_run(self):
        defines = GetDefines(self.test.includes_file)
        seed = "" if self.args.seed is None else f"RANDOM_SEED={self.args.seed}"
        run_command = f"cd {self.test.test_dir} && TESTCASE={self.test.name} MODULE=module_trail {seed} vvp -M $(cocotb-config --prefix)/cocotb/libs -m libcocotbvpi_icarus {self.test.compilation_dir}/sim.vvp +{ ' +'.join(self.test.macros) } {' '.join([f'+{k}={v}' if v != ''else f'+{k}' for k, v in defines.defines.items()])}"
        # Set up environment variables for direct execution  
        self.setup_environment_vars()
        # Use direct command since Docker is not required
        self.run_command_write_to_file(
            run_command,
            None if self.args.verbosity == "quiet" else self.test.test_log2,
            self.logger,
            quiet=True if self.args.verbosity == "quiet" else False,
        )


    def find_symbolic_links(self, directory):
        sym_links = []
        for root, dirs, files in os.walk(directory):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                if os.path.islink(dir_path):
                    sym_links.append(dir_path)
        return sym_links

    # vcs function
    def runTest_vcs(self):
        self.write_vcs_includes_file()
        self.vcs_coverage_command = ""
        if self.test.sim == "RTL":
            self.vcs_coverage_command = "-cm line+tgl+cond+fsm+branch+assert "
        os.environ["TESTCASE"] = f"{self.test.name}"
        os.environ["MODULE"] = "module_trail"
        if not os.path.isfile(f"{self.test.compilation_dir}/simv"):
            print(f"{bcolors.OKCYAN}Compiling as simv not found{bcolors.ENDC}")
            self.vcs_compile()
            self.write_hash(self.test.netlist)
        elif self.args.compile:
            print(f"{bcolors.OKCYAN}Compiling as compile flag is set{bcolors.ENDC}")
            self.vcs_compile()
            self.write_hash(self.test.netlist)
        elif not self.is_same_hash(self.test.netlist) and f"{self.test.compilation_dir}/simv" not in RunTest.COMPILE_LOCK:
            print(f"{bcolors.OKCYAN}Compiling since netlist has has changed{bcolors.ENDC}")
            self.vcs_compile()
        else:
            if f"{self.test.compilation_dir}/simv" not in RunTest.COMPILE_LOCK:
                print(f"{bcolors.OKCYAN}Skipping compilation as netlist has not changed{bcolors.ENDC}")
        RunTest.COMPILE_LOCK.add(f"{self.test.compilation_dir}/simv")  # locked means if it is copiled for the first time then it will not be compiled again even if netlist changes
        if not self.args.compile_only:
            self.vcs_run()

    def write_vcs_includes_file(self):
        # self.vcs_dirs = f'+incdir+\\"{self.paths.PDK_ROOT}/{self.paths.PDK}\\" '
        self.vcs_dirs = " "
        if self.test.sim == "RTL":
            self.vcs_dirs += (
                f'+incdir+\\"{self.paths.USER_PROJECT_ROOT}/verilog/rtl\\" '
            )
        self.test.set_user_project()

    def vcs_compile(self):
        if os.path.isfile(f"{self.test.compilation_dir}/simv"):
            os.remove(f"{self.test.compilation_dir}/simv")
        macros = " +define+" + " +define+".join(self.test.macros)
        vlogan_cmd = f"cd {self.test.compilation_dir}; vlogan -full64 -sverilog +error+30 {self.paths.CARAVEL_VERILOG_PATH}/rtl/toplevel_cocotb.v {self.vcs_dirs}  {macros}   -l {self.test.compilation_dir}/analysis.log -o {self.test.compilation_dir} "
        self.run_command_write_to_file(
            vlogan_cmd,
            self.test.compilation_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )
        lint = "+lint=all" if self.args.lint else ""
        ignored_errors = " -error=noZMMCM "
        vcs_cmd = f"cd {self.test.compilation_dir};  vcs {lint} -negdelay {self.vcs_coverage_command} {ignored_errors} -debug_access+all +error+50 +vcs+loopreport+1000000 -diag=sdf:verbose +sdfverbose +neg_tchk -full64  -l {self.test.compilation_dir}/test_compilation.log  caravel_top -Mdir={self.test.compilation_dir}/csrc -o {self.test.compilation_dir}/simv +vpi -P pli.tab -load $(cocotb-config --lib-name-path vpi vcs)"
        self.run_command_write_to_file(
            vcs_cmd,
            self.test.compilation_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )

    def vcs_run(self):
        defines = GetDefines(self.test.includes_file)
        if self.args.seed is not None:
            os.environ["RANDOM_SEED"] = self.args.seed
        run_sim = f"cd {self.test.test_dir}; {self.test.compilation_dir}/simv +vcs+dumpvars+all {self.vcs_coverage_command} -cm_name {self.test.name} +{ ' +'.join(self.test.macros)} {' '.join([f'+{k}={v}' if v != ''else f'+{k}' for k, v in defines.defines.items()])}"
        self.run_command_write_to_file(
            run_sim,
            None if self.args.verbosity == "quiet" else self.test.test_log2,
            self.logger,
            quiet=True if self.args.verbosity == "quiet" else False,
        )

    def find(self, name, path):
        for root, dirs, files in os.walk(path):
            if name in files:
                return os.path.join(root, name)
        raise RuntimeError(f"Test {name} doesn't exist or don't have a C file ")

    def run_command_write_to_file(self, cmd, file, logger, quiet=True):
        """run command and write output to file return 0 if no error"""
        if file is not None:
            logger_file = logging.getLogger(file)
            logger_file.setLevel(logging.INFO)
            # Configure file handler for the logger
            file_handler = logging.FileHandler(file)
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter("%(message)s")
            file_handler.setFormatter(file_formatter)
            logger_file.addHandler(file_handler)
            f = open(file, "a")
            f.write("command:")
            f.write(os.path.expandvars(cmd) + "\n\n")
            f.close()
        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1024,
            )
            while True:
                out = process.stdout.readline().decode("utf-8")
                ansi_escape = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
                stdout = ansi_escape.sub("", out)
                if process.poll() is not None:
                    break
                if out:
                    if not quiet:
                        logger.info(stdout.replace("\n", "", 1))
                        # time.sleep(0.01)
                    if file is not None:
                        logger_file.info(stdout.replace("\n", "", 1))
        except Exception as e:
            logger(f"Process stopped by user {e}")
            process.stdin.write(b"\x03")  # Send the Ctrl+C signal to the process
            process.terminate()

        return process.returncode

    @staticmethod
    def calculate_netlist_hash(netlist, hash_algorithm="sha256"):
        """Calculate a combined hash of multiple files ignoring the order."""
        hash_func = getattr(hashlib, hash_algorithm)()
        try:
            for file_path in sorted(netlist):  # Ensure consistent order
                with open(file_path, "rb") as f:
                    while chunk := f.read(8192):
                        hash_func.update(chunk)
            return hash_func.hexdigest()
        except FileNotFoundError as e:
            return f"File not found: {e.filename}"
        except PermissionError as e:
            return f"Permission denied: {e.filename}"

    def is_same_hash(self, netlist):
        # read old hash if exists
        try:
            with open(self.test.hash_log, "r") as f:
                old_hash = f.read().strip()
        except FileNotFoundError:
            old_hash = 0
        # calculate new hash
        new_hash = self.write_hash(netlist)
        return new_hash == old_hash

    def write_hash(self, netlist):
        new_hash = self.calculate_netlist_hash(netlist)
        with open(self.test.hash_log, "w") as f:
            f.write(new_hash)
        return new_hash

    def check_cross_compile_tools(self):
        """Check if required cross-compilation tools are available"""
        if self.args.cpu_type == "ARM":
            tool = "arm-none-eabi-gcc"
        else:
            tool = "riscv32-unknown-elf-gcc"
        
        try:
            result = subprocess.run([tool, "--version"], 
                                  capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def setup_environment_vars(self):
        """Set up environment variables needed for compilation and simulation"""
        if hasattr(self.paths, 'CARAVEL_PATH'):
            os.environ['CARAVEL_PATH'] = self.paths.CARAVEL_PATH
        if hasattr(self.paths, 'CARAVEL_VERILOG_PATH'):
            os.environ['CARAVEL_VERILOG_PATH'] = self.paths.CARAVEL_VERILOG_PATH
        if hasattr(self.paths, 'VERILOG_PATH'):
            os.environ['VERILOG_PATH'] = self.paths.VERILOG_PATH
        if hasattr(self.paths, 'PDK_ROOT'):
            os.environ['PDK_ROOT'] = self.paths.PDK_ROOT
        if hasattr(self.paths, 'PDK'):
            os.environ['PDK'] = self.paths.PDK
        if hasattr(self.paths, 'USER_PROJECT_ROOT'):
            os.environ['USER_PROJECT_VERILOG'] = f"{self.paths.USER_PROJECT_ROOT}/verilog"
        
        # Set COCOTB_RESULTS_FILE if not already set
        if 'COCOTB_RESULTS_FILE' not in os.environ:
            os.environ['COCOTB_RESULTS_FILE'] = f"{self.test.test_dir}/results.xml"

class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def change_str(str, new_str, file_path):
    # Read in the file
    with open(file_path, "r") as file:
        filedata = file.read()

    filedata = filedata.replace(str, new_str)

    # Write the file out again
    with open(file_path, "w") as file:
        file.write(filedata)
