"""Windows operator interface for the Z100 Keyword Transformer."""

import argparse
import csv
import json
import math
import queue
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tkinter import filedialog, ttk
from pathlib import Path

from monitor_panel import MonitorPanel
from board import DEMO_BAUD, DEMO_TCP, connect_for_audio
from workbench_theme import BG, BLUE, CARD, FONT, GREEN, INK, LINE, MUTED, PANEL, RED, SIDEBAR, Surface, WorkbenchTheme

SAMPLE_RATE = 16000
HISTORY = ("时间", "音频", "真值", "预测", "预处理 ms", "板上 ms", "总耗时 ms", "PL MHz", "连接")


class Demo:
    def __init__(self, root, port, baud):
        self.root = root
        self.port = tk.StringVar(value=port)
        self.baud = tk.StringVar(value=str(baud))
        self.status = tk.StringVar(value="正在加载 KWT‑1 检查点与语音验证集")
        self.audio_name = tk.StringVar(value="请选择语音")
        self.truth = tk.StringVar(value="真实标签  —")
        self.keyword = tk.StringVar(value="—")
        self.layer_count = tk.IntVar(value=0)
        self.board_time, self.total_time, self.prep_time, self.frequency = (
            tk.StringVar(value="—") for _ in range(4)
        )
        self.sample = tk.StringVar()
        self.quick_samples = []
        self.audio = None
        self.audio_title = ""
        self.audio_truth = None
        self.history = []
        self.playing = False
        self.playback_timer = None
        self.wave_size = 0
        self.peaks = ()
        self.ready = False
        self.events = queue.SimpleQueue()
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.busy = True
        root.title("KWT‑1 语音识别工作台")
        root.geometry("1240x780")
        root.minsize(940, 660)
        root.configure(bg=BG)
        self.theme = WorkbenchTheme(root)
        self.build()
        self.worker.submit(self.load)
        self.poll()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-o>", lambda _: self.select_wav())

    def close(self):
        if self.monitor.stop is not None:
            self.monitor.stop.set()
        self.stop_playback()
        self.worker.shutdown(wait=False)
        self.root.destroy()

    def text(self, parent, value=None, *, variable=None, size=11, color=INK, background=PANEL, weight="normal"):
        return tk.Label(parent, text=value, textvariable=variable, font=(FONT, size, weight),
                        fg=color, bg=background, anchor="w")

    def build(self):
        backdrop = Surface(self.root, self.theme, material=False)
        backdrop.place(relwidth=1, relheight=1)
        self.root.tk.call("lower", backdrop._w)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        sidebar = Surface(self.root, self.theme, inset=(13, 14), color=SIDEBAR, width=196, height=1)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(11, 0), pady=10)
        self.build_sidebar(sidebar.content)

        header = Surface(self.root, self.theme, inset=(17, 9), width=1, height=1)
        header.grid(row=0, column=1, sticky="ew", padx=(11, 12), pady=(10, 0))
        self.text(header.content, "语音识别工作台", size=12, weight="bold").pack(side="left")
        self.build_connection(header.content)
        header.fit_content()

        workspace = Surface(self.root, self.theme, inset=(15, 12), width=1, height=1)
        workspace.grid(row=1, column=1, sticky="nsew", padx=(11, 12), pady=(10, 10))
        sample_row = tk.Frame(workspace.content, bg=PANEL)
        sample_row.pack(fill="x", pady=(0, 8))
        self.text(sample_row, "验证样本", size=10, color=MUTED).pack(side="left", padx=(0, 10))
        self.sample_menu = ttk.Combobox(sample_row, textvariable=self.sample, state="disabled", width=34)
        self.sample_menu.pack(side="left", fill="x", expand=True)
        self.sample_menu.bind("<Return>", lambda _: self.run_sample())
        self.sample_menu.bind("<<ComboboxSelected>>", lambda _: self.run_sample())
        self.run = ttk.Button(sample_row, text="开始识别", command=self.run_sample,
                              style="Primary.TButton", state="disabled")
        self.run.pack(side="right", padx=(8, 0))
        self.rule(workspace.content).pack(fill="x")

        self.tabs = ttk.Notebook(workspace.content)
        self.tabs.pack(fill="both", expand=True, pady=(5, 0))
        self.overview = tk.Frame(self.tabs, bg=PANEL)
        history = tk.Frame(self.tabs, bg=PANEL)
        self.tabs.add(self.overview, text="识别概览")
        monitor = tk.Frame(self.tabs, bg=PANEL)
        self.monitor_tab = monitor
        self.tabs.add(monitor, text="实时监测")
        self.tabs.add(history, text="历史记录")
        self.monitor = MonitorPanel(self, monitor)
        self.tabs.enable_traversal()
        self.build_overview(self.overview)
        self.build_history(history)

    def build_sidebar(self, parent):
        self.text(parent, "KWT‑1", size=18, background=SIDEBAR, weight="bold").pack(fill="x")
        self.text(parent, "关键词识别 · Z100", size=9, color=MUTED, background=SIDEBAR).pack(fill="x", pady=(2, 18))
        self.choose = ttk.Button(parent, text="打开 WAV…", command=self.select_wav, state="disabled")
        self.choose.pack(fill="x")
        self.record = ttk.Button(parent, text="录音 1 秒", command=lambda: self.submit(), state="disabled")
        self.record.pack(fill="x", pady=(6, 0))
        self.rule(parent).pack(fill="x", pady=(17, 13))
        self.text(parent, "快捷样本", size=10, color=MUTED, background=SIDEBAR, weight="bold").pack(fill="x", pady=(0, 7))
        self.quick_list = ttk.Treeview(parent, show="tree", height=10, selectmode="browse",
                                       style="Sidebar.Treeview")
        self.quick_list.column("#0", width=130, stretch=True)
        self.quick_list.pack(fill="both", expand=True)
        self.quick_list.bind("<<TreeviewSelect>>", self.run_quick_sample)
        self.quick_list.bind("<Return>", self.run_quick_sample)
        self.text(parent, "Zynq‑7035", size=9, background=SIDEBAR, color=MUTED).pack(fill="x", pady=(12, 2))

    def run_quick_sample(self, _event):
        selected = self.quick_list.selection()
        if selected and self.ready and not self.busy:
            self.sample.set(self.quick_samples[int(selected[0])])
            self.run_sample()

    def rule(self, parent):
        return tk.Frame(parent, bg=LINE, height=1)

    def card(self, parent, **kwargs):
        return Surface(parent, self.theme, color=CARD, card=True, width=1, height=1, **kwargs)

    def build_overview(self, parent):
        self.text(parent, "识别概览", size=15, weight="bold").pack(fill="x", pady=(12, 9))

        banner = self.card(parent, inset=(13, 8))
        banner.pack(fill="x", pady=(0, 9))
        status = banner.content
        self.status_dot = tk.Canvas(status, bg=CARD, width=12, height=16, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 7))
        self.status_marker = self.status_dot.create_oval(2, 4, 10, 12, fill=MUTED, outline="")
        self.status_label = self.text(status, variable=self.status, background=CARD, size=10)
        self.status_label.pack(side="left", fill="x", expand=True)
        banner.fit_content()

        metric_strip = self.card(parent, inset=(9, 5))
        metric_strip.pack(fill="x", pady=(0, 10))
        metrics = metric_strip.content
        for index, (label, value) in enumerate((
            ("预测关键词", self.keyword), ("板上计算", self.board_time), ("端到端", self.total_time),
            ("音频与特征", self.prep_time), ("PL 时钟", self.frequency),
        )):
            column = index * 2
            metrics.columnconfigure(column, weight=1, uniform="metric")
            if index:
                tk.Frame(metrics, bg=LINE, width=1).grid(row=0, column=column - 1, sticky="ns")
            cell = tk.Frame(metrics, bg=CARD, padx=10, pady=8)
            cell.grid(row=0, column=column, sticky="nsew")
            self.text(cell, label, size=9, color=MUTED, background=CARD).pack(fill="x")
            self.text(cell, variable=value, size=14, weight="bold", background=CARD).pack(fill="x", pady=(4, 0))
        metric_strip.fit_content()

        detail = tk.Frame(parent, bg=PANEL)
        detail.pack(fill="both", expand=True)
        detail.columnconfigure(0, weight=3, uniform="details")
        detail.columnconfigure(1, weight=2, uniform="details")
        detail.rowconfigure(0, weight=1)
        source = self.card(detail, inset=(12, 11))
        source.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        result = self.card(detail, inset=(12, 11))
        result.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.build_waveform(source.content)
        self.build_scores(result.content)

    def build_waveform(self, parent):
        self.text(parent, "语音波形", size=12, background=CARD, weight="bold").pack(fill="x")
        self.text(parent, variable=self.audio_name, size=10, background=CARD, color=MUTED).pack(fill="x", pady=(3, 8))
        controls = tk.Frame(parent, bg=CARD)
        controls.pack(side="bottom", fill="x", pady=(8, 0))
        self.replay = ttk.Button(controls, text="试听", command=self.toggle_playback, state="disabled")
        self.replay.pack(side="left")
        self.again = ttk.Button(controls, text="再次识别", command=lambda: self.submit(reuse=True), state="disabled")
        self.again.pack(side="left", padx=(6, 0))
        self.text(controls, variable=self.truth, size=9, background=CARD, color=MUTED).pack(side="right")
        self.wave = tk.Canvas(parent, height=105, bg=CARD, highlightthickness=0)
        self.wave.pack(fill="both", expand=True)
        self.wave.bind("<Configure>", lambda _: self.draw_wave())

    def build_scores(self, parent):
        self.text(parent, "识别分数", size=12, background=CARD, weight="bold").pack(fill="x")
        self.text(parent, "Top 3 · Softmax", size=9, background=CARD, color=MUTED).pack(fill="x", pady=(3, 10))
        self.scores = []
        for _ in range(3):
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill="x", pady=(0, 3))
            label = self.text(row, "—", background=CARD, size=10)
            label.pack(side="left", fill="x", expand=True)
            score = self.text(row, "—", background=CARD, size=10, color=MUTED)
            score.pack(side="right")
            bar = ttk.Progressbar(parent, maximum=100)
            bar.pack(fill="x", pady=(0, 9))
            self.scores.append((label, score, bar))
        self.rule(parent).pack(fill="x", pady=(2, 8))
        self.progress_caption = self.text(parent, "编码器  0 / 12 层", size=10, background=CARD, color=MUTED)
        self.progress_caption.pack(fill="x", pady=(0, 5))
        ttk.Progressbar(parent, variable=self.layer_count, maximum=12).pack(fill="x")

    def build_connection(self, parent):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(side="right", padx=(12, 0))
        self.text(row, "板卡连接", size=9, color=MUTED).pack(side="left")
        self.endpoint = ttk.Combobox(row, textvariable=self.port, values=(DEMO_TCP, "COM8", "JTAG"), width=19)
        self.endpoint.pack(side="left", padx=(8, 0))
        self.rate = ttk.Combobox(row, textvariable=self.baud, values=("115200", "921600"), width=8)
        self.port.trace_add("write", self.update_rate)
        self.update_rate()

    def build_history(self, panel):
        heading = tk.Frame(panel, bg=PANEL)
        heading.pack(fill="x", pady=(12, 9))
        self.text(heading, "本次识别记录", size=15, weight="bold").pack(side="left")
        self.export = ttk.Button(heading, text="导出 CSV…", command=self.export_history, state="disabled")
        self.export.pack(side="right")
        self.export_feedback = self.text(heading, "", size=9, color=MUTED)
        self.export_feedback.pack(side="right", padx=9)
        table_surface = self.card(panel, inset=(5, 5))
        table_surface.pack(fill="both", expand=True)
        table = table_surface.content
        self.log = ttk.Treeview(table, columns=HISTORY, displaycolumns=HISTORY[:8], show="headings", height=3)
        for name, width in zip(HISTORY, (65, 202, 59, 59, 78, 69, 78, 62, 130)):
            self.log.heading(name, text=name)
            self.log.column(name, width=width, minwidth=46, anchor="w" if name == "音频" else "center",
                            stretch=name == "音频")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("alternate", background="#e4edf5")
        self.empty_history = self.text(table, "识别完成后，结果会记录在这里", size=10, color=MUTED)
        self.empty_history.place(relx=0.5, rely=0.5, anchor="center")

    def export_history(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="导出本次识别记录",
                                            defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")])
        if path:
            try:
                with open(path, "w", encoding="utf-8-sig", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow(HISTORY)
                    writer.writerows(self.history)
                self.set_status(f"已导出 {len(self.history)} 条识别记录", GREEN)
                self.export_feedback.configure(text=f"已导出 {len(self.history)} 条", fg=GREEN)
            except OSError as exc:
                self.set_status(f"导出失败 · {exc}", RED)
                self.export_feedback.configure(text="导出失败", fg=RED)

    def set_status(self, message, color=MUTED):
        self.status.set(message)
        self.status_dot.itemconfigure(self.status_marker, fill=color)
        self.status_label.configure(fg=color if color in (GREEN, RED) else INK)

    def update_rate(self, *_):
        connection = self.port.get().strip().upper()
        if connection == "JTAG" or ":" in connection:
            self.rate.pack_forget()
        else:
            self.rate.pack(side="left")
            self.rate.configure(state="disabled" if self.busy else "readonly")

    def load(self):
        try:
            from model_data import ROOT, Model

            self.model = Model()
            self.validation = self.model.validation()
            silence, _ = self.model.validation_audio("silence")
            self.model.encode(silence)
            names = json.loads((ROOT / "model" / "validation-samples.json").read_text(encoding="utf-8"))
            self.events.put(("ready", tuple(dict.fromkeys(name for name in names if name != "silence"))))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def select_wav(self):
        if self.busy or not self.ready:
            return
        path = filedialog.askopenfilename(parent=self.root, title="选择 WAV 音频",
                                          initialdir=self.model.dataset,
                                          filetypes=[("WAV 音频", "*.wav")])
        if path:
            self.submit(Path(path).resolve())

    def file_audio(self, path):
        from model_data import NotValidationAudio

        dataset = self.model.dataset.resolve()
        if dataset in path.parents:
            name = path.relative_to(dataset).as_posix()
            try:
                audio, truth = self.model.validation_audio(name)
                return audio, name, truth
            except NotValidationAudio:
                pass

        import numpy as np
        from scipy.io import wavfile
        from scipy.signal import resample_poly

        rate, samples = wavfile.read(path)
        if rate <= 0 or samples.size == 0 or samples.ndim not in (1, 2):
            raise ValueError("WAV 为空或音频格式无效")
        # Use the first second, as in the validation and microphone paths.
        samples = samples[:rate]
        if samples.dtype.kind in "iu":
            info = np.iinfo(samples.dtype)
            scale = 2 ** (info.bits - 1)
            offset = scale if samples.dtype.kind == "u" else 0
            audio = ((samples.astype("float64") - offset) / scale).astype("float32")
        elif samples.dtype.kind == "f":
            audio = samples.astype("float32")
        else:
            raise ValueError("WAV 需要 PCM 或浮点采样")
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if not np.isfinite(audio).all():
            raise ValueError("WAV 中存在无效采样")
        if rate != SAMPLE_RATE:
            divisor = math.gcd(rate, SAMPLE_RATE)
            audio = resample_poly(audio, SAMPLE_RATE // divisor, rate // divisor)
        audio = np.clip(audio[:SAMPLE_RATE], -1, 1)
        return np.pad(audio, (0, SAMPLE_RATE - len(audio))), path.name, None

    def run_sample(self):
        if self.sample.get():
            self.submit(self.sample.get())

    def toggle_playback(self):
        if self.audio is None or self.busy:
            return
        if self.playing:
            self.stop_playback()
            return
        try:
            import sounddevice as sd
            sd.play(self.audio, samplerate=SAMPLE_RATE, blocking=False)
            self.playing = True
            self.replay.configure(text="停止试听")
            self.playback_timer = self.root.after(
                round(len(self.audio) * 1000 / SAMPLE_RATE) + 100, self.stop_playback)
        except Exception as exc:
            self.set_status(f"试听失败 · {exc}", RED)

    def stop_playback(self):
        if self.playback_timer is not None:
            self.root.after_cancel(self.playback_timer)
            self.playback_timer = None
        if self.playing:
            import sounddevice as sd
            try:
                sd.stop()
            except Exception as exc:
                self.set_status(f"停止试听失败 · {exc}", RED)
            finally:
                self.playing = False
                self.replay.configure(text="试听")

    def submit(self, name=None, *, reuse=False):
        if self.busy or not self.ready or (reuse and self.audio is None):
            return
        port = self.port.get().strip()
        if not port:
            self.set_status("请输入板卡 IP 和端口，或选择 COM8 / JTAG", RED)
            self.endpoint.focus_set()
            return
        baud = int(self.baud.get())
        self.stop_playback()
        self.tabs.select(self.overview)
        self.set_busy(True)
        self.keyword.set("—")
        for value in (self.board_time, self.total_time, self.prep_time, self.frequency):
            value.set("—")
        self.set_progress(0)
        for label, score, bar in self.scores:
            label.configure(text="—")
            score.configure(text="—")
            bar.configure(value=0)
        if reuse:
            source = (self.audio, self.audio_title, self.audio_truth)
            self.set_status("正在重新识别当前音频…")
        else:
            source = None
            if name is None or isinstance(name, Path):
                self.sample.set("")
                self.quick_list.selection_remove(*self.quick_list.selection())
            else:
                label = name.split("/", 1)[0]
                for index, quick in enumerate(self.quick_samples):
                    if quick.startswith(label + "/"):
                        self.quick_list.selection_set(str(index))
                        break
            self.set_status("正在录音，请说关键词…" if name is None else "正在读取 WAV 音频…")
        self.worker.submit(self.infer, name, port, baud, source)

    def infer(self, name, port, baud, source):
        start = time.perf_counter()
        stage = "音频处理"
        try:
            with connect_for_audio(port, baud) as acquire:
                if source is not None:
                    audio, title, truth = source
                elif name is None:
                    stage = "麦克风录音"
                    import sounddevice as sd
                    audio = sd.rec(SAMPLE_RATE, samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocking=True)[:, 0]
                    title, truth = "麦克风录音 · 1.00 秒", None
                elif isinstance(name, Path):
                    audio, title, truth = self.file_audio(name)
                else:
                    audio, truth = self.model.validation_audio(name)
                    title = name
                self.events.put(("audio", (audio, title, truth)))
                stage = "特征提取"
                features = self.model.encode(audio)
                prepared = time.perf_counter()
                self.events.put(("upload", None))
                stage = f"板卡通信 ({port})"
                result = acquire().infer(features, progress=lambda layer: self.events.put(("progress", layer)))
                self.events.put(("result", (result, (prepared - start) * 1000,
                                            (time.perf_counter() - start) * 1000, port)))
        except Exception as exc:
            self.events.put(("error", f"{stage}失败 · {exc}"))

    def set_busy(self, busy):
        self.busy = busy
        active = not busy and self.ready
        for widget in (self.choose, self.record, self.run):
            widget.configure(state="normal" if active else "disabled")
        for widget in (self.replay, self.again):
            widget.configure(state="normal" if active and self.audio is not None else "disabled")
        self.sample_menu.configure(state="readonly" if active else "disabled")
        self.quick_list.state(["!disabled" if active else "disabled"])
        self.endpoint.configure(state="disabled" if busy else "normal")
        self.export.configure(state="normal" if not busy and self.history else "disabled")
        self.monitor.available(active)
        self.update_rate()

    def set_progress(self, layer):
        self.layer_count.set(layer)
        self.progress_caption.configure(text=f"编码器  {layer} / 12 层")

    def draw_wave(self):
        width, height = self.wave.winfo_width(), self.wave.winfo_height()
        self.wave.delete("all")
        if width < 30 or height < 26:
            return
        radius = 12
        self.wave.create_polygon(radius, 1, width-radius, 1, width-1, 1, width-1, radius,
                                 width-1, height-radius, width-1, height-1, width-radius, height-1,
                                 radius, height-1, 1, height-1, 1, height-radius, 1, radius, 1, 1,
                                 smooth=True, splinesteps=16, fill="#e8eff6", outline=LINE)
        plot_height = height - 24
        if self.audio is None:
            self.wave.create_text(width / 2, height / 2, text="选择样本或录音后显示波形",
                                  fill=MUTED, font=(FONT, 10))
            return
        left, plot_width = 12, width - 24
        for tick in (0.25, 0.5, 0.75):
            x = left + plot_width * tick
            self.wave.create_line(x, 8, x, plot_height, fill="#d8e3ed")
        self.wave.create_line(left, plot_height / 2, left + plot_width, plot_height / 2, fill="#a7bdcf")
        bins = min(plot_width, len(self.audio), 640)
        if bins != self.wave_size:
            blocks = (self.audio[x * len(self.audio) // bins:(x + 1) * len(self.audio) // bins]
                      for x in range(bins))
            self.peaks = tuple((float(block.min()), float(block.max())) for block in blocks)
            self.wave_size = bins
        for index, (low, high) in enumerate(self.peaks):
            x = left + index * plot_width / bins
            self.wave.create_line(x, plot_height * (0.5 - 0.45 * high),
                                  x, plot_height * (0.5 - 0.45 * low), fill=BLUE)
        for tick, anchor in ((0, "w"), (0.5, "center"), (1, "e")):
            self.wave.create_text(left + tick * plot_width, height - 11, anchor=anchor,
                                  text=f"{tick:g} s", fill=MUTED, font=(FONT, 8))

    def show_result(self, result, prep_ms, total_ms, port):
        predicted = self.model.labels[result.label]
        self.keyword.set(predicted)
        exponentials = [math.exp(v - max(result.logits)) for v in result.logits]
        ranked = sorted(range(len(result.logits)), key=lambda i: result.logits[i], reverse=True)
        for (label, score, bar), index in zip(self.scores, ranked):
            percent = 100 * exponentials[index] / sum(exponentials)
            label.configure(text=self.model.labels[index])
            score.configure(text=f"{percent:.1f}%")
            bar.configure(value=percent)
        self.set_progress(12)
        board_ms = 1000 * result.cycles / result.frequency
        mhz = result.frequency / 1e6
        self.board_time.set(f"{board_ms:.1f} ms")
        self.total_time.set(f"{total_ms:.1f} ms")
        self.prep_time.set(f"{prep_ms:.1f} ms")
        self.frequency.set(f"{mhz:g} MHz")
        truth = self.model.labels[self.audio_truth] if self.audio_truth is not None else "—"
        row = (datetime.now().strftime("%H:%M:%S"), self.audio_title, truth, predicted,
               f"{prep_ms:.1f}", f"{board_ms:.1f}", f"{total_ms:.1f}", f"{mhz:g}", port)
        self.history.append(row)
        self.empty_history.place_forget()
        tags = ("alternate",) if len(self.history) % 2 == 0 else ()
        self.log.insert("", 0, values=row, tags=tags)
        self.log.yview_moveto(0)
        self.set_status(f"识别完成 · {port}", GREEN)
        self.set_busy(False)

    def poll(self):
        while True:
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "monitor":
                self.monitor.handle(*value)
            elif event == "ready":
                self.monitor.status.set("等待开始监听")
                self.ready = True
                self.sample_menu.configure(values=value)
                self.sample.set(next((name for name in value if name.startswith("yes/")), value[0]))
                first_samples = {}
                for name in value:
                    first_samples.setdefault(name.split("/", 1)[0], name)
                keywords = [label for label in self.model.labels if label in first_samples]
                self.quick_samples = [first_samples[label] for label in keywords]
                for index, label in enumerate(keywords):
                    self.quick_list.insert("", "end", iid=str(index), text=label)
                self.set_status("已就绪 · 选择样本、打开 WAV 或录音")
                self.set_busy(False)
            elif event == "error":
                self.set_status(value, RED)
                self.set_busy(False)
            elif event == "audio":
                self.audio, name, truth = value
                self.audio_title, self.audio_truth = name, truth
                self.wave_size = 0
                self.audio_name.set(name)
                self.truth.set("真实标签  —" if truth is None else f"真实标签  {self.model.labels[truth]}")
                self.draw_wave()
            elif event == "upload":
                self.set_status("正在连接板卡并发送特征…")
            elif event == "progress":
                self.set_progress(value)
                self.set_status("FPGA 正在执行 12 层编码器")
            elif event == "result":
                self.show_result(*value)
        self.root.after(8 if self.busy and self.ready else 40, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEMO_TCP)
    parser.add_argument("--baud", type=int, choices=[115200, 921600], default=DEMO_BAUD)
    parser.add_argument("--monitor", action="store_true", help="Open the realtime monitor tab")
    args = parser.parse_args()
    root = tk.Tk()
    app = Demo(root, args.port, args.baud)
    if args.monitor:
        app.tabs.select(app.monitor_tab)
    root.mainloop()


if __name__ == "__main__":
    main()
