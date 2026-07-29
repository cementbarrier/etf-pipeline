"""
ETF Pipeline - 主 GUI 入口
统一 ETF 分析 + 视频解析 + 定期跟踪 + 配置管理
"""
import sys
import os as _os
from pathlib import Path

# ── 项目路径设置 ──
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── 代理禁用 ──
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    _os.environ[_key] = ""
_os.environ["NO_PROXY"] = "*"

import tkinter as tk
from tkinter import ttk, messagebox

from backend.config_manager import get_setting, set_setting, DEFAULTS
from gui.timeline import PipelineTimeline, PIPELINE_STEPS
from gui.pages.tray import init_tray, setup_window_tray_hooks, set_valley_scheduler


# ── 全局状态 ──
_pages = []
_sidebar_buttons = []
_timeline = None
_cfg_scrollbar = None
_valley_scheduler = None


def show_page(index: int):
    """切换标签页"""
    for i, btn in enumerate(_sidebar_buttons):
        btn.configure(bg="#D0D0D0" if i == index else "#EBEBEB")

    tab_names = ["etf", "parse", "batch", "config"]
    if _timeline:
        _timeline.set_mode(tab_names[min(index, len(tab_names) - 1)])
        _timeline.reset()

    for i, page in enumerate(_pages):
        if i == index:
            page.place(x=198, y=60, width=796, height=666)
        else:
            page.place_forget()

    # 配置页滚动条
    if index == 3:
        try:
            _window._config_ui and _window._config_ui.get('refresh_all') and _window._config_ui['refresh_all']()
        except: pass
    if index == 3 and _cfg_scrollbar is not None:
        _cfg_scrollbar.place(x=974, y=60, height=666)
    elif _cfg_scrollbar is not None:
        _cfg_scrollbar.place_forget()


def get_timeline():
    return _timeline


def get_window():
    return _window


# ── 创建主窗口 ──
_window = None


def create_main_window():
    global _window, _timeline, _cfg_scrollbar, _valley_scheduler

    _window = tk.Tk()
    _window.title("ETF Pipeline")
    _window.geometry("994x724")
    _window.configure(bg="#EBEBEB")
    _window.resizable(False, False)

    # 居中
    _window.update_idletasks()
    sw = _window.winfo_screenwidth()
    sh = _window.winfo_screenheight()
    x = (sw - 994) // 2
    y = (sh - 724) // 2
    _window.geometry(f"994x700+{x}+{y}")

    # ── 关闭行为 ──
    from gui.pages.tray import setup_window_tray_hooks
    setup_window_tray_hooks(_window)

    # ── 全局字体放大 ──
    style = ttk.Style()
    style.configure("TLabelframe.Label", font=("Microsoft YaHei", 14, "bold"))

    # ── 时间轴 ──
    _timeline = PipelineTimeline(_window)
    _timeline.place(x=0, y=0, width=994, height=60)

    # ── 侧边栏背景 ──
    sidebar_bg = tk.Frame(_window, bg="#EBEBEB", width=198, height=666,
                          highlightthickness=0)
    sidebar_bg.place(x=0, y=60)
    sidebar_bg.lower()

    sep = tk.Frame(_window, bg="#C8C8C8", width=1, height=666)
    sep.place(x=197, y=60)

    # ── 侧边栏标题 ──
    title_label = tk.Label(
        _window, text="ETF Pipeline",
        bg="#EBEBEB", fg="#000000",
        font=("Microsoft YaHei", 16, "bold"),
    )
    title_label.place(x=0, y=60 + 56, width=198, height=36)

    # ── 侧边栏导航按钮 ──
    tab_defs = [
        ("ETF分析", 0),
        ("视频解析", 1),
        ("定期跟踪", 2),
        ("配置", 3),
    ]

    base_y = 234
    for label, idx in tab_defs:
        btn = tk.Button(
            _window, text=label,
            bg="#D0D0D0" if idx == 0 else "#EBEBEB",
            fg="#000000",
            font=("Microsoft YaHei", 14, "normal"),
            borderwidth=0, highlightthickness=0,
            command=lambda i=idx: show_page(i),
            relief="flat", activebackground="#D0D0D0",
            cursor="hand2",
        )
        btn.place(x=8, y=base_y + idx * 122, width=183, height=40)
        _sidebar_buttons.append(btn)

    # ── 构建各页面 ──
    _build_etf_page()
    _build_parse_page()
    _build_batch_page()
    _build_config_page()

    # ── 默认显示 ETF 分析页 ──
    show_page(0)

    # ── 托盘 ──
    from backend import valley_scheduler as vs
    _valley_scheduler = vs
    set_valley_scheduler(vs)

    from gui.pages.tray import init_tray
    init_tray(_window)

    return _window


def _build_etf_page():
    """构建 ETF 分析页面（Canvas 滚动）"""
    from gui.pages.page_etf import build_page_etf
    frame = tk.Frame(_window, bg="#FFFFFF", borderwidth=0, highlightthickness=0)
    canvas = tk.Canvas(frame, bg="#FFFFFF", highlightthickness=0)
    scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg="#FFFFFF")
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    def _on_inner_configure(event):
        b = canvas.bbox("all")
        canvas.configure(scrollregion=(b[0], b[1], b[2], b[3] + 200) if b else (0, 0, 0, 0))
    inner.bind("<Configure>", _on_inner_configure)
    def _on_canvas_configure(event):
        canvas.itemconfig(win_id, width=event.width)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.configure(yscrollcommand=scrollbar.set)
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    def _bind_wheel(event):
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
    def _unbind_wheel(event):
        canvas.unbind_all("<MouseWheel>")
    canvas.bind("<Enter>", _bind_wheel)
    canvas.bind("<Leave>", _unbind_wheel)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    _pages.append(frame)
    _, ui = build_page_etf(_window, inner)
    _window._etf_ui = ui


def _build_parse_page():
    """构建视频解析页面"""
    from gui.pages.page_parse import build_page_parse
    frame = tk.Frame(_window, bg="#FFFFFF", borderwidth=0, highlightthickness=0)
    _pages.append(frame)
    build_page_parse(_window, frame)


def _build_batch_page():
    """构建定期跟踪页面（Canvas 滚动）"""
    from gui.pages.page_batch import build_page_batch
    frame = tk.Frame(_window, bg="#FFFFFF", borderwidth=0, highlightthickness=0)
    canvas = tk.Canvas(frame, bg="#FFFFFF", highlightthickness=0)
    scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg="#FFFFFF")
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    def _on_inner_configure(event):
        b = canvas.bbox("all")
        canvas.configure(scrollregion=(b[0], b[1], b[2], b[3] + 200) if b else (0, 0, 0, 0))
    inner.bind("<Configure>", _on_inner_configure)
    def _on_canvas_configure(event):
        canvas.itemconfig(win_id, width=event.width)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.configure(yscrollcommand=scrollbar.set)
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    def _bind_wheel(event):
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
    def _unbind_wheel(event):
        canvas.unbind_all("<MouseWheel>")
    canvas.bind("<Enter>", _bind_wheel)
    canvas.bind("<Leave>", _unbind_wheel)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    _pages.append(frame)
    build_page_batch(_window, inner)


def _build_config_page():
    """构建配置页面"""
    global _cfg_scrollbar
    from gui.pages.page_config import build_page_config
    scroll_frame, ui = build_page_config(_window, None, _window)
    _pages.append(scroll_frame)
    _cfg_scrollbar = ui.get("v_scrollbar_3")
    _window._config_ui = ui


# ── 启动 ──
if __name__ == "__main__":
    _window = create_main_window()

    # 单实例锁
    _lock_path = Path(_os.environ.get("TEMP", ".")) / "etf_pipeline_instance.lock"
    try:
        import msvcrt
        _lock_fd = _os.open(str(_lock_path), _os.O_CREAT | _os.O_RDWR, 0o644)
        try:
            msvcrt.locking(_lock_fd, msvcrt.LK_NBLCK, 1)
        except _os.error:
            _os.close(_lock_fd)
            messagebox.showwarning("ETF Pipeline", "程序已在运行中（可能隐藏在托盘区）")
            sys.exit(0)
    except Exception:
        pass

    # 启动低谷调度器
    if _valley_scheduler:
        _valley_scheduler.start(
            callback=lambda n: _window.after(0, lambda: None)
        )

    _window.mainloop()
