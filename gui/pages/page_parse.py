# -*- coding: utf-8 -*-
"""单视频解析页（包含 step1-5 按钮、进度条、输出框）"""

import sys
import threading
from pathlib import Path
from threading import Event

if getattr(sys, 'frozen', False):
    pass
else:
    _project_root = Path(__file__).parent.parent.parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

from tkinter import (
    Button, Canvas, Entry, Label, ttk, messagebox, filedialog,
)
from backend.single_parser import parse_single
from backend import config_manager, time_price_judge, single_summary_client, task_queue_manager

from gui.utils import create_rounded_rectangle, debug, peak_dialog
from gui.timeline import get_timeline as _get_timeline

# ── 模块级状态 ──
selected_save_path = config_manager.get_setting("parse_save_path")
cancel_event_1 = Event()
cancel_event_summary = Event()
last_parsed_bvid = ""
last_transcript_path_var = ""

# 外部注入的回调
_gui_refresh_queue = None
_window = None


def set_refresh_callback(cb):
    global _gui_refresh_queue
    _gui_refresh_queue = cb


def button_3_clicked(canvas_page_1, entry_single_path_text):
    global selected_save_path
    path = filedialog.askdirectory(title="选择保存路径")
    if path:
        selected_save_path = path
        config_manager.set_setting("parse_save_path", path)
        canvas_page_1.itemconfigure(entry_single_path_text,
            text=path[:40] + "..." if len(path) > 40 else path)
        debug(f"保存路径已选: {path}")


def _do_summary(window, summary_result_1, summary_btn_1, price_label_1):
    global last_parsed_bvid, last_transcript_path_var, cancel_event_summary
    if not last_parsed_bvid or not last_transcript_path_var:
        return
    cancel_event_summary.clear()

    try:
        with open(last_transcript_path_var, "r", encoding="utf-8") as f:
            transcript = f.read()
    except Exception as e:
        summary_result_1.config(text=f"读取字幕失败: {e}")
        summary_result_1.place(x=30, y=432, width=585, height=60)
        return

    if time_price_judge.is_peak():
        result = peak_dialog(window)
        if not result:
            task_id = single_summary_client.summarize_single(
                last_parsed_bvid, transcript, force=False
            )
            if _gui_refresh_queue:
                _gui_refresh_queue()
            summary_result_1.config(
                text=f"已加入延迟队列（{task_id.get('task_id', '?')}），"
                     f"低谷时段自动生成摘要。\n队列待处理: {task_queue_manager.get_pending_count()} 条"
            )
            summary_result_1.place(x=30, y=432, width=585, height=60)
            return

    summary_btn_1.config(text="生成中...", state="disabled")
    summary_result_1.config(text="正在调用大模型...")
    summary_result_1.place(x=30, y=432, width=585, height=60)

    tl = _get_timeline()
    if tl:
        window.after(0, tl.highlight, "summary")

    def run():
        if cancel_event_summary.is_set():
            return
        res = single_summary_client.summarize_single(
            last_parsed_bvid, transcript, force=True
        )
        if cancel_event_summary.is_set():
            return
        if res.get("status") == "done":
            window.after(0, lambda: _show_summary(res["summary"]))
            if tl:
                window.after(0, lambda: tl.set_step_status("summary", "done"))
        else:
            window.after(0, lambda: _show_summary(f"错误: {res.get('error', '未知')}"))
            if tl:
                window.after(0, lambda: tl.set_step_status("summary", "error"))

    def _show_summary(text):
        if cancel_event_summary.is_set():
            return
        summary_btn_1.config(text="生成 AI 摘要", state="normal")
        summary_result_1.config(text=text)
        summary_result_1.place(x=30, y=432, width=585, height=60)
        try:
            from backend.feishu_notifier import notify_single_done, send_transcript_text
            notify_single_done()
            if last_transcript_path_var:
                with open(last_transcript_path_var, "r", encoding="utf-8") as _f:
                    send_transcript_text(_f.read())
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def _finish_parse_1(window, success, msg, bv="", path="",
                    progress_label_1=None, progress_bar_1=None, button_stop_1=None,
                    button_4=None, summary_result_1=None, summary_btn_1=None,
                    price_label_1=None):
    global last_parsed_bvid, last_transcript_path_var, cancel_event_summary
    if progress_bar_1:
        progress_bar_1.place_forget()
    if button_stop_1:
        button_stop_1.place_forget()
    if progress_label_1:
        progress_label_1.configure(text=f"  {'✅' if success else '❌'} {msg}")
    if button_4:
        button_4.place(x=376, y=91, width=80, height=30)

    if summary_result_1:
        summary_result_1.config(text="")
        summary_result_1.place_forget()

    if not success:
        cancel_event_summary.set()
        if summary_btn_1:
            summary_btn_1.place_forget()
        if price_label_1:
            price_label_1.place_forget()

    if success and bv and path:
        last_parsed_bvid = bv
        last_transcript_path_var = path
        try:
            from backend.feishu_notifier import notify_single_done, send_transcript_text
            threading.Thread(target=notify_single_done, daemon=True).start()
            if path:
                with open(path, "r", encoding="utf-8") as _f:
                    _transcript = _f.read()
                threading.Thread(target=send_transcript_text, args=(_transcript,), daemon=True).start()
        except Exception:
            pass
        if price_label_1:
            from backend.time_price_judge import get_price_label
            price_label_1.config(text=f"  当前: {get_price_label()}")
            price_label_1.place(x=172, y=370, width=300, height=18)
        if summary_btn_1:
            summary_btn_1.place(x=232, y=390, width=180, height=36)


def button_4_clicked(window, entry_1, selected_save_path_getter,
                     progress_label_1, progress_bar_1, button_stop_1, button_4,
                     summary_result_1, summary_btn_1, price_label_1):
    global cancel_event_1, cancel_event_summary
    url = entry_1.get().strip()
    if not url or url == "Search...":
        messagebox.showwarning("提示", "请先输入视频链接")
        return
    save_path = selected_save_path_getter()
    if not save_path:
        messagebox.showwarning("提示", "请先选择保存路径")
        return

    cancel_event_summary.set()
    cancel_event_1.clear()

    summary_result_1.place_forget()
    summary_result_1.config(text="")
    summary_btn_1.place_forget()
    price_label_1.place_forget()

    button_4.place_forget()
    progress_label_1.configure(text="  正在初始化... 0%")
    progress_label_1.place(x=30, y=260, width=585, height=18)
    progress_label_1.tkraise()
    progress_bar_1.configure(value=0, maximum=100, mode="determinate")
    progress_bar_1.place(x=30, y=282, width=500, height=14)
    progress_bar_1.tkraise()
    button_stop_1.configure(command=lambda: cancel_event_1.set())
    button_stop_1.place(x=540, y=280, width=75, height=20)
    button_stop_1.tkraise()

    tl = _get_timeline()
    if tl:
        window.after(0, tl.reset)
        window.after(0, tl.highlight, "fetch")

    _tl_seen = set()
    _tl_done = set()
    _prev_stage = None

    def run():
        try:
            def progress_cb(ptype, msg, pct=0):
                nonlocal _prev_stage
                window.after(0, lambda: progress_label_1.configure(text=f"  {msg}"))
                window.after(0, lambda: progress_bar_1.configure(value=pct))

                # ── 时间轴更新（逐阶段标记完成） ──
                if tl:
                    detected = None
                    if "下载" in msg:
                        detected = "fetch"
                    elif "音频" in msg or "提取" in msg:
                        detected = "audio"
                    elif "转写" in msg:
                        detected = "transcribe"
                    if detected and detected != _prev_stage:
                        if _prev_stage and _prev_stage not in _tl_done:
                            _tl_done.add(_prev_stage)
                            window.after(0, tl.set_step_status, _prev_stage, "done")
                        if detected not in _tl_seen:
                            _tl_seen.add(detected)
                            window.after(0, tl.highlight, detected)
                        _prev_stage = detected
                    if ptype == "done":
                        if _prev_stage and _prev_stage not in _tl_done:
                            _tl_done.add(_prev_stage)
                            window.after(0, tl.set_step_status, _prev_stage, "done")
                        window.after(0, lambda: tl.set_step_status("transcribe", "done"))
                    elif ptype == "error":
                        window.after(0, lambda: tl.set_step_status("transcribe", "error"))
                    elif ptype == "cancelled":
                        window.after(0, lambda: tl.set_step_status("transcribe", "error"))

                if ptype == "done":
                    window.after(0, lambda: _finish_parse_1(
                        window, True, msg,
                        progress_label_1=progress_label_1,
                        progress_bar_1=progress_bar_1,
                        button_stop_1=button_stop_1,
                        button_4=button_4,
                        summary_result_1=summary_result_1,
                        summary_btn_1=summary_btn_1,
                        price_label_1=price_label_1))
                elif ptype == "error":
                    window.after(0, lambda: _finish_parse_1(
                        window, False, msg,
                        progress_label_1=progress_label_1,
                        progress_bar_1=progress_bar_1,
                        button_stop_1=button_stop_1,
                        button_4=button_4,
                        summary_result_1=summary_result_1,
                        summary_btn_1=summary_btn_1,
                        price_label_1=price_label_1))
                elif ptype == "cancelled":
                    window.after(0, lambda: _finish_parse_1(
                        window, False, msg,
                        progress_label_1=progress_label_1,
                        progress_bar_1=progress_bar_1,
                        button_stop_1=button_stop_1,
                        button_4=button_4,
                        summary_result_1=summary_result_1,
                        summary_btn_1=summary_btn_1,
                        price_label_1=price_label_1))
            result = parse_single(url, save_path, callback=progress_cb, cancel_event=cancel_event_1)
            if result.get("skipped"):
                window.after(0, lambda bv=url: _finish_parse_1(
                    window, True, "已有转写文件，已跳过", bv=bv,
                    progress_label_1=progress_label_1,
                    progress_bar_1=progress_bar_1,
                    button_stop_1=button_stop_1,
                    button_4=button_4,
                    summary_result_1=summary_result_1,
                    summary_btn_1=summary_btn_1,
                    price_label_1=price_label_1))
            elif result.get("success"):
                parsed_path = result.get("path", "")
                window.after(0, lambda bv=url, p=parsed_path: _finish_parse_1(
                    window, True, "字幕已保存", bv=bv, path=p,
                    progress_label_1=progress_label_1,
                    progress_bar_1=progress_bar_1,
                    button_stop_1=button_stop_1,
                    button_4=button_4,
                    summary_result_1=summary_result_1,
                    summary_btn_1=summary_btn_1,
                    price_label_1=price_label_1))
            else:
                if result.get("error") != "用户取消了解析":
                    window.after(0, lambda: _finish_parse_1(
                        window, False, result.get("error", "解析失败"),
                        progress_label_1=progress_label_1,
                        progress_bar_1=progress_bar_1,
                        button_stop_1=button_stop_1,
                        button_4=button_4,
                        summary_result_1=summary_result_1,
                        summary_btn_1=summary_btn_1,
                        price_label_1=price_label_1))
        except Exception as e:
            window.after(0, lambda: _finish_parse_1(
                window, False, str(e),
                progress_label_1=progress_label_1,
                progress_bar_1=progress_bar_1,
                button_stop_1=button_stop_1,
                button_4=button_4,
                summary_result_1=summary_result_1,
                summary_btn_1=summary_btn_1,
                price_label_1=price_label_1))

    threading.Thread(target=run, daemon=True).start()


def get_entry_1_text(entry_1):
    return entry_1.get("1.0", "end-1c") if hasattr(entry_1, 'get') and callable(entry_1.get) else entry_1.get()


def build_page_parse(window, parent):
    """构建单视频解析页，返回 (page_frame, ui_elements_dict)"""
    global _window
    _window = window

    page_frame = parent

    canvas_page_1 = Canvas(
        page_frame,
        bg="#FFFFFF",
        height=666,
        width=796,
        bd=0,
        highlightthickness=0,
        relief="ridge"
    )
    canvas_page_1.place(x=0, y=0)

    canvas_page_1.create_text(
        30, 190, anchor="nw",
        text="保存于", fill="#000000",
        font=("Inter", 16 * -1, "normal")
    )

    canvas_page_1.create_text(
        30, 69, anchor="nw",
        text="视频BV号", fill="#000000",
        font=("Inter", 16 * -1, "normal")
    )

    canvas_page_1.create_rectangle(
        30, 214, 370, 240,
        fill="#F0F0F0", outline="#cfcece")

    initial_path = selected_save_path
    display_path = (initial_path[:40] + "..." if len(initial_path) > 40 else initial_path) if initial_path else ""
    entry_single_path_text = canvas_page_1.create_text(
        34, 216, anchor="nw",
        text=display_path, fill="#888888",
        font=("Inter", 12 * -1, "normal")
    )

    browse_btn = Button(
        page_frame,
        text="浏览",
        bg="#E0E0E0", fg="#000000",
        font=("Inter", 12, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: button_3_clicked(canvas_page_1, entry_single_path_text),
        relief="flat", activebackground="#D0D0D0", cursor="hand2"
    )
    browse_btn.place(x=376, y=212, width=80, height=30)

    entry_1 = Entry(
        page_frame,
        bd=0, bg="#FFFFFF", fg="#828282",
        insertbackground="#828282",
        highlightthickness=0, font=("Inter", 14)
    )
    entry_1.insert(0, "Search...")
    entry_1.bind("<FocusIn>", lambda e: e.widget.delete(0, "end") if e.widget.get() == "Search..." else None)
    entry_1.bind("<FocusOut>", lambda e: e.widget.insert(0, "Search...") if not e.widget.get() else None)
    entry_1.place(x=30, y=91, width=334, height=40)

    # 进度区域
    progress_label_1 = Label(
        page_frame, text="", fg="#555555", bg="#FFFFFF",
        font=("Inter", 11), anchor="w"
    )
    progress_label_1.place(x=30, y=260, width=585, height=18)
    progress_label_1.place_forget()

    progress_bar_1 = ttk.Progressbar(page_frame, mode="determinate", length=500)
    progress_bar_1.place(x=30, y=282, width=500, height=14)
    progress_bar_1.place_forget()

    button_stop_1 = Button(
        page_frame, text="停止", bg="#F44336", fg="#FFFFFF",
        font=("Inter", 11, "normal"), borderwidth=0, highlightthickness=0,
        relief="flat", activebackground="#D32F2F", cursor="hand2"
    )
    button_stop_1.place(x=540, y=280, width=75, height=20)
    button_stop_1.place_forget()

    # 价格标签
    from backend.time_price_judge import get_price_label
    price_label_1 = Label(
        page_frame, text=f"  当前: {get_price_label()}",
        fg="#FF5722" if "高峰" in get_price_label() else "#4CAF50",
        bg="#FFFFFF", font=("Inter", 12), anchor="w"
    )

    # 摘要结果
    summary_result_1 = Label(
        page_frame, text="", fg="#333333", bg="#F5F5F5",
        font=("Inter", 12), anchor="nw", wraplength=570, justify="left",
        cursor="hand2"
    )

    def _copy_summary_to_clipboard(event):
        text = summary_result_1.cget("text")
        if text:
            window.clipboard_clear()
            window.clipboard_append(text)

    summary_result_1.bind("<Button-1>", _copy_summary_to_clipboard)

    # 解析按钮
    button_4 = Button(
        page_frame,
        text="解析",
        bg="#E0E0E0", fg="#000000",
        font=("Inter", 12, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: button_4_clicked(
            window, entry_1, lambda: selected_save_path,
            progress_label_1, progress_bar_1, button_stop_1, button_4,
            summary_result_1, summary_btn_1, price_label_1),
        relief="flat", activebackground="#D0D0D0", cursor="hand2"
    )
    button_4.place(x=376, y=91, width=80, height=30)

    # 摘要按钮
    summary_btn_1 = Button(
        page_frame, text="生成 AI 摘要",
        command=lambda: _do_summary(window, summary_result_1, summary_btn_1, price_label_1),
        bg="#2196F3", fg="#FFFFFF", font=("Inter", 14, "normal"),
        borderwidth=0, highlightthickness=0,
        relief="flat", activebackground="#1976D2", cursor="hand2"
    )

    ui = {
        "page_frame": page_frame,
        "canvas_page_1": canvas_page_1,
        "entry_single_path_text": entry_single_path_text,
        "entry_1": entry_1,
        "button_4": button_4,
        "browse_btn": browse_btn,
        "progress_label_1": progress_label_1,
        "progress_bar_1": progress_bar_1,
        "button_stop_1": button_stop_1,
        "price_label_1": price_label_1,
        "summary_result_1": summary_result_1,
        "summary_btn_1": summary_btn_1,
    }
    return page_frame, ui

