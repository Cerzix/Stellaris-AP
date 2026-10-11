"""Sends the real key presses to a small test window and checks that they arrive.

The window shows up for a second. The test is skipped while Stellaris is in front,
so that it never presses keys in the game.
"""
import ctypes
import time
import tkinter
import unittest

from stellaris_ap import console

WINDOW_TITLE = "Stellaris Archipelago key test"
VK_RETURN = 0x0D
VK_UP = 0x26


class KeyPressTest(unittest.TestCase):
    def test_title_match_is_exact(self):
        original = console.foreground_title
        self.addCleanup(setattr, console, "foreground_title", original)
        for title, expected in (("Stellaris", True), ("Stellaris Archipelago", False), ("", False)):
            console.foreground_title = lambda: title
            self.assertEqual(console.stellaris_is_foreground(), expected, title)

    def test_input_structure_size(self):
        self.assertEqual(ctypes.sizeof(console.INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_keys_arrive_in_the_focused_window(self):
        if console.stellaris_is_foreground():
            self.skipTest("Stellaris is in front")
        window = tkinter.Tk()
        self.addCleanup(window.destroy)
        window.title(WINDOW_TITLE)
        window.geometry("300x80")
        window.attributes("-topmost", True)
        pressed = []
        window.bind("<KeyPress>", lambda event: pressed.append(event.keycode))
        window.focus_force()
        self.pump(window, 0.4)
        if console.foreground_title() != WINDOW_TITLE:
            self.skipTest("Windows did not let the test window take the focus")

        console.rerun_last_command()
        self.pump(window, 0.4)

        console_key = console.user32.MapVirtualKeyW(console.SCAN_CONSOLE, 1)  # scancode -> virtual key
        # Without the keys the person at the keyboard pressed in the meantime
        expected = [console_key, VK_UP, VK_RETURN, console_key]
        self.assertEqual([key for key in pressed if key in expected], expected)

    def pump(self, window: tkinter.Tk, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
