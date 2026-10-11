"""Installs what the client needs beyond Python itself, the first time it is started.

    websockets = require("websockets")

The client is started without a console, so while pip works a small window says what is going on.
"""
import importlib
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def install(package: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", package],
                          capture_output=True, text=True, errors="replace", creationflags=CREATE_NO_WINDOW)


def notice(text: str):
    """A window with a line of text, or None if there is no screen to show it on."""
    try:
        import tkinter
        window = tkinter.Tk()
        window.title("Stellaris Archipelago")
        tkinter.Label(window, text=text, padx=30, pady=24).pack()
        window.update()
        return window
    except Exception:
        return None


def require(package: str, install=install, notice=notice):
    """The module of a package, which is installed first if it is missing."""
    try:
        return importlib.import_module(package)
    except ImportError:
        pass
    window = notice(f"Setting up for the first start: installing {package}...")
    try:
        result = install(package)
    finally:
        if window is not None:
            window.destroy()
    importlib.invalidate_caches()
    try:
        return importlib.import_module(package)
    except ImportError:
        raise ImportError(f"Could not install {package}. Run this yourself: "
                          f'"{sys.executable}" -m pip install {package}\n\n{result.stderr[-600:]}') from None
