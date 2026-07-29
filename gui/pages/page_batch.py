# -*- coding: utf-8 -*-
"""批量解析页（UP 列表、日期选择、批量按钮、高峰弹窗）"""

import sys
import threading
import datetime as _dt
import time as _time

from pathlib import Path
from threading import Event

if getattr(sys, 'frozen', False):
    pass
else:
    _project_root = Path(__file__).parent.parent.parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

from tkinter import (
    Button, Entry, Frame, Label, Listbox, StringVar, Toplevel, ttk, messagebox, filedialog,
)

from backend.batch_parser import batch_parse
from backend.up_manager import load_up_list, save_up_list, fetch_up_name
from backend import config_manager, time_price_judge, task_queue_manager

from gui.utils import debug, peak_dialog
from gui.timeline import get_timeline

# ── 模块级状态 ──
batch_save_path = config_manager.get_setting("batch_save_path")
cancel_event_2 = Event()
today = _dt.date.today()
yesterday = today - _dt.timedelta(days=1)
_selected_target_dates = [yesterday.strftime("%Y-%m-%d")]
_date_popup = None

# 外部注入
_gui_refresh_queue = None
_window = None


def set_refresh_callback(cb):
    global _gui_refresh_queue
    _gui_refresh_queue = cb


# ── Treeview 交互逻辑 ──

def reapply_treeview_tags(treeview_1):
    for idx, item in enumerate(treeview_1.get_children()):
        tag = "evenrow" if idx % 2 == 0 else "oddrow"
        treeview_1.item(item, tags=(tag,))


def toggle_checkbox(treeview_1, event):
    region = treeview_1.identify("region", event.x, event.y)
    if region != "cell":
        return
    column = treeview_1.identify_column(event.x)
    if column != "#1":
        return
    iid = treeview_1.identify_row(event.y)
    if not iid:
        return
    current = treeview_1.set(iid, "选中")
    if current == "☑":
        treeview_1.set(iid, "选中", "☐")
    else:
        treeview_1.set(iid, "选中", "☑")


def toggle_select_all(treeview_1, event=None):
    all_items = treeview_1.get_children()
    if not all_items:
        return
    all_checked = all(treeview_1.set(item, "选中") == "☑" for item in all_items)
    new_state = "☐" if all_checked else "☑"
    for item in all_items:
        treeview_1.set(item, "选中", new_state)


def on_double_click_edit(treeview_1, treeview_1_cols, window, event):
    region = treeview_1.identify("region", event.x, event.y)
    if region != "cell":
        return
    column = treeview_1.identify_column(event.x)
    if column == "#1":
        return
    iid = treeview_1.identify_row(event.y)
    if not iid:
        return

    col_index = int(column[1:]) - 1
    col_name = treeview_1_cols[col_index]

    bbox = treeview_1.bbox(iid, column)
    if not bbox:
        return
    x_cell, y_cell, w_cell, h_cell = bbox

    current_value = treeview_1.set(iid, col_name)

    edit_entry = Entry(
        treeview_1,
        font=("Inter", 13),
        bd=1, relief="solid", justify="center"
    )
    edit_entry.place(x=x_cell, y=y_cell, width=w_cell, height=h_cell)
    edit_entry.insert(0, current_value)
    edit_entry.select_range(0, "end")
    edit_entry.focus_set()

    _editing_done = False

    def save_edit(event=None):
        nonlocal _editing_done
        if _editing_done:
            return
        _editing_done = True
        new_value = edit_entry.get()
        values = list(treeview_1.item(iid, "values"))
        values[col_index] = new_value
        treeview_1.item(iid, values=values)
        edit_entry.destroy()
        if col_index == 1 and new_value.strip() and not values[2]:
            debug(f"自动补全触发: {new_value.strip()}")
            _auto_fill_name(treeview_1, iid, new_value.strip(), window)

    edit_entry.bind("<Return>", save_edit)
    edit_entry.bind("<FocusOut>", save_edit)


def add_new_row(treeview_1):
    all_items = treeview_1.get_children()
    idx = len(all_items)
    tag = "evenrow" if idx % 2 == 0 else "oddrow"
    treeview_1.insert("", "end", values=["☐", "", ""], tags=(tag,))


def _auto_fill_name(treeview_1, iid, uid, window):
    def fetch():
        try:
            name = fetch_up_name(uid)
            if name:
                window.after(0, lambda: _set_name(treeview_1, iid, name))
            else:
                debug(f"自动补全: {uid} 未查到昵称")
        except Exception as e:
            debug(f"自动补全失败: {uid} -> {e}")
    threading.Thread(target=fetch, daemon=True).start()


def _set_name(treeview_1, iid, name):
    values = list(treeview_1.item(iid, "values"))
    values[2] = name
    treeview_1.item(iid, values=values)


def delete_selected(treeview_1):
    to_delete = []
    for item in treeview_1.get_children():
        if treeview_1.set(item, "选中") == "☑":
            to_delete.append(item)

    if not to_delete:
        messagebox.showinfo("提示", "没有选中任何行")
        return

    if not messagebox.askyesno("确认删除", f"确定删除选中的 {len(to_delete)} 行吗？"):
        return

    for item in to_delete:
        treeview_1.delete(item)
    reapply_treeview_tags(treeview_1)


# ── 按钮回调 ──

def button_batch_browse_clicked(path_var):
    global batch_save_path
    path = filedialog.askdirectory(title="选择批量解析保存路径")
    if path:
        batch_save_path = path
        config_manager.set_setting("batch_save_path", path)
        debug(f"批量保存路径已选: {path}")
        path_var.set(path[:40] + "..." if len(path) > 40 else path)


def button_6_clicked(treeview_1):
    rows = []
    for item in treeview_1.get_children():
        uid = treeview_1.set(item, "uid")
        name = treeview_1.set(item, "昵称")
        weight = 1 if treeview_1.set(item, "选中") == "☑" else 0
        if uid:
            rows.append({"uid": uid, "name": name, "weight": weight})
    debug(f"保存按钮: 共 {len(rows)} 位UP主待保存")
    try:
        save_up_list(rows)
        debug(f"已保存 {len(rows)} 位UP主到Excel")
        messagebox.showinfo("保存成功", f"已保存 {len(rows)} 位UP主")
    except Exception as e:
        debug(f"保存失败: {e}")
        messagebox.showerror("保存失败", str(e))


def _update_progress_2(progress_label_2, progress_bar_2, msg, pct):
    progress_label_2.configure(text=f"  {msg}")
    progress_bar_2.configure(value=pct)


def _finish_parse_2(window, success, msg, progress_bar_2, button_stop_2,
                    progress_label_2, button_5, progress_row_bottom):
    progress_bar_2.pack_forget()
    button_stop_2.pack_forget()
    progress_row_bottom.pack_forget()
    progress_label_2.configure(text=f"  {'✅' if success else '❌'} {msg}")
    button_5.config(state="normal", fg="#FFFFFF")


def button_5_clicked(window, treeview_1,
                     progress_label_2, progress_bar_2, button_stop_2, button_5,
                     progress_row_bottom):
    global cancel_event_2
    try:
        debug("button_5 CLICKED")
        if not batch_save_path:
            messagebox.showwarning("提示", "请先选择保存路径")
            return

        selected_uids = []
        for item in treeview_1.get_children():
            if treeview_1.set(item, "选中") == "☑":
                uid = treeview_1.set(item, "uid")
                if uid:
                    selected_uids.append(uid)

        if not selected_uids:
            messagebox.showwarning("提示", "没有选中任何UP主")
            return

        target_dates = list(_selected_target_dates)
        debug(f"batch_parse target_dates: {target_dates}")

        if time_price_judge.is_peak():
            result = peak_dialog(window)
            if not result:
                for target_date in target_dates:
                    task_id = task_queue_manager.enqueue(
                        task_type="batch_parse",
                        payload={
                            "uid_list": selected_uids,
                            "save_dir": batch_save_path,
                            "target_date": target_date,
                        },
                    )
                if _gui_refresh_queue:
                    _gui_refresh_queue()
                messagebox.showinfo(
                    "已加入延迟队列",
                    f"定期跟踪（{len(target_dates)} 个日期）已加入低谷延迟队列。\n"
                    f"队列待处理: {task_queue_manager.get_pending_count()} 条"
                )
                return

        cancel_event_2.clear()

        tl = get_timeline()
        if tl:
            window.after(0, tl.reset)
            window.after(0, tl.highlight, "fetch")

        _tl_seen = set()

        button_5.config(state="disabled", fg="#AAAAAA")
        progress_label_2.configure(text=f"  准备处理 {len(selected_uids)} 个UP主 × {len(target_dates)} 天... 0%")
        progress_label_2.pack(fill="x", padx=(0, 4))
        progress_row_bottom.pack(fill="x", pady=(2, 0))
        progress_bar_2.pack(side="left", fill="x", expand=True, padx=(0, 4))
        button_stop_2.configure(command=lambda: cancel_event_2.set())
        button_stop_2.pack(side="right")

        def run():
            total_dates = len(target_dates)
            total_success = 0
            total_failed = 0
            total_videos = 0

            def progress_callback(ptype, msg, pct=0):
                # ── 时间轴更新 ──
                if tl:
                    if "下载" in msg and "fetch" not in _tl_seen:
                        _tl_seen.add("fetch"); window.after(0, tl.highlight, "fetch")
                    elif ("音频" in msg or "提取" in msg) and "audio" not in _tl_seen:
                        _tl_seen.add("audio"); window.after(0, tl.highlight, "audio")
                    elif "转写" in msg and "transcribe" not in _tl_seen:
                        _tl_seen.add("transcribe"); window.after(0, tl.highlight, "transcribe")
                    if ptype == "done":
                        window.after(0, lambda: tl.set_step_status("transcribe", "done"))
                    elif ptype == "error":
                        window.after(0, lambda: tl.set_step_status("transcribe", "error"))
                    elif ptype == "cancelled":
                        window.after(0, lambda: tl.set_step_status("transcribe", "error"))

                if ptype == "progress":
                    window.after(0, lambda m=msg, p=pct: _update_progress_2(
                        progress_label_2, progress_bar_2, m, p))
                elif ptype == "done":
                    pass  # 单日完成由 run 内循环汇总
                elif ptype == "error":
                    window.after(0, lambda m=msg: _update_progress_2(
                        progress_label_2, progress_bar_2, m, 0))
                elif ptype == "cancelled":
                    window.after(0, lambda m=msg: _finish_parse_2(
                        window, False, m, progress_bar_2, button_stop_2,
                        progress_label_2, button_5, progress_row_bottom))

            try:
                for date_idx, target_date in enumerate(target_dates):
                    if cancel_event_2.is_set():
                        if tl:
                            window.after(0, lambda: tl.set_step_status("transcribe", "error"))
                        window.after(0, lambda: _finish_parse_2(
                            window, False, "用户取消", progress_bar_2, button_stop_2,
                            progress_label_2, button_5, progress_row_bottom))
                        return

                    day_pct = int((date_idx / total_dates) * 100)
                    window.after(0, lambda d=target_date, p=day_pct: _update_progress_2(
                        progress_label_2, progress_bar_2,
                        f"处理 {d} ({date_idx + 1}/{total_dates})", p))

                    result = batch_parse(selected_uids, batch_save_path,
                                         callback=progress_callback,
                                         cancel_event=cancel_event_2,
                                         target_date=target_date)
                    if result.get("cancelled"):
                        window.after(0, lambda: _finish_parse_2(
                            window, False, "用户取消", progress_bar_2, button_stop_2,
                            progress_label_2, button_5, progress_row_bottom))
                        return
                    if result.get("success"):
                        total_success += result.get("success_count", 0)
                        total_videos += result.get("total", 0)
                    else:
                        total_failed += 1

                window.after(0, lambda: _finish_parse_2(
                    window, True,
                    f"批量解析完成（{total_dates} 天）：成功 {total_success}/{total_videos} 个视频"
                    + (f"，{total_failed} 天失败" if total_failed else ""),
                    progress_bar_2, button_stop_2, progress_label_2, button_5,
                    progress_row_bottom))
                if tl and total_failed == 0:
                    window.after(0, lambda: tl.set_step_status("transcribe", "done"))
            except Exception as e:
                import traceback
                if tl:
                    window.after(0, lambda: tl.set_step_status("transcribe", "error"))
                window.after(0, lambda: _finish_parse_2(
                    window, False, str(e),
                    progress_bar_2, button_stop_2, progress_label_2, button_5,
                    progress_row_bottom))

        threading.Thread(target=run, daemon=True).start()
    except Exception as e:
        import traceback
        debug(f"button_5 ERROR: {e}\n{traceback.format_exc()}")
        messagebox.showerror("错误", str(e))


def build_page_batch(window, parent):
    """构建批量解析页（左侧树+按钮，右侧参数面板）"""
    global _window
    _window = window

    page_frame = parent  # Canvas 内的 inner frame

    # ═══════════ 左侧栏 ═══════════
    left_frame = Frame(page_frame, bg="#FFFFFF")
    left_frame.pack(side="left", fill="both", expand=True, padx=(6, 3), pady=4)

    # ── UP主列表 ──
    up_lf = ttk.LabelFrame(left_frame, text="UP主列表", padding=2)
    up_lf.pack(fill="both", expand=True)

    style_treeview_1 = ttk.Style()
    style_treeview_1.configure("Treeview", rowheight=30, fieldbackground="#FFFFFF")

    treeview_1_cols = ["选中", "uid", "昵称"]
    treeview_1 = ttk.Treeview(
        up_lf, columns=treeview_1_cols, show="headings", height=15
    )
    treeview_1.heading("选中", text="选中", anchor="center")
    treeview_1.column("选中", width=65, anchor="center")
    treeview_1.heading("uid", text="UID", anchor="center")
    treeview_1.column("uid", width=89, anchor="center")
    treeview_1.heading("昵称", text="昵称", anchor="center")
    treeview_1.column("昵称", width=163, anchor="center")
    treeview_1.tag_configure("oddrow", background="#FFFFFF")
    treeview_1.tag_configure("evenrow", background="#F5F5F5")
    treeview_1.pack(fill="both", expand=True, padx=2, pady=2)

    # 加载 UP 主数据
    up_list_data = load_up_list()
    for idx, row in enumerate(up_list_data):
        uid = row.get("uid", "")
        name = row.get("name", "")
        weight = row.get("weight", 0)
        checked = "☑" if weight > 0 else "☐"
        tag = "evenrow" if idx % 2 == 0 else "oddrow"
        treeview_1.insert("", "end", values=[checked, uid, name], tags=(tag,))

    # 绑定交互
    def on_treeview_click(event):
        region = treeview_1.identify("region", event.x, event.y)
        if region == "heading":
            column = treeview_1.identify_column(event.x)
            if column == "#1":
                toggle_select_all(treeview_1)
            return
        toggle_checkbox(treeview_1, event)

    treeview_1.bind("<Button-1>", on_treeview_click)
    treeview_1.bind("<Double-1>",
        lambda e: on_double_click_edit(treeview_1, treeview_1_cols, window, e))

    # ── 按钮区（2×2 grid） ──
    btn_frame = Frame(left_frame, bg="#FFFFFF")
    btn_frame.pack(fill="x", pady=(4, 0))
    btn_frame.grid_columnconfigure(0, weight=1, uniform="batch_btn")
    btn_frame.grid_columnconfigure(1, weight=1, uniform="batch_btn")

    button_6 = Button(
        btn_frame, text="保存修改",
        bg="#03D7FC", fg="#FFFFFF",
        font=("Inter", 16, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: button_6_clicked(treeview_1),
        relief="flat", activebackground="#03D7FC", cursor="hand2"
    )
    button_6.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=2)

    button_5 = Button(
        btn_frame, text="解析",
        bg="#000000", fg="#FFFFFF",
        font=("Inter", 16, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: button_5_clicked(
            window, treeview_1,
            progress_label_2, progress_bar_2, button_stop_2, button_5,
            progress_row_bottom),
        relief="flat", activebackground="#000000", cursor="hand2"
    )
    button_5.grid(row=0, column=1, sticky="nsew", padx=(2, 0), pady=2)

    button_add = Button(
        btn_frame, text="新增",
        bg="#4CAF50", fg="#FFFFFF",
        font=("Inter", 16, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: add_new_row(treeview_1),
        relief="flat", activebackground="#4CAF50", cursor="hand2"
    )
    button_add.grid(row=1, column=0, sticky="nsew", padx=(0, 2), pady=2)

    button_delete = Button(
        btn_frame, text="删除选中",
        bg="#F44336", fg="#FFFFFF",
        font=("Inter", 16, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: delete_selected(treeview_1),
        relief="flat", activebackground="#F44336", cursor="hand2"
    )
    button_delete.grid(row=1, column=1, sticky="nsew", padx=(2, 0), pady=2)

    # ═══════════ 右侧栏 ═══════════
    right_frame = Frame(page_frame, bg="#FFFFFF", width=430)
    right_frame.pack(side="right", fill="both", padx=(3, 6), pady=4)
    right_frame.pack_propagate(False)

    # ── 保存路径 ──
    path_lf = ttk.LabelFrame(right_frame, text="保存路径", padding=4)
    path_lf.pack(fill="x", pady=(0, 6))

    _bp = batch_save_path
    path_label_var = StringVar(
        value=_bp[:40] + "..." if len(_bp) > 40 else _bp if _bp else "(未选择)"
    )
    path_row = Frame(path_lf, bg="#FFFFFF")
    path_row.pack(fill="x")
    path_display = Label(
        path_row, textvariable=path_label_var,
        bg="#F0F0F0", fg="#555555", anchor="w",
        font=("", 12), relief="groove", padx=4
    )
    path_display.pack(side="left", fill="x", expand=True, padx=(0, 4))

    button_batch_browse = Button(
        path_row, text="浏览",
        bg="#2196F3", fg="#FFFFFF",
        font=("Inter", 12, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: button_batch_browse_clicked(path_label_var),
        relief="flat", activebackground="#1976D2", cursor="hand2"
    )
    button_batch_browse.pack(side="right")

    # ── 日期选择 ──
    date_lf = ttk.LabelFrame(right_frame, text="目标日期", padding=4)
    date_lf.pack(fill="x", pady=(0, 6))

    date_toggle_btn = Button(
        date_lf,
        text=f"已选 {len(_selected_target_dates)} 天 ▼",
        bg="#E3F2FD", fg="#1565C0",
        font=("Inter", 14, "bold"),
        borderwidth=2, relief="groove",
        highlightthickness=0,
        width=14,
        activebackground="#BBDEFB", activeforeground="#0D47A1",
        cursor="hand2",
    )
    date_toggle_btn.pack()

    def _toggle_date_popup():
        global _date_popup, _selected_target_dates
        if _date_popup is not None and _date_popup.winfo_exists():
            _date_popup.destroy()
            _date_popup = None
            return

        popup_h = 320

        def _calc_popup_xy():
            bx = date_toggle_btn.winfo_rootx()
            by_ = date_toggle_btn.winfo_rooty()
            bh = date_toggle_btn.winfo_height()
            sh = window.winfo_screenheight()
            if sh - (by_ + bh) >= popup_h + 4:
                return bx, by_ + bh + 2
            else:
                return bx, by_ - popup_h - 2

        popup = Toplevel(window)
        popup.transient(window)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        px, py = _calc_popup_xy()
        bw = date_toggle_btn.winfo_width()
        popup.geometry(f"{bw}x{popup_h}+{px}+{py}")
        popup.lift()
        popup.configure(bg="#FFFFFF", highlightbackground="#2196F3",
                        highlightthickness=1)
        popup.bind("<Escape>", lambda e: _cancel_popup())

        def _reposition_popup(event=None):
            if _date_popup is None or not _date_popup.winfo_exists():
                return
            nx, ny = _calc_popup_xy()
            _date_popup.geometry(f"{bw}x{popup_h}+{nx}+{ny}")

        _follow_id = window.bind("<Configure>", _reposition_popup, add="+")

        def _on_global_click(event):
            if _date_popup is None or not _date_popup.winfo_exists():
                return
            try:
                tl = event.widget.winfo_toplevel()
                if tl is popup:
                    return
            except Exception:
                pass
            _confirm_source[0] = "global_click"
            _confirm()

        _all_bind_id = [None]
        _all_bind_id[0] = window.after(150,
            lambda: _all_bind_id.__setitem__(0,
                window.bind_all("<Button-1>", _on_global_click, "+")))

        _confirming = [False]
        _confirm_source = ["unknown"]

        def _on_focus_out(event):
            if _confirming[0]:
                return
            if _date_popup is None or not _date_popup.winfo_exists():
                return
            _confirm_source[0] = "FocusOut"
            _confirming[0] = True
            _confirm()

        _focus_out_id = window.bind("<FocusOut>", _on_focus_out, add="+")

        listbox = Listbox(
            popup,
            selectmode="multiple",
            font=("Inter", 13),
            bg="#FFFFFF",
            fg="#000000",
            selectbackground="#2196F3",
            selectforeground="#FFFFFF",
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            exportselection=False,
            justify="center",
        )

        selected_set = set(_selected_target_dates)
        for i in range(30):
            d = _dt.date.today() - _dt.timedelta(days=29 - i)
            ds = d.strftime("%Y-%m-%d")
            listbox.insert("end", ds)
            if ds in selected_set:
                listbox.selection_set(i)

        listbox.place(x=1, y=1, width=bw - 2, height=278)

        btn_bar = Frame(popup, bg="#F5F5F5", height=40)
        btn_bar.place(x=0, y=280, width=bw, height=40)

        def _cleanup():
            try:
                if _all_bind_id[0] is not None:
                    window.after_cancel(_all_bind_id[0])
            except Exception:
                pass
            window.unbind_all("<Button-1>")
            window.unbind("<FocusOut>", _focus_out_id)

        def _confirm():
            global _date_popup, _selected_target_dates
            source = _confirm_source[0]
            sel_raw = [listbox.get(i) for i in listbox.curselection()]
            sel = [s.strip() for s in sel_raw]
            debug(f"_confirm [{source}]: curselection indices={listbox.curselection()}, sel={sel}")
            if sel:
                _selected_target_dates = sel
                debug(f"_selected_target_dates updated to: {_selected_target_dates}")
            else:
                debug(f"_selected_target_dates NOT updated (sel empty), keeping: {_selected_target_dates}")
            date_toggle_btn.configure(
                text=f"已选 {len(_selected_target_dates)} 天 ▼")
            _cleanup()
            try:
                popup.destroy()
            except Exception:
                pass
            _date_popup = None

        def _cancel_popup():
            global _date_popup
            _cleanup()
            try:
                popup.destroy()
            except Exception:
                pass
            _date_popup = None

        btn_ok = Button(
            btn_bar, text="确认",
            bg="#2196F3", fg="#FFFFFF",
            font=("Inter", 11, "normal"),
            borderwidth=0, highlightthickness=0,
            relief="flat", activebackground="#1976D2",
            cursor="hand2", command=lambda: (_confirm_source.__setitem__(0, "button_ok"), _confirm())[1],
        )
        btn_ok.place(x=5, y=5, width=85, height=30)

        btn_cancel = Button(
            btn_bar, text="取消",
            bg="#E0E0E0", fg="#333333",
            font=("Inter", 11, "normal"),
            borderwidth=0, highlightthickness=0,
            relief="flat", activebackground="#BDBDBD",
            cursor="hand2", command=_cancel_popup,
        )
        btn_cancel.place(x=100, y=5, width=85, height=30)

        def _on_destroy(event):
            try:
                window.unbind("<Configure>", _follow_id)
            except Exception:
                pass
            try:
                if _all_bind_id[0] is not None:
                    window.after_cancel(_all_bind_id[0])
            except Exception:
                pass
            window.unbind_all("<Button-1>")
            window.unbind("<FocusOut>", _focus_out_id)

        popup.bind("<Destroy>", _on_destroy)
        _date_popup = popup

    date_toggle_btn.configure(command=_toggle_date_popup)

    # ── 进度 ──
    progress_lf = ttk.LabelFrame(right_frame, text="进度", padding=4)
    progress_lf.pack(fill="x")

    progress_row_top = Frame(progress_lf, bg="#FFFFFF")
    progress_row_bottom = Frame(progress_lf, bg="#FFFFFF")
    # 初始仅显示 top（占位），bottom 运行时再展开
    progress_row_top.pack(fill="x")

    progress_label_2 = Label(
        progress_row_top, text="", fg="#555555", bg="#FFFFFF",
        font=("Inter", 11), anchor="w", wraplength=400
    )
    progress_label_2.pack(fill="x", padx=(0, 4))
    progress_label_2.pack_forget()

    progress_bar_2 = ttk.Progressbar(progress_row_bottom, mode="determinate")
    # 不预 pack

    button_stop_2 = Button(
        progress_row_bottom, text="停止", bg="#F44336", fg="#FFFFFF",
        font=("Inter", 10, "normal"), borderwidth=0, highlightthickness=0,
        relief="flat", activebackground="#D32F2F", cursor="hand2"
    )
    # 不预 pack

    ui = {
        "page_frame": page_frame,
        "treeview_1": treeview_1,
        "treeview_1_cols": treeview_1_cols,
        "button_5": button_5,
        "button_6": button_6,
        "button_add": button_add,
        "button_delete": button_delete,
        "date_toggle_btn": date_toggle_btn,
        "progress_label_2": progress_label_2,
        "progress_bar_2": progress_bar_2,
        "button_stop_2": button_stop_2,
    }
    return page_frame, ui

