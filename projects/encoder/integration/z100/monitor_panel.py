"""Controls and physical UART transcript for the live KWT monitor."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from workbench_theme import BLUE, CARD, INK, LINE, MUTED, PANEL, RED

MIC = "电脑麦克风"
DEMO = "验证集示例"
FILES = "本机 WAV"


class MonitorPanel:
    def __init__(self, app, parent):
        self.app = app
        self.stop = None
        self.paths = ()
        self.source = tk.StringVar(value=MIC)
        self.com = tk.StringVar()
        self.status = tk.StringVar(value="就绪后可开始监听")
        self.file_text = tk.StringVar()
        self.meter = tk.StringVar(value="等待音频输入")
        self.hit = tk.StringVar(value="—")
        self.detail = tk.StringVar(value="串口收到的关键词将按时间排列")
        self.envelope = self.last_hit = None
        self.capture_hit = False

        bar = tk.Frame(parent, bg=PANEL)
        bar.pack(fill="x", pady=(12, 4))
        app.text(bar, "音频来源", size=9, color=MUTED).pack(side="left")
        self.mode = ttk.Combobox(bar, textvariable=self.source, values=(MIC, DEMO, FILES), width=12, state="readonly")
        self.mode.pack(side="left", padx=(6, 12))
        self.mode.bind("<<ComboboxSelected>>", lambda _: self.source_changed())
        self.files = ttk.Button(bar, text="选 WAV…", command=self.choose)
        self.files.pack(side="left")
        app.text(bar, "日志串口", size=9, color=MUTED).pack(side="left", padx=(12, 5))
        self.ports = ttk.Combobox(bar, textvariable=self.com, width=9, postcommand=self.refresh_ports)
        self.ports.pack(side="left")
        self.refresh_ports()
        self.toggle = ttk.Button(bar, text="开始监听", style="Primary.TButton", command=self.toggle_monitor)
        self.toggle.pack(side="right")
        app.text(parent, variable=self.file_text, size=9, color=MUTED).pack(anchor="w", pady=(0, 8))

        live = app.card(parent, inset=(12, 9))
        live.pack(fill="x")
        line = tk.Frame(live.content, bg=CARD)
        line.pack(fill="x")
        self.status_label = app.text(line, variable=self.status, size=11, weight="bold", background=CARD)
        self.status_label.pack(side="left")
        app.text(line, variable=self.hit, size=14, weight="bold", color=BLUE, background=CARD).pack(side="right")
        self.wave = tk.Canvas(live.content, background=CARD, highlightthickness=0, height=92)
        self.wave.pack(fill="x", pady=(4, 1))
        self.wave.bind("<Configure>", lambda _: self.draw())
        app.text(live.content, variable=self.meter, size=9, color=MUTED, background=CARD).pack(anchor="w")
        live.fit_content()

        app.text(parent, "串口接收", size=12, weight="bold").pack(anchor="w", pady=(14, 3))
        app.text(parent, variable=self.detail, size=9, color=MUTED).pack(anchor="w", pady=(0, 6))
        table = tk.Frame(parent, bg=PANEL)
        table.pack(fill="both", expand=True, pady=(0, 8))
        self.log = ttk.Treeview(table, columns=("line", "port"), show="headings", selectmode="browse", height=6)
        for name, title, width in (("line", "板卡原文 · 本地采集时间", 355), ("port", "接收端口", 100)):
            self.log.heading(name, text=title, anchor="w")
            self.log.column(name, width=width, anchor="w", stretch=(name=="line"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.source_changed()

    def refresh_ports(self):
        from serial.tools import list_ports
        devices = sorted(list_ports.comports(), key=lambda p: (p.vid != 0x1a86, p.vid is None, p.device))
        names = [p.device for p in devices]
        self.ports.configure(values=names)
        if not self.com.get() and names:
            self.com.set(names[0])

    def choose(self):
        paths = filedialog.askopenfilenames(parent=self.app.root, title="选择连续回放的 WAV", filetypes=[("WAV 音频", "*.wav")])
        if paths:
            self.paths = tuple(Path(p) for p in paths)
            self.source.set(FILES)
            self.source_changed()

    def source_changed(self):
        if self.source.get() == FILES:
            self.file_text.set(f"{len(self.paths)} 个 WAV · {self.paths[0].name}" if self.paths else "选择一个长录音或多个 WAV，按原速送入监听")
        elif self.source.get() == DEMO:
            self.file_text.set("原速输入验证集音频流 · three、yes、no、stop、go · 文件间隔 1 秒静音")
        else:
            self.file_text.set("16 kHz 单声道 · 每 200 ms 检查最近 1 秒音频")
        self.available(self.app.ready and not self.app.busy)

    def available(self, active):
        running = self.stop is not None
        self.mode.configure(state="readonly" if active else "disabled")
        self.files.configure(state="normal" if active else "disabled")
        self.ports.configure(state="normal" if active else "disabled")
        self.toggle.configure(state="normal" if active or (running and not self.stop.is_set()) else "disabled",
                              text="停止监听" if running else "开始监听")

    def toggle_monitor(self):
        if self.stop is not None:
            self.stop.set()
            self.status.set("正在停止监听…")
            self.toggle.configure(state="disabled")
            return
        if not self.app.ready or self.app.busy:
            return
        paths = None
        if self.source.get() == DEMO:
            names = self.app.sample_menu.cget("values")
            paths = tuple(self.app.model.dataset / next(n for n in names if n.startswith(k+"/"))
                          for k in ("three", "yes", "no", "stop", "go"))
        elif self.source.get() == FILES:
            if not self.paths:
                self.choose()
            if not self.paths:
                return
            paths = self.paths
        self.app.stop_playback()
        self.stop = threading.Event()
        self.app.set_busy(True)
        self.status_label.configure(foreground=INK)
        self.status.set("正在连接板卡与日志串口…")
        self.meter.set("等待第一帧音频")
        self.hit.set("—")
        self.envelope = self.last_hit = None
        self.capture_hit = False
        self.draw()
        self.app.worker.submit(self.run, self.app.port.get().strip(), self.com.get().strip(), paths, self.stop)

    def run(self, endpoint, com, paths, stop):
        from realtime import listen
        def emit(kind, payload):
            self.app.events.put(("monitor", (kind, payload)))
        try:
            windows, hits = listen(self.app.model, endpoint, com, paths, stop, emit)
            emit("done", f"{'监听已停止' if stop.is_set() else '回放结束'} · {windows} 个窗口 · 命中 {hits} 次")
        except Exception as exc:
            emit("failed", str(exc))

    def draw(self):
        w, h = self.wave.winfo_width(), self.wave.winfo_height()
        self.wave.delete("all")
        self.wave.create_line(0, h/2, w, h/2, fill=LINE)
        if self.envelope is not None:
            lo, hi = self.envelope
            points = [(i*w/(len(lo)-1), h*(.5-.46*v)) for i,v in enumerate(hi)]
            points.extend((i*w/(len(lo)-1), h*(.5-.46*lo[i])) for i in reversed(range(len(lo))))
            self.wave.create_polygon(points, fill=BLUE, outline=BLUE)

    def handle(self, kind, data):
        if kind == "listening":
            self.status.set("监听中")
            self.detail.set(data)
        elif kind == "keyword":
            raw, com = data
            self.log.insert("", 0, values=(raw, com))
            if len(self.log.get_children()) > 500:
                self.log.delete(self.log.get_children()[-1])
            self.hit.set(raw.rsplit(" ", 1)[1])
            self.capture_hit = True
        elif kind == "window":
            lo, hi, title, windows, hits, ms, stamp, gaps = data
            self.envelope = lo, hi
            self.draw()
            msg = f"{stamp[11:]}   ·   {title}   ·   窗口 {windows}   ·   命中 {hits}"
            if ms is not None:
                msg += f"   ·   板上 {ms:.1f} ms"
            if gaps:
                msg += f"   ·   音频中断 {gaps} 次"
            self.meter.set(msg)
            if self.capture_hit:
                self.last_hit = (self.envelope, stamp, self.hit.get())
                self.capture_hit = False
        else:
            self.stop = None
            if kind == "done" and self.last_hit:
                self.envelope, stamp, word = self.last_hit
                self.meter.set(f"最近命中波形 · {word} · {stamp}")
                self.draw()
            self.status_label.configure(foreground=RED if kind=="failed" else INK)
            self.status.set(data)
            self.app.set_busy(False)
