# -*- coding: utf-8 -*-
"""系统托盘逻辑（右键菜单、还原/退出）"""

import threading
import tkinter as tk

from backend.config_manager import get_setting, set_setting

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ── 模块级状态 ──
_tray_icon = None
_should_exit = False
_handling_minimize = False

# 外部注入
_valley_scheduler = None


def set_valley_scheduler(scheduler):
    global _valley_scheduler
    _valley_scheduler = scheduler


def _create_tray_image():
    """生成托盘图标（64x64 红色K线风格）"""
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, 56, 56], fill=(178, 34, 34), outline=(128, 0, 0), width=2)
    draw.line([(20, 42), (30, 26), (38, 36), (48, 20)], fill=(255, 255, 255), width=4)
    return img


def _restore_window(window, icon, item=None):
    global _handling_minimize
    _handling_minimize = False
    window.deiconify()
    window.state('normal')
    window.lift()
    window.focus_force()


def _quit_app(window, icon, item=None):
    global _tray_icon, _should_exit, _valley_scheduler
    _should_exit = True
    if _tray_icon:
        _tray_icon.stop()
        _tray_icon = None
    try:
        if _valley_scheduler:
            _valley_scheduler.stop()
    except Exception:
        pass
    window.destroy()


def _hide_to_tray(window):
    if not HAS_TRAY:
        return
    window.withdraw()


def _show_close_dialog(window):
    """显示关闭行为选择对话框，返回用户选择的 action 或 None（取消）"""
    dialog = tk.Toplevel(window)
    dialog.title("关闭行为")
    dialog.geometry("380x220")
    dialog.resizable(False, False)
    dialog.transient(window)
    dialog.grab_set()

    dialog.update_idletasks()
    x = window.winfo_x() + (window.winfo_width() - 380) // 2
    y = window.winfo_y() + (window.winfo_height() - 220) // 2
    dialog.geometry(f"+{x}+{y}")

    last_action = get_setting("close_action") or "tray"
    action_var = tk.StringVar(value=last_action)
    dont_ask_var = tk.BooleanVar(value=False)
    result = {"action": None}

    tk.Label(dialog, text="点击关闭按钮后，程序将：", font=("Microsoft YaHei", 12)).pack(pady=(15, 10))

    fg = tk.Frame(dialog)
    fg.pack(pady=(0, 5))
    tk.Radiobutton(fg, text="最小化到系统托盘", variable=action_var, value="tray", font=("Microsoft YaHei", 11)).pack(anchor="w", pady=2)
    tk.Radiobutton(fg, text="退出应用", variable=action_var, value="exit", font=("Microsoft YaHei", 11)).pack(anchor="w", pady=2)

    tk.Checkbutton(dialog, text="不再提示", variable=dont_ask_var, font=("Microsoft YaHei", 10)).pack(pady=(5, 10))

    def on_cancel():
        dialog.destroy()

    def on_confirm():
        result["action"] = action_var.get()
        set_setting("close_action", result["action"])
        set_setting("close_dont_ask", "true" if dont_ask_var.get() else "false")
        dialog.destroy()

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=(5, 10))
    tk.Button(btn_frame, text="取消", width=10, command=on_cancel).pack(side="left", padx=10)
    tk.Button(btn_frame, text="确定", width=10, command=on_confirm, bg="#0078D4", fg="white").pack(side="left", padx=10)

    dialog.wait_window()
    return result["action"]


def _on_window_close(window):
    global _should_exit
    if _should_exit:
        _quit_app(window, None)
        return

    # 如果用户勾选了"不再提示"，直接按保存的行为执行
    if get_setting("close_dont_ask") == "true":
        action = get_setting("close_action")
        if action == "exit":
            _should_exit = True
            _quit_app(window, None)
        else:
            _hide_to_tray(window)
        return

    # 弹出选择对话框
    action = _show_close_dialog(window)

    if action == "exit":
        _should_exit = True
        _quit_app(window, None)
    elif action == "tray":
        _hide_to_tray(window)
    # action 为 None（取消）→ 窗口保持打开


def _on_unmap(window, event):
    global _handling_minimize, _should_exit
    if _handling_minimize or _should_exit:
        return
    if event.widget is window and window.state() == 'iconic':
        _handling_minimize = True
        _hide_to_tray(window)


def init_tray(window):
    """初始化系统托盘图标"""
    global _tray_icon
    if not HAS_TRAY:
        return
    if _tray_icon is not None:
        return
    menu = pystray.Menu(
        pystray.MenuItem('显示', lambda icon, item: _restore_window(window, icon, item), default=True),
        pystray.MenuItem('退出', lambda icon, item: _quit_app(window, icon, item)),
    )
    _tray_icon = pystray.Icon('bilidigest', _create_tray_image(), 'BiliDigest', menu)
    threading.Thread(target=_tray_icon.run, daemon=True).start()


def setup_window_tray_hooks(window):
    """设置窗口的关闭和最小化托盘钩子"""
    window.protocol('WM_DELETE_WINDOW', lambda: _on_window_close(window))
    if HAS_TRAY:
        window.bind('<Unmap>', lambda e: _on_unmap(window, e), add='+')

