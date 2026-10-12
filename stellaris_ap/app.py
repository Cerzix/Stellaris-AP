"""The window of the client: connect to a multiworld, start the game, and watch what happens.

    pythonw -m stellaris_ap.app        (what "Play Stellaris Archipelago.bat" runs)

The window stays open while playing. It has to be there before the game starts, because the game
reads the names of the technologies and traditions (which say what they send) once, at its start.

The window only shows things. Everything that touches the game or the server happens in one other
thread, which takes what the player does from a queue.
"""
import os
import queue
import sys
import threading
import time
import tkinter
from tkinter import messagebox, ttk

from . import build_mod, data
from .client import LOG_FILE, asked_to_quit, only_instance, shuffle
from .memory import stellaris_pid
from .paths import WRITE_BLOCKED_HINT, stellaris_user_dir
from .profiles import Profile, Profiles
from .session import OfflineSession, ServerSession, Session
from .settings import Settings
from .tracker import TrackerState, TrackerWindow

STELLARIS = "steam://rungameid/281990"
DEFAULT_SERVER = "archipelago.gg:"
TICK_SECONDS = 0.25

BACKGROUND = "#14181f"
# How the kinds of lines and of their parts look: (label in front of the line, colour)
LINES = {
    "item": ("ITEM", "#c792ea"), "check": ("CHECK", "#c3e88d"), "hint": ("HINT", "#f7d774"),
    "death": ("DEATH", "#ff5370"), "game": ("GAME", "#7fdbca"), "server": ("SERVER", "#8792a2"),
    "chat": ("CHAT", "#ffffff"), "error": ("ERROR", "#ff5370"), "info": ("INFO", "#82aaff"),
}
PARTS = {
    "text": "#d7dde5", "player": "#ffcb6b", "me": "#f78c6c", "location": "#c3e88d",
    "progression": "#c792ea", "useful": "#82aaff", "trap": "#ff5370", "filler": "#89ddff",
}


def describe(profile: Profile) -> str:
    """A run in the list of the ones without a server."""
    return f"{profile.name}  ({len(profile.checked)} of {len(data.locations())} locations)"


def plain(parts) -> str:
    return parts if isinstance(parts, str) else "".join(text for text, _ in parts)


class App:
    def __init__(self, store: Profiles, user_dir, lock=None, log_file=LOG_FILE, delivery: str = "memory",
                 settings: Settings | None = None):
        self.store = store
        self.user_dir = user_dir
        self.delivery = delivery
        self.lock = lock
        self.session: Session | None = None
        self.requests: queue.Queue = queue.Queue()
        self.lines: queue.Queue = queue.Queue()
        self.closing = False
        self.tracker: TrackerWindow | None = None
        self.settings = settings or Settings()
        self.last_tracker_state = TrackerState()
        self.log_file = open(log_file, "w", encoding="utf-8", buffering=1) if log_file else None

        self.window = tkinter.Tk()
        self.window.title("Stellaris Archipelago")
        self.window.geometry("900x560")
        self.window.minsize(700, 380)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.log("info", "Connect to a multiworld, then start Stellaris. /help lists what you can type below.")
        self.core = threading.Thread(target=self.run_core, daemon=True)
        self.core.start()
        self.timer = self.window.after(100, self.refresh)

    # --- the window

    def build(self) -> None:
        recent = self.store.recent_servers()
        bar = ttk.Frame(self.window, padding=(10, 10, 10, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Server").pack(side="left")
        self.address = ttk.Combobox(bar, width=26, values=[address for address, _ in recent])
        self.address.set(recent[0][0] if recent else DEFAULT_SERVER)
        self.address.pack(side="left", padx=(4, 10))
        self.address.bind("<<ComboboxSelected>>", self.pick_recent)
        ttk.Label(bar, text="Slot name").pack(side="left")
        self.slot = ttk.Entry(bar, width=16)
        self.slot.insert(0, recent[0][1] if recent else "")
        self.slot.pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="Password").pack(side="left")
        self.password = ttk.Entry(bar, width=12, show="*")
        self.password.pack(side="left", padx=(4, 10))
        ttk.Button(bar, text="Connect", command=self.connect).pack(side="left")
        for field in (self.address, self.slot, self.password):
            field.bind("<Return>", lambda event: self.connect())

        status = ttk.Frame(self.window, padding=(10, 2, 10, 6))
        status.pack(fill="x")
        self.play = ttk.Button(status, text="Start Stellaris", command=self.start_game, state="disabled")
        self.play.pack(side="right")
        ttk.Button(status, text="Tracker", command=self.open_tracker).pack(side="right", padx=6)
        self.status = ttk.Label(status, text="Not connected.")
        self.status.pack(side="left")

        entry = ttk.Frame(self.window, padding=(10, 6, 10, 10))
        entry.pack(fill="x", side="bottom")
        ttk.Button(entry, text="Send", command=self.send).pack(side="right")
        ttk.Button(entry, text="Hint", command=self.hint).pack(side="right", padx=6)
        self.entry = ttk.Entry(entry)
        self.entry.pack(fill="x", side="left", expand=True)
        self.entry.bind("<Return>", lambda event: self.send())

        frame = ttk.Frame(self.window, padding=(10, 0, 10, 0))
        frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(frame)
        scroll.pack(side="right", fill="y")
        self.text = tkinter.Text(frame, background=BACKGROUND, foreground=PARTS["text"], insertbackground="#ffffff",
                                 font=("Consolas", 10), wrap="word", state="disabled", borderwidth=0,
                                 padx=10, pady=8, yscrollcommand=scroll.set, spacing1=2)
        self.text.pack(fill="both", expand=True)
        scroll.configure(command=self.text.yview)
        self.text.tag_configure("time", foreground="#566070")
        for kind, (_, colour) in LINES.items():
            self.text.tag_configure("label_" + kind, foreground=colour, font=("Consolas", 10, "bold"))
        for kind, colour in PARTS.items():
            self.text.tag_configure(kind, foreground=colour)
        for kind in ("progression", "me"):
            self.text.tag_configure(kind, font=("Consolas", 10, "bold"))

    def pick_recent(self, event=None) -> None:
        for address, slot in self.store.recent_servers():
            if address == self.address.get():
                self.slot.delete(0, "end")
                self.slot.insert(0, slot)
                return

    def connect(self) -> None:
        address, slot = self.address.get().strip(), self.slot.get().strip()
        if not address or address == DEFAULT_SERVER or not slot:
            messagebox.showinfo("Stellaris Archipelago", "Enter the address of the server (like archipelago.gg:38281) "
                                                         "and the name of your slot.")
            return
        self.requests.put(("connect", address, slot, self.password.get()))

    def send(self) -> None:
        text = self.entry.get().strip()
        self.entry.delete(0, "end")
        if text:
            self.requests.put(("command", text))

    def hint(self) -> None:
        """Starts a hint for the player to finish: the name of the item they are looking for."""
        self.entry.delete(0, "end")
        self.entry.insert(0, "!hint ")
        self.entry.focus_set()
        self.entry.icursor("end")

    def open_tracker(self) -> None:
        """Opens the tracker in a window of its own, or brings it to the front."""
        if self.tracker and not self.tracker.closed:
            self.tracker.window.lift()
            self.tracker.window.focus_force()
            return
        self.tracker = TrackerWindow(self.window, self.tracker_state, self.settings)

    def tracker_state(self) -> TrackerState:
        session = self.session
        try:
            self.last_tracker_state = session.tracker_state() if session else TrackerState()
        except RuntimeError:
            # The other thread changed the run while it was read: the tracker asks again in a moment
            pass
        return self.last_tracker_state

    def start_game(self) -> None:
        try:
            os.startfile(STELLARIS)
        except OSError as error:
            messagebox.showerror("Stellaris Archipelago", f"Could not start the game:\n{error}")

    def refresh(self) -> None:
        """Shows what the other thread reported."""
        if self.closing:
            return
        added = False
        while True:
            try:
                stamp, kind, parts = self.lines.get_nowait()
            except queue.Empty:
                break
            added = True
            label = LINES.get(kind, LINES["info"])[0]
            self.text.configure(state="normal")
            self.text.insert("end", stamp + "  ", "time")
            self.text.insert("end", f"{label:<7}", "label_" + (kind if kind in LINES else "info"))
            for text, part in ([(parts, "text")] if isinstance(parts, str) else parts):
                self.text.insert("end", text, part if part in PARTS else "text")
            self.text.insert("end", "\n")
            self.text.configure(state="disabled")
        if added:
            self.text.see("end")
        session = self.session
        ready = bool(session and session.ready)
        self.play.configure(state="normal" if ready else "disabled")
        if session is None:
            self.status.configure(text="Not connected.")
        else:
            self.status.configure(text=session.status() or "Connecting...")
        self.timer = self.window.after(150, self.refresh)

    def close(self) -> None:
        self.closing = True
        self.window.after_cancel(self.timer)
        if self.tracker and not self.tracker.closed:
            self.tracker.close()
        self.requests.put(("quit",))
        self.core.join(3)
        if self.log_file:
            self.log_file.close()
        self.window.destroy()

    # --- the other thread

    def log(self, kind: str, parts) -> None:
        stamp = time.strftime("%H:%M:%S")
        for line in (parts.split("\n") if isinstance(parts, str) else [parts]):
            self.lines.put((stamp, kind, line))
            if self.log_file and not self.log_file.closed:
                self.log_file.write(f"{stamp} {LINES.get(kind, LINES['info'])[0]:<7}{plain(line)}\n")

    def run_core(self) -> None:
        while True:
            try:
                request = self.requests.get(timeout=TICK_SECONDS)
            except queue.Empty:
                request = None
            try:
                if request and not self.handle(request):
                    return
                if self.session:
                    self.session.tick()
            except Exception as error:  # Shown to the player, the client goes on
                self.log("error", f"{type(error).__name__}: {error}")
            if self.lock is not None and asked_to_quit(self.lock):
                self.log("error", "Another client was started, this one stops.")
                self.replace_session(None)
                # The new client waits for the port to be free
                self.lock.close()
                self.lock = None
                return

    def replace_session(self, session: Session | None) -> None:
        if self.session:
            self.session.stop()
        self.session = session

    def handle(self, request: tuple) -> bool:
        """Carries out what the player did. False to stop."""
        if request[0] == "quit":
            self.replace_session(None)
            return False
        if request[0] == "command":
            self.log("chat", [("> ", "text"), (request[1], "me")])
            if request[1].split()[0].lower() == "/offline":
                self.offline(new=request[1].split()[1:] == ["new"])
            elif self.session:
                self.session.command(request[1])
            else:
                self.log("error", "Connect first. (For a test without a server: /offline)")
        elif request[0] == "connect":
            _, address, slot, password = request
            self.replace_session(None)
            self.replace_session(ServerSession(self.user_dir, self.log, self.store, address, slot, password,
                                               delivery=self.delivery))
        elif request[0] == "offline":
            self.offline(new=True)
        return True

    def offline(self, new: bool) -> None:
        """A randomizer of the client's own, without a server: the shuffle played last, or a new one."""
        shuffles = [profile for profile in self.store.all() if profile.state["kind"] == "offline"]
        profile = self.store.new_offline() if new or not shuffles else shuffles[0]
        self.replace_session(None)
        self.replace_session(OfflineSession(self.user_dir, self.log, profile, shuffle, delivery=self.delivery))
        self.log("info", f"Playing {describe(profile)}. /offline new starts another shuffle.")


def main() -> None:
    try:
        from . import archipelago  # noqa: F401  Installs what the connection needs, the first time
    except ImportError as error:
        messagebox.showerror("Stellaris Archipelago", str(error))
        return
    lock = only_instance()
    if lock is None:
        messagebox.showerror("Stellaris Archipelago", "The client is already running.")
        return
    user_dir = stellaris_user_dir()
    if not user_dir.is_dir():
        messagebox.showerror("Stellaris Archipelago", f"Stellaris user directory not found:\n{user_dir}")
        return
    try:
        app = App(Profiles(), user_dir, lock)
    except OSError as error:
        messagebox.showerror("Stellaris Archipelago",
                             WRITE_BLOCKED_HINT.format(path=error.filename or user_dir, python=sys.executable))
        return
    try:
        if build_mod.register(user_dir):
            app.log("info", 'The mod was registered with the Stellaris launcher. Add "Archipelago" to your '
                            "playset there and enable it, once.")
    except OSError as error:
        app.log("error", WRITE_BLOCKED_HINT.format(path=error.filename or user_dir, python=sys.executable))
    if stellaris_pid() is not None:
        app.log("info", "Stellaris is already running. After connecting, restart it to see the right names.")
    app.window.mainloop()
    lock.close()


if __name__ == "__main__":
    main()
