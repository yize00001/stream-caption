"""
Floating subtitle overlay window using tkinter.
Runs in its own thread; receives (ja_text, zh_text) pairs via a queue.
"""

import json
import queue
import threading
import tkinter as tk
from pathlib import Path

from stream_caption.settings import OverlaySettings

_STATE_PATH = Path(__file__).parent.parent.parent / "window-state.json"


def _load_state() -> dict | None:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_state(x: int, y: int, w: int, h: int) -> None:
    try:
        _STATE_PATH.write_text(
            json.dumps({"x": x, "y": y, "w": w, "h": h}), encoding="utf-8"
        )
    except Exception:
        pass


class SubtitleOverlay:
    def __init__(self, s: OverlaySettings | None = None):
        self._s = s or OverlaySettings()
        self._queue: queue.Queue[tuple[str | None, str, str, bool]] = queue.Queue()
        self._pairs: list[tuple[str, str]] = []
        self._caption_indexes: dict[str, int] = {}
        self._draft_indexes: set[int] = set()
        self._user_hidden: bool = False
        self._visibility_changed: bool = False
        self._auto_hide_enabled = self._s.auto_hide_enabled
        self._auto_hide_changed = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def push(self, ja: str, zh: str):
        self._queue.put((None, ja, zh, True))

    def upsert(self, caption_id: str, source: str, translated: str, *, final: bool = True):
        """Revisions replace the existing caption instead of appending history."""
        self._queue.put((caption_id, source, translated, final))

    def toggle(self):
        """Toggle overlay on/off. Safe to call from any thread."""
        self._user_hidden = not self._user_hidden
        self._visibility_changed = True

    @property
    def auto_hide_enabled(self) -> bool:
        return self._auto_hide_enabled

    def toggle_auto_hide(self):
        """Request a timer update; all tkinter work stays on the UI thread."""
        self._auto_hide_enabled = not self._auto_hide_enabled
        self._auto_hide_changed.set()

    def _render(self, text_widget: tk.Text, scroll_to_bottom: bool = True):
        text_widget.config(state="normal")
        text_widget.delete("1.0", "end")
        for i, (ja, zh) in enumerate(self._pairs):
            if i > 0:
                text_widget.insert("end", "\n")
            prefix = "[暫定] " if i in self._draft_indexes else ""
            text_widget.insert("end", prefix + ja + "\n", "ja")
            text_widget.insert("end", zh, "zh")
        text_widget.config(state="disabled")
        if scroll_to_bottom:
            text_widget.see("end")

    def _run(self):
        s = self._s
        root = tk.Tk()
        root.title("stream-caption")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0 if self._auto_hide_enabled else s.opacity)
        root.configure(bg=s.bg_color)
        root.resizable(False, False)

        state = _load_state()
        if state:
            w, h = state["w"], state["h"]
            x, y = state["x"], state["y"]
        else:
            w, h = s.width, s.height
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = (sw - w) // 2
            y = sh - h - 60
        root.geometry(f"{w}x{h}+{x}+{y}")

        self._drag_x = 0
        self._drag_y = 0
        _save_timer = [None]

        def schedule_save():
            if _save_timer[0]:
                root.after_cancel(_save_timer[0])
            _save_timer[0] = root.after(
                1000,
                lambda: _save_state(root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height()),
            )

        def on_press(event):
            self._drag_x = event.x
            self._drag_y = event.y

        def on_drag(event):
            dx = event.x - self._drag_x
            dy = event.y - self._drag_y
            root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")
            schedule_save()

        root.bind("<ButtonPress-1>", on_press)
        root.bind("<B1-Motion>", on_drag)

        txt = tk.Text(
            root,
            bg=s.bg_color,
            relief="flat",
            font=(s.font_family, s.font_size_zh),
            padx=10,
            pady=10,
            cursor="arrow",
            wrap="word",
        )
        txt.tag_configure("ja", font=(s.font_family, s.font_size_ja), foreground=s.fg_ja)
        txt.tag_configure("zh", font=(s.font_family, s.font_size_zh), foreground=s.fg_zh)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)

        # Enable mouse wheel scrolling on disabled Text widget
        def on_mousewheel(event):
            txt.config(state="normal")
            txt.yview_scroll(int(-1 * (event.delta / 120)), "units")
            txt.config(state="disabled")

        txt.bind("<MouseWheel>", on_mousewheel)
        root.bind("<MouseWheel>", on_mousewheel)

        # Resize grip — bottom-right corner
        grip = tk.Label(root, bg=s.bg_color, cursor="sizing", text="⠿", fg="#444444")
        grip.place(relx=1.0, rely=1.0, anchor="se")

        _rx, _ry = [0], [0]

        def on_grip_press(event):
            _rx[0] = event.x_root
            _ry[0] = event.y_root

        def on_grip_drag(event):
            dx = event.x_root - _rx[0]
            dy = event.y_root - _ry[0]
            _rx[0] = event.x_root
            _ry[0] = event.y_root
            new_w = max(300, root.winfo_width() + dx)
            new_h = max(60, root.winfo_height() + dy)
            root.geometry(f"{new_w}x{new_h}")
            schedule_save()

        grip.bind("<ButtonPress-1>", on_grip_press)
        grip.bind("<B1-Motion>", on_grip_drag)

        hide_timer = [None]
        mouse_over = [False]

        def hide():
            hide_timer[0] = None
            if self._auto_hide_enabled and not mouse_over[0]:
                root.attributes("-alpha", 0)

        def cancel_hide():
            if hide_timer[0] is not None:
                root.after_cancel(hide_timer[0])
                hide_timer[0] = None

        def schedule_hide():
            cancel_hide()
            if (self._auto_hide_enabled and not mouse_over[0]
                    and not self._user_hidden and root.attributes("-alpha") > 0):
                hide_timer[0] = root.after(s.auto_hide_seconds * 1000, hide)

        def on_enter(event):
            mouse_over[0] = True
            # Cancel auto-hide while hovering
            cancel_hide()

        def on_leave(event):
            mouse_over[0] = False
            # Restart auto-hide when mouse leaves
            schedule_hide()

        root.bind("<Enter>", on_enter)
        root.bind("<Leave>", on_leave)

        def poll():
            updated = False
            try:
                while True:
                    caption_id, ja, zh, final = self._queue.get_nowait()
                    if caption_id is not None and caption_id in self._caption_indexes:
                        index = self._caption_indexes[caption_id]
                        self._pairs[index] = (ja, zh)
                    else:
                        index = len(self._pairs)
                        if caption_id is not None:
                            self._caption_indexes[caption_id] = index
                        self._pairs.append((ja, zh))
                    if final:
                        self._draft_indexes.discard(index)
                    else:
                        self._draft_indexes.add(index)
                    updated = True
            except queue.Empty:
                pass

            visibility_changed = self._visibility_changed
            self._visibility_changed = False
            auto_hide_changed = self._auto_hide_changed.is_set()
            if auto_hide_changed:
                self._auto_hide_changed.clear()

            if updated or visibility_changed or auto_hide_changed:
                if self._user_hidden:
                    cancel_hide()
                    root.attributes("-alpha", 0)
                else:
                    # Refresh history received while manually hidden as well.
                    at_bottom = txt.yview()[1] >= 0.95
                    self._render(txt, scroll_to_bottom=at_bottom)
                    if self._pairs or not self._auto_hide_enabled:
                        root.attributes("-alpha", s.opacity)
                    schedule_hide()
            root.after(100, poll)

        root.after(100, poll)
        root.mainloop()
