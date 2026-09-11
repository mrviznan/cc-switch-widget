"""CC Switch usage monitor with a compact floating-ball interface."""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from ctypes import wintypes
from decimal import Decimal
from queue import Empty, Queue
from typing import Any


def _prepare_tk_runtime() -> None:
    # PyInstaller's standard Tk hook sets absolute paths. On this machine
    # Tcl cannot resolve those paths when the Windows profile contains CJK
    # characters, while relative paths from the extraction directory work.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        os.chdir(sys._MEIPASS)
        os.environ["TCL_LIBRARY"] = "_tcl_data"
        os.environ["TK_LIBRARY"] = "_tk_data"


_prepare_tk_runtime()
import tkinter as tk
from tkinter import Menu

from cc_switch_quota import QuotaResult, query_quota
from cc_switch_reader import Provider, SessionUsage, Snapshot, read_snapshot


BG = "#14211d"
PANEL = "#1b2d27"
PANEL_EDGE = "#365047"
TEXT = "#f4efe4"
MUTED = "#a9b8ad"
ACCENT = "#d9a86c"
GOOD = "#9dcc8b"
ERROR = "#ef9b83"
TRANSPARENT = "#ff00ff"

BALL_SIZE = 76
DEFAULT_DETAIL_WIDTH = 320
DEFAULT_DETAIL_HEIGHT = 190
MIN_DETAIL_WIDTH = 270
MIN_DETAIL_HEIGHT = 175
RESIZE_BORDER = 8
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020


def format_compact_number(value: int) -> str:
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= threshold:
            number = value / threshold
            return f"{number:.1f}{suffix}" if number < 100 else f"{number:.0f}{suffix}"
    return str(value)


def format_cost(value: Decimal) -> str:
    return f"${value:,.4f}"


def format_balance(value: Any, unit: str) -> str:
    if isinstance(value, (int, float, Decimal)):
        return f"{unit} {Decimal(str(value)):,.2f}"
    return f"{value} {unit}".strip()


def format_ball_balance(quota: QuotaResult) -> tuple[str, str]:
    if quota.status != "ok" or quota.remaining is None:
        return "--", "余额"
    if isinstance(quota.remaining, (int, float, Decimal)):
        return f"{Decimal(str(quota.remaining)):,.2f}", quota.unit
    return str(quota.remaining)[:8], quota.unit


class UsageWidget:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CC Switch 使用监控")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)
        self.root.configure(bg=TRANSPARENT)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.geometry(f"{BALL_SIZE}x{BALL_SIZE}+30+120")
        self.root.resizable(False, False)
        self.root.bind("<FocusOut>", self._on_focus_out)
        self.root.bind("<Button-3>", self._show_menu)

        self._drag_offset = (0, 0)
        self._press_root = (0, 0)
        self._moved = False
        self._resize_edges: tuple[str, ...] = ()
        self._resize_origin: tuple[int, int, int, int] | None = None
        self._expanded = False
        self._detail_width = DEFAULT_DETAIL_WIDTH
        self._detail_height = DEFAULT_DETAIL_HEIGHT
        self._refresh_in_flight = False
        self._closed = False
        self._after_id: str | None = None
        self._focus_check_id: str | None = None
        self._result_queue: Queue[tuple[Snapshot, Provider | None, QuotaResult]] = Queue()

        self._build_ball()
        self._build_detail()
        self._apply_toolwindow_style()
        self.root.after(100, self._poll_results)
        self.refresh()

    def _apply_toolwindow_style(self) -> None:
        if not hasattr(ctypes, "windll"):
            return
        try:
            hwnd = wintypes.HWND(self.root.winfo_id())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
        except (AttributeError, OSError):
            pass

    def _build_ball(self) -> None:
        self.ball_canvas = tk.Canvas(
            self.root, width=BALL_SIZE, height=BALL_SIZE, highlightthickness=0,
            bd=0, bg=TRANSPARENT, cursor="hand2",
        )
        self.ball_canvas.pack(fill="both", expand=True)
        pad = 3
        self.ball_canvas.create_oval(
            pad, pad, BALL_SIZE - pad, BALL_SIZE - pad,
            fill=PANEL, outline=PANEL_EDGE, width=2, tags="ball",
        )
        self.ball_value = self.ball_canvas.create_text(
            BALL_SIZE // 2, 34, text="--", fill=ACCENT,
            font=("Segoe UI", 13, "bold"), tags="ball",
        )
        self.ball_unit = self.ball_canvas.create_text(
            BALL_SIZE // 2, 53, text="余额", fill=MUTED,
            font=("Segoe UI", 8), tags="ball",
        )
        self.ball_canvas.bind("<ButtonPress-1>", self._on_press)
        self.ball_canvas.bind("<B1-Motion>", self._on_drag_or_resize)
        self.ball_canvas.bind("<ButtonRelease-1>", self._on_release)
        self.ball_canvas.bind("<Button-3>", self._show_menu)

    def _build_detail(self) -> None:
        self.detail_shell = tk.Frame(
            self.root, bg=PANEL, highlightthickness=1,
            highlightbackground=PANEL_EDGE,
        )
        header = tk.Frame(self.detail_shell, bg=PANEL, height=34)
        header.pack(fill="x", padx=12, pady=(8, 0))
        header.pack_propagate(False)
        self.title_label = tk.Label(
            header, text="CC Switch · 使用监控", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 10, "bold"), anchor="w",
        )
        self.title_label.pack(side="left", fill="both", expand=True)
        self.refresh_button = tk.Button(
            header, text="刷新", command=self.refresh, relief="flat", bd=0,
            padx=8, pady=2, bg="#29443a", fg=TEXT,
            activebackground="#3a5a4b", activeforeground=TEXT,
            font=("Segoe UI", 9), cursor="hand2",
        )
        self.refresh_button.pack(side="left", padx=(4, 4))
        self.close_button = tk.Button(
            header, text="×", command=self.close, relief="flat", bd=0,
            padx=5, pady=0, bg=PANEL, fg=MUTED,
            activebackground=PANEL, activeforeground=TEXT,
            font=("Segoe UI", 14), cursor="hand2",
        )
        self.close_button.pack(side="right")

        body = tk.Frame(self.detail_shell, bg=PANEL)
        body.pack(fill="both", expand=True, padx=12, pady=(2, 8))
        self.provider_label = self._label(body, "读取中…", font=("Segoe UI", 10, "bold"), anchor="w")
        self.provider_label.pack(fill="x", pady=(0, 5))
        balance_row = tk.Frame(body, bg=PANEL)
        balance_row.pack(fill="x")
        self._label(balance_row, "剩余额度", fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(side="left")
        self.balance_label = self._label(balance_row, "读取中…", fg=ACCENT, font=("Segoe UI", 11, "bold"), anchor="e")
        self.balance_label.pack(side="right")
        self.session_label = self._label(body, "本次对话：读取中…", fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.session_label.pack(fill="x", pady=(6, 0))
        self.tokens_label = self._label(body, "Token：读取中…", fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.tokens_label.pack(fill="x", pady=(2, 0))
        self.status_label = self._label(body, "最后更新：读取中…", fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self.status_label.pack(fill="x", pady=(5, 0))
        self._bind_detail_interactions(self.detail_shell)

    def _label(self, parent: tk.Misc, text: str, **kwargs: Any) -> tk.Label:
        return tk.Label(parent, text=text, bg=kwargs.pop("bg", PANEL), fg=kwargs.pop("fg", TEXT), **kwargs)

    def _bind_detail_interactions(self, widget: tk.Misc) -> None:
        widget.bind("<Button-3>", self._show_menu, add="+")
        if not isinstance(widget, tk.Button):
            widget.bind("<ButtonPress-1>", self._on_press, add="+")
            widget.bind("<B1-Motion>", self._on_drag_or_resize, add="+")
            widget.bind("<ButtonRelease-1>", self._on_release, add="+")
            widget.bind("<Motion>", self._on_motion, add="+")
        for child in widget.winfo_children():
            self._bind_detail_interactions(child)

    def _set_expanded(self, expanded: bool) -> None:
        if self._closed or expanded == self._expanded:
            return
        self._expanded = expanded
        if expanded:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            self.root.configure(bg=PANEL)
            self.ball_canvas.pack_forget()
            self.detail_shell.pack(fill="both", expand=True)
            self.root.geometry(f"{self._detail_width}x{self._detail_height}+{x}+{y}")
            self.root.resizable(True, True)
            self.root.focus_force()
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            self._detail_width = max(MIN_DETAIL_WIDTH, self.root.winfo_width())
            self._detail_height = max(MIN_DETAIL_HEIGHT, self.root.winfo_height())
            self.detail_shell.pack_forget()
            self.root.configure(bg=TRANSPARENT)
            self.ball_canvas.pack(fill="both", expand=True)
            self.root.geometry(f"{BALL_SIZE}x{BALL_SIZE}+{x}+{y}")
            self.root.resizable(False, False)
        self._apply_toolwindow_style()

    def _on_focus_out(self, _event: tk.Event) -> None:
        if self._expanded and not self._closed:
            if self._focus_check_id:
                self.root.after_cancel(self._focus_check_id)
            self._focus_check_id = self.root.after(120, self._collapse_if_unfocused)

    def _collapse_if_unfocused(self) -> None:
        self._focus_check_id = None
        if self._expanded and self.root.focus_displayof() is None:
            self._set_expanded(False)

    def _on_motion(self, event: tk.Event) -> None:
        if not self._expanded:
            return
        root_x = event.x_root - self.root.winfo_rootx()
        root_y = event.y_root - self.root.winfo_rooty()
        edges = self._resize_edges_for(root_x, root_y)
        cursor = ""
        if edges in (("left", "top"), ("right", "bottom")):
            cursor = "size_nw_se"
        elif edges in (("right", "top"), ("left", "bottom")):
            cursor = "size_ne_sw"
        elif edges in (("left",), ("right",)):
            cursor = "size_we"
        elif edges in (("top",), ("bottom",)):
            cursor = "size_ns"
        self.root.configure(cursor=cursor)

    def _resize_edges_for(self, x: int, y: int) -> tuple[str, ...]:
        width, height = self.root.winfo_width(), self.root.winfo_height()
        edges: list[str] = []
        if x <= RESIZE_BORDER:
            edges.append("left")
        elif x >= width - RESIZE_BORDER:
            edges.append("right")
        if y <= RESIZE_BORDER:
            edges.append("top")
        elif y >= height - RESIZE_BORDER:
            edges.append("bottom")
        return tuple(edges)

    def _on_press(self, event: tk.Event) -> None:
        self._press_root = (event.x_root, event.y_root)
        self._moved = False
        if self._expanded:
            root_x = event.x_root - self.root.winfo_rootx()
            root_y = event.y_root - self.root.winfo_rooty()
            self._resize_edges = self._resize_edges_for(root_x, root_y)
            if self._resize_edges:
                self._resize_origin = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())
                return
        self._drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _on_drag_or_resize(self, event: tk.Event) -> None:
        if abs(event.x_root - self._press_root[0]) + abs(event.y_root - self._press_root[1]) > 5:
            self._moved = True
        if self._expanded and self._resize_edges and self._resize_origin:
            ox, oy, ow, oh = self._resize_origin
            x, y, width, height = ox, oy, ow, oh
            if "left" in self._resize_edges:
                x = min(event.x_root, ox + ow - MIN_DETAIL_WIDTH)
                width = max(MIN_DETAIL_WIDTH, ow - (x - ox))
            if "right" in self._resize_edges:
                width = max(MIN_DETAIL_WIDTH, ow + event.x_root - (ox + ow))
            if "top" in self._resize_edges:
                y = min(event.y_root, oy + oh - MIN_DETAIL_HEIGHT)
                height = max(MIN_DETAIL_HEIGHT, oh - (y - oy))
            if "bottom" in self._resize_edges:
                height = max(MIN_DETAIL_HEIGHT, oh + event.y_root - (oy + oh))
            self.root.geometry(f"{width}x{height}+{x}+{y}")
            return
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, _event: tk.Event) -> None:
        was_expanded = self._expanded
        self._resize_edges = ()
        self._resize_origin = None
        if not was_expanded and not self._moved:
            self._set_expanded(True)

    def _show_menu(self, event: tk.Event) -> None:
        menu = Menu(self.root, tearoff=False)
        menu.add_command(label="刷新", command=self.refresh)
        menu.add_command(label="收起悬浮球" if self._expanded else "展开详情", command=lambda: self._set_expanded(not self._expanded))
        menu.add_separator()
        menu.add_command(label="退出", command=self.close)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def refresh(self) -> None:
        if self._refresh_in_flight or self._closed:
            return
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._refresh_in_flight = True
        self.refresh_button.configure(state="disabled")
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self) -> None:
        try:
            snapshot = read_snapshot()
            quota = QuotaResult("unconfigured", message="余额查询未配置")
            provider: Provider | None = None
            if snapshot.latest_session and snapshot.latest_session.app_type in snapshot.providers:
                provider = snapshot.providers[snapshot.latest_session.app_type]
            elif snapshot.providers:
                provider = snapshot.providers.get("codex") or next(iter(snapshot.providers.values()))
            if provider is not None and snapshot.error is None:
                quota = query_quota(provider)
        except Exception as exc:  # Keep the UI responsive if a third-party script misbehaves.
            snapshot = Snapshot({}, None, f"读取组件数据失败：{exc}")
            provider = None
            quota = QuotaResult("error", message="余额查询失败")
        self._result_queue.put((snapshot, provider, quota))

    def _poll_results(self) -> None:
        if self._closed:
            return
        try:
            while True:
                self._apply_data(*self._result_queue.get_nowait())
        except Empty:
            pass
        self.root.after(100, self._poll_results)

    def _apply_data(self, snapshot: Snapshot, provider: Provider | None, quota: QuotaResult) -> None:
        if self._closed:
            return
        value, unit = format_ball_balance(quota)
        self.ball_canvas.itemconfigure(self.ball_value, text=value)
        self.ball_canvas.itemconfigure(self.ball_unit, text=unit)
        self._refresh_in_flight = False
        self.refresh_button.configure(state="normal")
        if snapshot.error:
            self.provider_label.configure(text="CC Switch 数据不可用", fg=ERROR)
            self.balance_label.configure(text="无法读取", fg=ERROR)
            self.session_label.configure(text="本次对话：暂无数据")
            self.tokens_label.configure(text=snapshot.error)
            self.status_label.configure(text="请确认 CC Switch 正在运行")
        else:
            app_name = {"codex": "Codex", "claude": "Claude"}
            if provider:
                provider_name = provider.name if len(provider.name) <= 24 else f"{provider.name[:23]}…"
                self.provider_label.configure(text=f"{app_name.get(provider.app_type, provider.app_type)} · {provider_name}", fg=TEXT)
            else:
                self.provider_label.configure(text="暂无当前供应商", fg=MUTED)
            if quota.status == "ok":
                self.balance_label.configure(text=format_balance(quota.remaining, quota.unit), fg=GOOD)
            else:
                self.balance_label.configure(text=quota.message, fg=ACCENT if quota.status == "unconfigured" else ERROR)
            self._apply_session(snapshot.latest_session)
            self.status_label.configure(text="最后更新：刚刚 · 下次自动刷新 60 秒")
        self._after_id = self.root.after(60_000, self.refresh)

    def _apply_session(self, session: SessionUsage | None) -> None:
        if session is None:
            self.session_label.configure(text="本次对话：暂无可识别会话")
            self.tokens_label.configure(text="Token：暂无数据")
            return
        self.session_label.configure(text=f"本次对话：{format_cost(session.total_cost_usd)} · {session.request_count} 次请求")
        self.tokens_label.configure(
            text=(
                f"Token：输入 {format_compact_number(session.input_tokens)} · 输出 {format_compact_number(session.output_tokens)} "
                f"· 缓存 {format_compact_number(session.cache_read_tokens + session.cache_creation_tokens)}"
            )
        )

    def close(self) -> None:
        self._closed = True
        if self._after_id:
            self.root.after_cancel(self._after_id)
        if self._focus_check_id:
            self.root.after_cancel(self._focus_check_id)
        self.root.destroy()


def main() -> None:
    # Re-apply this immediately before Tk is initialized. PyInstaller's
    # Tk runtime hook may run after module import and restore its absolute
    # paths, which are unreliable under a CJK Windows profile path.
    _prepare_tk_runtime()
    root = tk.Tk()
    UsageWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
