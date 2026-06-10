"""
Floating subtitle overlay window using tkinter.
Runs in its own thread; receives (ja_text, zh_text) pairs via a queue.
"""

import queue
import threading
import tkinter as tk


MAX_PAIRS = 2
FONT_FAMILY = "Microsoft JhengHei"
FONT_SIZE_ZH = 18
FONT_SIZE_JA = 12
BG_COLOR = "#1a1a1a"
FG_ZH = "#FFD700"
FG_JA = "#87CEEB"
OPACITY = 0.88
WINDOW_WIDTH = 700
WINDOW_HEIGHT = 160
PADDING = 8
AUTO_HIDE_MS = 8000  # hide overlay after 8s of no new subtitle


class SubtitleOverlay:
    def __init__(self):
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
        root = tk.Tk()
        root.title("stream-caption")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0)  # hidden until first subtitle arrives
        root.configure(bg=BG_COLOR)
        root.resizable(False, False)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - WINDOW_WIDTH) // 2
        y = sh - WINDOW_HEIGHT - 60
        root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

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
            bg=BG_COLOR,
            relief="flat",
            font=(FONT_FAMILY, FONT_SIZE_ZH),
            padx=PADDING,
            pady=PADDING,
            cursor="arrow",
            wrap="word",
        )
        txt.tag_configure("ja", font=(FONT_FAMILY, FONT_SIZE_JA), foreground=FG_JA)
        txt.tag_configure("zh", font=(FONT_FAMILY, FONT_SIZE_ZH), foreground=FG_ZH)
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
                root.attributes("-alpha", OPACITY)
                if hide_timer[0]:
                    root.after_cancel(hide_timer[0])
                hide_timer[0] = root.after(AUTO_HIDE_MS, hide)
            root.after(100, poll)

        root.after(100, poll)
        root.mainloop()
