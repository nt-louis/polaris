"""Terminal mode context managers, input readers, and confirmation gates."""

import os
import re
import select
import sys
import time
from typing import Optional

_LAST_SCROLL_TIME = 0.0
_SCROLL_COOLDOWN = 0.04  # 40ms debounce: debounces micro-bursts for 1-by-1 notches while allowing fast fluid scrolling (~25 items/s)
# Only enable Normal Tracking (1000) and SGR Extended Mode (1006).
# Exclude 1003 (Any Motion) and 1002 (Button Motion) to prevent mouse hover flooding stdin.
MOUSE_TRACKING_MODES = ("1000", "1006")
_ALL_MOUSE_MODES = ("1000", "1002", "1003", "1006", "1015")
_SGR_MOUSE_RE = re.compile(r"^\x1b\[<(\d+);(\d+);(\d+)([Mm])")


def set_mouse_tracking(enabled: bool) -> None:
    """Enable or disable terminal mouse tracking sequences."""
    if enabled:
        sequences = "".join(f"\x1b[?{mode}h" for mode in MOUSE_TRACKING_MODES)
    else:
        sequences = "".join(f"\x1b[?{mode}l" for mode in _ALL_MOUSE_MODES)
    sys.stdout.write(sequences)
    sys.stdout.flush()


def _drain_repeated_key(fd: int, ch: str) -> None:
    """Drain queued identical escape sequences from stdin when holding a navigation key."""
    ch_bytes = ch.encode("utf-8")
    byte_len = len(ch_bytes)
    while True:
        r, _, _ = select.select([fd], [], [], 0.0)
        if not r:
            break
        try:
            peek_raw = os.read(fd, byte_len)
            if not peek_raw:
                break
            if peek_raw != ch_bytes:
                break
        except (OSError, ValueError):
            break


def _drain_mouse_input(fd: int) -> None:
    """Drain any pending queued mouse/scroll sequences from the terminal buffer."""
    while True:
        r, _, _ = select.select([fd], [], [], 0.0)
        if not r:
            break
        try:
            buf = os.read(fd, 256)
            if not buf:
                break
        except (OSError, ValueError):
            break



class RawTerminalContext:
    """Context manager setting raw/cbreak mode on stdin for interactive TUIs."""

    def __init__(self) -> None:
        self.fd = None
        self.old_settings = None

    def __enter__(self) -> Optional[int]:
        if not sys.stdin.isatty():
            return None
        try:
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            return self.fd
        except Exception:
            return None

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.fd is not None and self.old_settings is not None:
            try:
                import termios
                termios.tcsetattr(self.fd, termios.TCSANOW, self.old_settings)
            except Exception:
                pass


class StandardTerminalContext:
    """Context manager temporarily restoring canonical terminal mode for child commands."""

    def __init__(self, raw_ctx: Optional[RawTerminalContext] = None) -> None:
        self.raw_ctx = raw_ctx

    def __enter__(self) -> None:
        try:
            import termios
            fd = self.raw_ctx.fd if self.raw_ctx else sys.stdin.fileno()
        except Exception:
            return

        old = getattr(self.raw_ctx, "old_settings", None)
        if old is not None:
            try:
                termios.tcsetattr(fd, termios.TCSANOW, old)
            except Exception:
                pass
        else:
            try:
                mode = termios.tcgetattr(fd)
                mode[3] |= (termios.ECHO | termios.ICANON)
                termios.tcsetattr(fd, termios.TCSANOW, mode)
            except Exception:
                pass

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            import tty
            fd = self.raw_ctx.fd if self.raw_ctx else sys.stdin.fileno()
            tty.setcbreak(fd)
        except Exception:
            pass


def _read_key_bytes(fd: int, timeout: Optional[float] = None) -> Optional[str]:
    global _LAST_SCROLL_TIME
    if timeout is not None:
        r, _, _ = select.select([fd], [], [], timeout)
        if not r:
            return None

    try:
        raw_ch = os.read(fd, 1)
    except (OSError, ValueError):
        return None

    if not raw_ch:
        return None

    ch = raw_ch.decode("utf-8", errors="ignore")
    if ch == "\x1b":
        while True:
            r, _, _ = select.select([fd], [], [], 0.005)
            if not r:
                break
            try:
                next_raw = os.read(fd, 1)
            except (OSError, ValueError):
                break
            if not next_raw:
                break
            next_ch = next_raw.decode("utf-8", errors="ignore")
            ch += next_ch

            # Normal X10/X11 mouse sequence (\x1b[M) is followed by exactly 3 payload bytes (btn, col, row)
            if ch == "\x1b[M":
                for _ in range(3):
                    r_p, _, _ = select.select([fd], [], [], 0.005)
                    if not r_p:
                        break
                    try:
                        p_raw = os.read(fd, 1)
                        if not p_raw:
                            break
                        ch += p_raw.decode("utf-8", errors="ignore")
                    except (OSError, ValueError):
                        break
                break

            # Sequence terminators for standard ANSI escape sequences and SGR mouse (<...M/m)
            if next_ch in ("A", "B", "C", "D", "H", "F", "M", "m", "~"):
                break

    # 1. Parse Normal X10/X11 Mouse Sequence: \x1b[M<btn><col><row>
    if ch.startswith("\x1b[M") and len(ch) >= 6:
        btn_char = ch[3]
        btn_code = ord(btn_char) - 32
        if btn_code in (64, 65):  # Wheel Up / Down
            now = time.monotonic()
            if now - _LAST_SCROLL_TIME < _SCROLL_COOLDOWN:
                _drain_mouse_input(fd)
                return None
            _LAST_SCROLL_TIME = now
            _drain_mouse_input(fd)
            return "\x1b[<wheel_up>" if btn_code == 64 else "\x1b[<wheel_down>"

        _drain_mouse_input(fd)
        return None

    # 2. Parse SGR Mouse Sequence: \x1b[<button;column;row[M|m]
    if ch.startswith("\x1b[<"):
        match = _SGR_MOUSE_RE.match(ch)
        if match:
            btn_code = int(match.group(1))
            flag = match.group(4)
            # Button code: 64 = Wheel Up, 65 = Wheel Down
            # Mask out modifier bits (4=Shift, 8=Alt, 16=Ctrl)
            base_btn = btn_code & ~28

            if flag == "M" and base_btn in (64, 65):  # Wheel Event
                now = time.monotonic()
                if now - _LAST_SCROLL_TIME < _SCROLL_COOLDOWN:
                    _drain_mouse_input(fd)
                    return None

                _LAST_SCROLL_TIME = now
                _drain_mouse_input(fd)
                return "\x1b[<wheel_up>" if base_btn == 64 else "\x1b[<wheel_down>"

        # Discard non-wheel mouse events (clicks, releases, hover motions) and drain buffer
        _drain_mouse_input(fd)
        return None

    # 3. For navigation keys that can repeat rapidly, drain any buffered duplicates
    if ch in ("\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D", "\x1b[5~", "\x1b[6~", "j", "k"):
        _drain_repeated_key(fd, ch)

    return ch



def get_key(fd: Optional[int] = None, timeout: Optional[float] = 0.05) -> Optional[str]:
    """Read a single keypress or ANSI escape sequence from the terminal."""
    if fd is not None:
        return _read_key_bytes(fd, timeout=timeout)

    if not sys.stdin.isatty():
        return None

    try:
        import termios
        import tty
        sys_fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(sys_fd)
        tty.setcbreak(sys_fd)
    except Exception:
        sys_fd = None
        old_settings = None

    try:
        if sys_fd is not None:
            return _read_key_bytes(sys_fd, timeout=timeout)
        return None
    finally:
        if sys_fd is not None and old_settings is not None:
            try:
                termios.tcsetattr(sys_fd, termios.TCSANOW, old_settings)
            except Exception:
                pass


def confirm_action(
    prompt: str,
    yes: bool = False,
    default_yes: bool = False,
    danger: bool = False,
) -> bool:
    """Prompt the user for interactive confirmation of high-impact actions."""
    if yes:
        return True

    if not sys.stdin.isatty():
        print(f"[BLOCK] {prompt}\n        Non-interactive shell; pass --yes/-y to proceed.", file=sys.stderr)
        return False

    prefix = "\033[1;31m[DANGER]\033[0m " if danger else "\033[1;33m[CONFIRM]\033[0m "
    hint = " [Y/n]: " if default_yes else " [y/N]: "

    try:
        response = input(f"{prefix}{prompt}{hint}").strip().lower()
        if not response:
            return default_yes
        return response in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print("\n[CANCEL] Operation aborted by user.")
        return False
