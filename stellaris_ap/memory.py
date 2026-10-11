"""Reads and writes script variables in the memory of the running game.

A script variable is stored as its name followed by its value:

    16 bytes  the name, zero terminated (names of up to 15 characters are stored in place)
     8 bytes  length of the name
     8 bytes  capacity of the name, 15
     8 bytes  the value times 100000

Found with Stellaris 4.5.2. The name is what the variable is searched by.
"""
import ctypes
import struct
import subprocess
from ctypes import wintypes

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
STILL_ACTIVE = 259
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_READWRITE = 0x04
CREATE_NO_WINDOW = 0x08000000

SCALE = 100000
NAME_CAPACITY = 15
VALUE_OFFSET = 32
CHUNK = 32 * 1024 * 1024


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def stellaris_pid() -> int | None:
    output = subprocess.run(["tasklist", "/FI", "IMAGENAME eq stellaris.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, creationflags=CREATE_NO_WINDOW).stdout
    # Without a match tasklist prints a message in the language of Windows, in the console's encoding
    output = output.decode("oem", errors="replace")
    for line in output.splitlines():
        parts = line.split('","')
        if len(parts) > 1 and parts[0].strip('"').lower() == "stellaris.exe":
            return int(parts[1])
    return None


def variable_header(name: str) -> bytes:
    """The bytes in front of the value of a variable with this name, apart from unused bytes of the name."""
    encoded = name.encode("ascii")
    if len(encoded) > NAME_CAPACITY:
        raise ValueError(f"variable name {name} is longer than {NAME_CAPACITY} characters")
    return encoded + b"\0"


class GameMemory:
    def __init__(self, process):
        self.process = process

    @classmethod
    def attach(cls) -> "GameMemory | None":
        pid = stellaris_pid()
        if pid is None:
            return None
        access = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        process = kernel32.OpenProcess(access, False, pid)
        return cls(process) if process else None

    def close(self) -> None:
        kernel32.CloseHandle(self.process)

    def alive(self) -> bool:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(self.process, ctypes.byref(code))) and code.value == STILL_ACTIVE

    def read(self, address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        done = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.process, address, buffer, size, ctypes.byref(done)):
            return b""
        return buffer.raw[:done.value]

    def heap_regions(self):
        address = 0
        info = MEMORY_BASIC_INFORMATION()
        while kernel32.VirtualQueryEx(self.process, address, ctypes.byref(info), ctypes.sizeof(info)):
            if info.State == MEM_COMMIT and info.Type == MEM_PRIVATE and info.Protect == PAGE_READWRITE:
                yield info.BaseAddress, info.RegionSize
            address = (info.BaseAddress or 0) + info.RegionSize

    def find_variable(self, name: str) -> list[int]:
        """The addresses of the value of every variable with this name, copies no longer in use included."""
        pattern = variable_header(name)
        found = []
        for base, size in self.heap_regions():
            for offset in range(0, size, CHUNK):
                # Overlap between chunks, but never past the end of the region: that makes the read fail
                data = self.read(base + offset, min(CHUNK + VALUE_OFFSET + 8, size - offset))
                position = data.find(pattern)
                while position != -1:
                    address = base + offset + position + VALUE_OFFSET
                    if position < CHUNK and address % 8 == 0 and self.is_variable(address, name):
                        found.append(address)
                    position = data.find(pattern, position + 1)
        return found

    def is_variable(self, address: int, name: str) -> bool:
        """Whether this is still the address of the value of a variable with this name."""
        pattern = variable_header(name)
        data = self.read(address - VALUE_OFFSET, VALUE_OFFSET)
        return (len(data) == VALUE_OFFSET and data.startswith(pattern)
                and struct.unpack_from("<QQ", data, 16) == (len(pattern) - 1, NAME_CAPACITY))

    def read_value(self, address: int) -> int | None:
        """The value of the variable, if it is a whole number."""
        data = self.read(address, 8)
        if len(data) != 8:
            return None
        value, fraction = divmod(struct.unpack("<q", data)[0], SCALE)
        return None if fraction else value

    def write_value(self, address: int, value: int) -> bool:
        data = struct.pack("<q", value * SCALE)
        done = ctypes.c_size_t()
        return bool(kernel32.WriteProcessMemory(self.process, address, data, len(data), ctypes.byref(done)))
