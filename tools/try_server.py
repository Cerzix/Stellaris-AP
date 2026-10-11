"""Plays a few checks against a real Archipelago server, without the game: a manual test of the connection.

    python tools/try_server.py <address> <slot name> [location id ...]

The game is replaced by a folder with a game.log that this script writes the checks into.
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stellaris_ap import build_mod  # noqa: E402
from stellaris_ap.profiles import Profiles  # noqa: E402
from stellaris_ap.session import ServerSession  # noqa: E402


def show(kind: str, parts) -> None:
    text = parts if isinstance(parts, str) else "".join(text for text, _ in parts)
    print(f"[{kind:6}] {text}", flush=True)


def main() -> None:
    address, slot_name, *locations = sys.argv[1:]
    with tempfile.TemporaryDirectory() as folder:
        user_dir = Path(folder)
        (user_dir / "logs").mkdir()
        log = user_dir / "logs" / "game.log"
        log.write_text("", encoding="utf-8")
        session = ServerSession(user_dir, show, Profiles(user_dir / "profiles.json"), address, slot_name,
                                delivery="manual")
        deadline = time.monotonic() + 12
        pending = [int(location) for location in locations]
        said = False
        while time.monotonic() < deadline:
            session.tick()
            if session.ready and pending:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"[x] AP_HELLO\n[x] AP_CHECK {pending.pop(0)}\n")
            elif session.ready and not said:
                said = True
                session.command("!hint Progressive Ascension")
                session.command("/status")
            time.sleep(0.2)
        show("result", session.status())
        show("result", f"run file: {len((user_dir / 'ap.txt').read_text().splitlines())} lines")
        session.stop()
    # The names in the mod are those of this test now: back to the default ones
    build_mod.write_check_names()


if __name__ == "__main__":
    main()
