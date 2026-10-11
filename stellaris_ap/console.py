"""Presses keys in Stellaris to re-run the last console command.

Only layout independent scancodes are sent: open the console, Up (recall the last command),
Enter, close the console. The player has to type "run ap.txt" once per game session so that
it is the last command in the console history.
"""
import ctypes
import time
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

SCAN_CONSOLE = 0x29  # the key left of 1: ` on US keyboards, ^ on German ones
SCAN_ENTER = 0x1C
SCAN_UP = 0x48  # extended

# How long a key is held and released. The game reads keys once per frame, this covers 20 fps.
KEY_SECONDS = 0.05

user32 = ctypes.WinDLL("user32", use_last_error=True)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUTUNION(ctypes.Union):
    # MOUSEINPUT is the largest member, it gives INPUT the size Windows expects
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def foreground_title() -> str:
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(user32.GetForegroundWindow(), title, 256)
    return title.value


def stellaris_is_foreground() -> bool:
    return foreground_title() == "Stellaris"


def press(scancode: int, extended: bool = False) -> None:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    for key_flags in (flags, flags | KEYEVENTF_KEYUP):
        event = INPUT(type=INPUT_KEYBOARD, union=INPUTUNION(ki=KEYBDINPUT(wScan=scancode, dwFlags=key_flags)))
        user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        time.sleep(KEY_SECONDS)


def rerun_last_command() -> None:
    press(SCAN_CONSOLE)
    press(SCAN_UP, extended=True)
    press(SCAN_ENTER)
    press(SCAN_CONSOLE)
