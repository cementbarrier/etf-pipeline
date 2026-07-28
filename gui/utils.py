# -*- coding: utf-8 -*-
"""共享工具函数"""
import sys
import datetime as _dt
from pathlib import Path
from tkinter import BooleanVar, Checkbutton, Button, Frame, Label, Toplevel

from backend import config_manager


if getattr(sys, 'frozen', False):
    OUTPUT_PATH = Path(sys._MEIPASS)
    ASSETS_PATH = OUTPUT_PATH / "gui" / "build" / "assets" / "frame0"
else:
    OUTPUT_PATH = Path(__file__).parent
    ASSETS_PATH = OUTPUT_PATH / "assets" / "frame0"


def relative_to_assets(path: str) -> Path:
    return ASSETS_PATH / Path(path)


def center_window(window, width, height):
    window.update_idletasks()
    x = int((window.winfo_screenwidth() - width) / 2)
    y = int((window.winfo_screenheight() - height) / 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def create_rounded_rectangle(canvas, x1, y1, x2, y2, radius, **kwargs):
    radius = max(0, min(radius, abs(x2 - x1) / 2, abs(y2 - y1) / 2))
    if radius == 0:
        return canvas.create_rectangle(x1, y1, x2, y2, **kwargs)
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


# ── 调试日志 ──

def _get_debug_log_path():
    try:
        return config_manager.get_debug_log_path()
    except Exception:
        return Path.home() / "Desktop" / "stock_batch_debug.log"


def debug(msg):
    log_path = _get_debug_log_path()
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
    print(f"[{ts}] {msg}")


# ── 高峰弹窗辅助（含"今天不再提醒"复选框）──

_peak_suppressed_today = False


def peak_dialog(window, title="高峰时段提醒"):
    """返回 True=立即执行, 否则返回 False（此时应走入队延迟流程）"""
    global _peak_suppressed_today
    if _peak_suppressed_today:
        return True
    dialog = Toplevel(window)
    dialog.title(title)
    dialog.geometry("380x210")
    dialog.resizable(False, False)
    dialog.transient(window)
    dialog.grab_set()
    result = {"action": False, "suppress": False}

    Label(dialog, text="当前为 DeepSeek 高峰时段（双倍价）。",
          font=("Microsoft YaHei", 10), wraplength=340).pack(pady=(15, 5))
    Label(dialog, text="「是」正常付费，「否」18点后自动处理。",
          font=("Microsoft YaHei", 9), fg="gray").pack(pady=(0, 10))

    suppress_var = BooleanVar(value=False)
    Checkbutton(dialog, text="今天不再提醒", variable=suppress_var).pack(pady=(0, 10))

    btn_frame = Frame(dialog)
    btn_frame.pack(pady=(5, 10))

    def _do_yes():
        result["action"] = True
        result["suppress"] = suppress_var.get()
        dialog.destroy()

    def _do_no():
        result["action"] = False
        result["suppress"] = suppress_var.get()
        dialog.destroy()

    Button(btn_frame, text="立即执行（是）", command=_do_yes, width=15).pack(side="left", padx=10)
    Button(btn_frame, text="入队延迟（否）", command=_do_no, width=15).pack(side="left", padx=10)
    dialog.wait_window()
    if result["suppress"]:
        _peak_suppressed_today = True
    return result["action"]

