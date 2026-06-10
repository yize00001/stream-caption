"""
Floating subtitle overlay window using tkinter.
Runs in its own thread; receives (ja_text, zh_text) pairs via a queue.
"""

import queue
import threading
import tkinter as tk

from stream_caption.settings import OverlaySettings

MAX_PAIRS = 2


class SubtitleOverlay:
    def __init__(self, s: OverlaySettings | None = None):
        self._s = s or OverlaySettings()
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._pairs: list[tuple[str, str]] = []
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def push(self, ja: str, zh: str):
        self._queue.put((ja, zh))

    def _render(self, text_widget: tk.Text):
        text_widget.config(state="normal")
        text_widget.delete("1.0", "end")
        for i, (ja, zh) in enumerate(self._pairs):
            if i > 0:
                text_widget.insert("end", "\n")
            text_widget.insert("end", ja + "\n", "ja")
            text_widget.insert("end", zh, "zh")
        text_widget.config(state="disabled")

    def _run(self):
        s = self._s
        root = tk.Tk()
        root.title("stream-caption")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0)
        root.configure(bg=s.bg_color)
        root.resizable(False, False)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - s.width) // 2
        y = sh - s.height - 60
        root.geometry(f"{s.width}x{s.height}+{x}+{y}")

        self._drag_x = 0
        self._drag_y = 0

        def on_press(event):
            self._drag_x = event.x
            self._drag_y = event.y

        def on_drag(event):
            dx = event.x - self._drag_x
            dy = event.y - self._drag_y
            root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")

        root.bind("<ButtonPress-1>", on_press)
        root.bind("<B1-Motion>", on_drag)
        root.bind("<Double-Button-1>", lambda e: root.destroy())

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

        hide_timer = [None]

        def hide():
            root.attributes("-alpha", 0)

        def poll():
            updated = False
            try:
                while True:
                    ja, zh = self._queue.get_nowait()
                    self._pairs.append((ja, zh))
                    if len(self._pairs) > MAX_PAIRS:
                        self._pairs.pop(0)
                    updated = True
            except queue.Empty:
                pass
            if updated:
                self._render(txt)
                root.attributes("-alpha", s.opacity)
                if hide_timer[0]:
                    root.after_cancel(hide_timer[0])
                hide_timer[0] = root.after(s.auto_hide_seconds * 1000, hide)
            root.after(100, poll)

        root.after(100, poll)
        root.mainloop()
