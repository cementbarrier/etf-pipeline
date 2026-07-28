# -*- coding: utf-8 -*-
"""配置页（API Key、邮件、飞书、路径等所有配置项）"""

import sys
import datetime as _dt
from pathlib import Path

if getattr(sys, 'frozen', False):
    pass
else:
    _project_root = Path(__file__).parent.parent.parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

from tkinter import (
    BooleanVar, Button, Canvas, Checkbutton, Entry, Frame, Label,
    Scrollbar, StringVar, ttk, messagebox, filedialog,
)
from backend import config_manager, time_price_judge, task_queue_manager, valley_scheduler

from gui.utils import create_rounded_rectangle

# 外部注入
_gui_refresh_queue = None
_window = None


def set_refresh_callback(cb):
    global _gui_refresh_queue
    _gui_refresh_queue = cb


# ── 配置页回调 ──

def _config_get_display(key):
    val = config_manager.get_setting(key)
    if key == "bili2text_dir" and val and Path(val).exists():
        return val
    if key == "bili2text_dir":
        return "D:\\bili2text"
    return val if val else "（未设置）"


def _config_browse_dir(canvas, text_id, setting_key):
    path = filedialog.askdirectory(title="选择目录")
    if path:
        config_manager.set_setting(setting_key, path)
        display = path[:45] + "..." if len(path) > 45 else path
        canvas.itemconfigure(text_id, text=display, fill="#000000")


def _config_browse_file(canvas, text_id, setting_key):
    path = filedialog.askopenfilename(title="选择文件")
    if path:
        config_manager.set_setting(setting_key, path)
        display = path[:45] + "..." if len(path) > 45 else path
        canvas.itemconfigure(text_id, text=display, fill="#000000")


def _config_clear_path(canvas, text_id, setting_key):
    config_manager.set_setting(setting_key, "")
    canvas.itemconfigure(text_id, text="", fill="#888888")


def _update_model_options(provider_combo, model_combo):
    selected = provider_combo.get()
    if selected == "火山方舟/豆包":
        options = ["doubao-seed-2-0-lite-260428", "doubao-seed-2-0-mini-260428"]
    else:
        options = ["deepseek-v4-pro", "deepseek-v4-flash"]
    model_combo["values"] = options


def _config_provider_changed(provider_combo, model_combo):
    PROVIDER_MAP = {"DeepSeek": "deepseek", "火山方舟/豆包": "volcengine"}
    selected = provider_combo.get()
    internal = PROVIDER_MAP.get(selected, "deepseek")
    config_manager.set_setting("llm_provider", internal)
    _update_model_options(provider_combo, model_combo)
    if selected == "火山方舟/豆包":
        model_combo.set("doubao-1.5-pro-32k")
    else:
        model_combo.set("deepseek-v4-pro")


def _config_save_all(provider_combo, api_key_entry, model_combo,
                     email_sender_entry=None, email_auth_entry=None,
                     email_enabled_var=None):
    from backend.config_manager import load_settings, save_settings
    PROVIDER_MAP = {"DeepSeek": "deepseek", "火山方舟/豆包": "volcengine"}
    settings = load_settings()
    settings["llm_provider"] = PROVIDER_MAP.get(provider_combo.get(), "deepseek")
    settings["llm_api_key"] = api_key_entry.get().strip()
    settings["llm_model"] = model_combo.get().strip()
    if email_sender_entry is not None:
        settings["email_sender"] = email_sender_entry.get().strip()
    if email_auth_entry is not None:
        settings["email_auth_code"] = email_auth_entry.get().strip()
    if email_enabled_var is not None:
        settings["email_enabled"] = "true" if email_enabled_var.get() else "false"
    save_settings(settings)
    messagebox.showinfo("保存成功", "配置已保存")


def _config_refresh_all(canvas, b2t_id, cookie_id, log_id,
                        provider_combo, api_key_entry, model_combo,
                        email_sender_entry=None, email_auth_entry=None):
    for text_id, key in [
        (b2t_id, "bili2text_dir"),
        (cookie_id, "cookie_file"),
        (log_id, "debug_log"),
    ]:
        val = _config_get_display(key)
        display = (val[:45] + "...") if len(val) > 45 else val
        color = "#000000" if val else "#888888"
        canvas.itemconfigure(text_id, text=display, fill=color)

    PROVIDER_MAP = {"deepseek": "DeepSeek", "volcengine": "火山方舟/豆包"}
    provider_val = config_manager.get_setting("llm_provider") or "deepseek"
    provider_combo.set(PROVIDER_MAP.get(provider_val, "DeepSeek"))

    api_key_entry.delete(0, "end")
    api_key_entry.insert(0, config_manager.get_setting("llm_api_key") or "")

    _update_model_options(provider_combo, model_combo)
    model = config_manager.get_setting("llm_model") or ""
    if model:
        model_combo.set(model)

    if email_sender_entry is not None:
        email_sender_entry.delete(0, "end")
        email_sender_entry.insert(0, config_manager.get_setting("email_sender") or "")
    if email_auth_entry is not None:
        email_auth_entry.delete(0, "end")
        email_auth_entry.insert(0, config_manager.get_setting("email_auth_code") or "")


def build_page_config(window, parent, notebook_parent):
    """构建配置页，返回 (scroll_canvas, ui_elements_dict)
    notebook_parent 用于滚动条的 place（与 show_page 联动）
    """
    global _window
    _window = window

    scroll_canvas_3 = Canvas(
        notebook_parent,
        bg="#FFFFFF",
        height=666,
        width=796,
        bd=0,
        highlightthickness=0,
        relief="ridge"
    )

    v_scrollbar_3 = Scrollbar(notebook_parent, orient="vertical", command=scroll_canvas_3.yview)
    scroll_canvas_3.configure(yscrollcommand=v_scrollbar_3.set)

    page_frame_3 = Frame(
        scroll_canvas_3,
        bg="#FFFFFF",
        borderwidth=0,
        highlightthickness=0,
        width=776,
        height=780
    )
    page_frame_3.pack_propagate(False)
    scroll_canvas_3.create_window((0, 0), window=page_frame_3, anchor="nw", tags="p3_inner")
    scroll_canvas_3.configure(scrollregion=(0, 0, 776, 780))

    def _on_mousewheel_outer(event):
        scroll_canvas_3.yview_scroll(-1 * int(event.delta / 120), "units")

    def _bind_scroll(_):
        scroll_canvas_3.bind_all("<MouseWheel>", _on_mousewheel_outer)

    def _unbind_scroll(_):
        scroll_canvas_3.unbind_all("<MouseWheel>")

    scroll_canvas_3.bind("<Enter>", _bind_scroll)
    scroll_canvas_3.bind("<Leave>", _unbind_scroll)

    layout_width = 776
    canvas_page_3 = Canvas(
        page_frame_3,
        bg="#FFFFFF",
        height=780,
        width=layout_width,
        bd=0,
        highlightthickness=0,
        relief="ridge"
    )
    canvas_page_3.place(x=0, y=0)

    canvas_page_3.create_text(30, 20, anchor="nw", text="配置", fill="#000000",
                              font=("Inter", 20 * -1, "bold"))

    # ── 路径设置 ──
    canvas_page_3.create_text(30, 62, anchor="nw", text="路径设置", fill="#888888",
                              font=("Inter", 13 * -1, "bold"))

    # bili2text 路径
    canvas_page_3.create_text(30, 87, anchor="nw", text="bili2text 路径",
                              fill="#000000", font=("Inter", 14 * -1, "normal"))
    create_rounded_rectangle(canvas_page_3, 29, 107, 475, 143, 8,
                             fill="#FFFFFF", outline="#e0e0e0")
    b2t_path_text = canvas_page_3.create_text(34, 109, anchor="nw", text="",
                                              fill="#888888", font=("Inter", 12 * -1, "normal"))
    Button(page_frame_3, text="浏览", bg="#2196F3", fg="#FFFFFF",
           font=("Inter", 13, "normal"), borderwidth=0, highlightthickness=0,
           command=lambda c=canvas_page_3, t=b2t_path_text: _config_browse_dir(c, t, "bili2text_dir"),
           relief="flat", activebackground="#1976D2", cursor="hand2"
    ).place(x=490, y=108, width=75, height=35)

    # B站 Cookie
    canvas_page_3.create_text(30, 157, anchor="nw", text="B站 Cookie",
                              fill="#000000", font=("Inter", 14 * -1, "normal"))
    create_rounded_rectangle(canvas_page_3, 29, 177, 475, 213, 8,
                             fill="#FFFFFF", outline="#e0e0e0")
    cookie_path_text = canvas_page_3.create_text(34, 179, anchor="nw", text="",
                                                 fill="#888888", font=("Inter", 12 * -1, "normal"))
    Button(page_frame_3, text="浏览", bg="#2196F3", fg="#FFFFFF",
           font=("Inter", 13, "normal"), borderwidth=0, highlightthickness=0,
           command=lambda c=canvas_page_3, t=cookie_path_text: _config_browse_file(c, t, "cookie_file"),
           relief="flat", activebackground="#1976D2", cursor="hand2"
    ).place(x=490, y=178, width=75, height=35)

    # 调试日志
    canvas_page_3.create_text(30, 227, anchor="nw", text="调试日志",
                              fill="#000000", font=("Inter", 14 * -1, "normal"))
    create_rounded_rectangle(canvas_page_3, 29, 247, 475, 283, 8,
                             fill="#FFFFFF", outline="#e0e0e0")
    debug_log_path_text = canvas_page_3.create_text(34, 249, anchor="nw", text="",
                                                    fill="#888888", font=("Inter", 12 * -1, "normal"))
    Button(page_frame_3, text="浏览", bg="#2196F3", fg="#FFFFFF",
           font=("Inter", 13, "normal"), borderwidth=0, highlightthickness=0,
           command=lambda c=canvas_page_3, t=debug_log_path_text: _config_browse_file(c, t, "debug_log"),
           relief="flat", activebackground="#1976D2", cursor="hand2"
    ).place(x=490, y=248, width=75, height=35)
    Button(page_frame_3, text="清空", bg="#FF6B6B", fg="#FFFFFF",
           font=("Inter", 13, "normal"), borderwidth=0, highlightthickness=0,
           command=lambda c=canvas_page_3, t=debug_log_path_text: _config_clear_path(c, t, "debug_log"),
           relief="flat", activebackground="#E55A5A", cursor="hand2"
    ).place(x=570, y=248, width=75, height=35)

    # ── 大模型 ──
    canvas_page_3.create_text(30, 290, anchor="nw", text="大模型", fill="#888888",
                              font=("Inter", 13 * -1, "bold"))
    canvas_page_3.create_text(30, 312, anchor="nw", text="提供商",
                              fill="#000000", font=("Inter", 14 * -1, "normal"))
    PROVIDER_OPTIONS = ["DeepSeek", "火山方舟/豆包"]
    provider_combo = ttk.Combobox(
        page_frame_3, values=PROVIDER_OPTIONS, state="readonly",
        font=("Inter", 13), width=18
    )
    provider_combo.place(x=30, y=332, width=220, height=28)
    provider_combo.bind("<<ComboboxSelected>>",
        lambda e: _config_provider_changed(provider_combo, model_combo))

    canvas_page_3.create_text(30, 368, anchor="nw", text="API Key",
                              fill="#000000", font=("Inter", 14 * -1, "normal"))
    api_key_entry = Entry(
        page_frame_3, show="*", bd=1, relief="solid",
        bg="#FFFFFF", fg="#000000", font=("Inter", 12)
    )
    api_key_entry.place(x=30, y=388, width=460, height=28)

    def _toggle_api_key_visibility():
        if api_key_entry.cget("show") == "*":
            api_key_entry.config(show="")
            api_key_toggle_btn.config(text="隐藏")
        else:
            api_key_entry.config(show="*")
            api_key_toggle_btn.config(text="显示")

    api_key_toggle_btn = Button(
        page_frame_3, text="显示", command=_toggle_api_key_visibility,
        bg="#F0F0F0", font=("Inter", 10), bd=1, relief="solid"
    )
    api_key_toggle_btn.place(x=498, y=388, width=48, height=28)

    canvas_page_3.create_text(30, 424, anchor="nw", text="模型名",
                              fill="#000000", font=("Inter", 14 * -1, "normal"))
    model_combo = ttk.Combobox(
        page_frame_3, values=["deepseek-v4-pro", "deepseek-v4-flash"],
        font=("Inter", 13), width=25
    )
    model_combo.place(x=30, y=444, width=280, height=28)

    # ── 错峰调度 ──
    canvas_page_3.create_text(30, 480, anchor="nw", text="错峰调度", fill="#888888",
                              font=("Inter", 13 * -1, "bold"))

    valley_var = BooleanVar(value=True)
    if config_manager.get_setting("valley_scheduler_enabled") != "true":
        valley_var.set(False)

    def _on_valley_toggle():
        config_manager.set_setting(
            "valley_scheduler_enabled", "true" if valley_var.get() else "false")
        if _gui_refresh_queue:
            _gui_refresh_queue()

    valley_check = Checkbutton(
        page_frame_3, text="启用低谷错峰队列", variable=valley_var,
        bg="#FFFFFF", font=("Inter", 13), command=_on_valley_toggle
    )
    valley_check.place(x=30, y=502)

    queue_status_label = Label(
        page_frame_3, text="", fg="#333333", bg="#FFFFFF",
        font=("Inter", 12), anchor="w"
    )
    queue_status_label.place(x=250, y=505, width=240, height=20)

    def _manual_flush():
        n = valley_scheduler.flush_now(force=True)
        messagebox.showinfo("执行完成", f"已处理 {n} 条队列任务")
        if _gui_refresh_queue:
            _gui_refresh_queue()

    flush_btn = Button(
        page_frame_3, text="立即执行全部队列", command=_manual_flush,
        bg="#2196F3", fg="#FFFFFF", font=("Inter", 13, "normal"),
        borderwidth=0, highlightthickness=0,
        relief="flat", activebackground="#1976D2", cursor="hand2"
    )
    flush_btn.place(x=30, y=535, width=180, height=32)

    def _refresh_queue_status(_n=None):
        n = task_queue_manager.get_pending_count()
        is_val = time_price_judge.is_valley()
        enabled = valley_var.get()
        zone = "低谷平价" if is_val else "高峰双倍"
        queue_status_label.config(
            text=f"待执行: {n} 条  |  {time_price_judge.get_price_label()}",
            fg="#4CAF50" if is_val else "#FF5722"
        )
        if enabled:
            flush_btn.config(state="disabled", fg="#666666")
        else:
            flush_btn.config(state="normal" if n > 0 else "disabled", fg="#FFFFFF")

    _refresh_queue_status()

    # ── 通知提醒（QQ邮箱）──
    canvas_page_3.create_text(30, 580, anchor="nw", text="通知提醒", fill="#888888",
                              font=("Inter", 13 * -1, "bold"))

    email_enabled_var = BooleanVar(value=False)
    if config_manager.get_setting("email_enabled") == "true":
        email_enabled_var.set(True)

    email_check = Checkbutton(
        page_frame_3, text="启用邮件通知（QQ邮箱→微信）", variable=email_enabled_var,
        bg="#FFFFFF", font=("Inter", 12),
        command=lambda: config_manager.set_setting(
            "email_enabled", "true" if email_enabled_var.get() else "false")
    )
    email_check.place(x=30, y=602)

    canvas_page_3.create_text(30, 630, anchor="nw", text="QQ邮箱地址",
                              fill="#000000", font=("Inter", 12 * -1, "normal"))
    email_sender_entry = Entry(
        page_frame_3, bd=1, relief="solid",
        bg="#FFFFFF", fg="#000000", font=("Inter", 12)
    )
    email_sender_entry.place(x=30, y=648, width=200, height=24)

    canvas_page_3.create_text(240, 630, anchor="nw", text="授权码",
                              fill="#000000", font=("Inter", 12 * -1, "normal"))
    email_auth_entry = Entry(
        page_frame_3, show="*", bd=1, relief="solid",
        bg="#FFFFFF", fg="#000000", font=("Inter", 12)
    )
    email_auth_entry.place(x=240, y=648, width=180, height=24)

    def _test_email():
        from backend.notifier import send_notification
        ok = send_notification(
            "[股票工具] 测试通知",
            f"这是一条测试通知，发送时间：{_dt.datetime.now():%Y-%m-%d %H:%M:%S}\n\n如果你在微信收到此消息，说明配置成功。",
        )
        if ok:
            messagebox.showinfo("发送成功", "测试邮件已发出，请检查QQ邮箱（微信）")
        else:
            messagebox.showerror("发送失败", "请检查授权码、邮箱地址是否正确\n或开启 SMTP 服务")

    Button(
        page_frame_3, text="测试发送", command=_test_email,
        bg="#2196F3", fg="#FFFFFF", font=("Inter", 11, "normal"),
        borderwidth=0, highlightthickness=0,
        relief="flat", activebackground="#1976D2", cursor="hand2"
    ).place(x=430, y=648, width=80, height=24)

    # ── 飞书通知 ──
    canvas_page_3.create_text(30, 690, anchor="nw", text="飞书通知", fill="#888888",
                              font=("Inter", 13 * -1, "bold"))

    feishu_enabled_var = BooleanVar(value=False)
    if config_manager.get_setting("feishu_enabled") == "true":
        feishu_enabled_var.set(True)

    feishu_check = Checkbutton(
        page_frame_3, text="启用飞书机器人通知", variable=feishu_enabled_var,
        bg="#FFFFFF", font=("Inter", 12),
        command=lambda: config_manager.set_setting(
            "feishu_enabled", "true" if feishu_enabled_var.get() else "false")
    )
    feishu_check.place(x=30, y=712)

    canvas_page_3.create_text(30, 742, anchor="nw", text="Webhook URL",
                              fill="#000000", font=("Inter", 12 * -1, "normal"))
    feishu_webhook_var = StringVar(value=config_manager.get_setting("feishu_webhook") or "")
    feishu_webhook_entry = Entry(
        page_frame_3, bd=1, relief="solid",
        bg="#FFFFFF", fg="#000000", font=("Inter", 11),
        textvariable=feishu_webhook_var
    )
    feishu_webhook_entry.place(x=30, y=760, width=380, height=24)

    def _feishu_save_webhook(*_args):
        url = feishu_webhook_var.get().strip()
        if url:
            config_manager.set_setting("feishu_webhook", url)
        else:
            config_manager.set_setting("feishu_webhook", config_manager.DEFAULTS.get("feishu_webhook", ""))

    feishu_webhook_entry.bind("<FocusOut>", _feishu_save_webhook)
    feishu_webhook_entry.bind("<Return>", _feishu_save_webhook)

    def _test_feishu():
        url = feishu_webhook_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先输入飞书 Webhook URL")
            return
        from backend.feishu_notifier import test_webhook
        ok, msg = test_webhook(url)
        if ok:
            messagebox.showinfo("发送成功", msg)
        else:
            messagebox.showerror("发送失败", msg)

    Button(
        page_frame_3, text="测试发送", command=_test_feishu,
        bg="#2196F3", fg="#FFFFFF", font=("Inter", 11, "normal"),
        borderwidth=0, highlightthickness=0,
        relief="flat", activebackground="#1976D2", cursor="hand2"
    ).place(x=420, y=760, width=80, height=24)

    # 扩展高度
    page_frame_3.config(height=890)
    scroll_canvas_3.configure(scrollregion=(0, 0, 776, 890))

    # 保存按钮
    Button(
        page_frame_3, text="保存配置",
        bg="#000000", fg="#FFFFFF",
        font=("Inter", 16, "normal"),
        borderwidth=0, highlightthickness=0,
        command=lambda: _config_save_all(provider_combo, api_key_entry, model_combo,
            email_sender_entry, email_auth_entry, email_enabled_var),
        relief="flat", activebackground="#333333", cursor="hand2"
    ).place(x=30, y=830, width=155, height=40)

    # 刷新
    _config_refresh_all(canvas_page_3,
        b2t_path_text, cookie_path_text, debug_log_path_text,
        provider_combo, api_key_entry, model_combo,
        email_sender_entry, email_auth_entry)
    _refresh_queue_status()

    ui = {
        "scroll_canvas": scroll_canvas_3,
        "v_scrollbar_3": v_scrollbar_3,
        "page_frame_3": page_frame_3,
        "canvas_page_3": canvas_page_3,
        "b2t_path_text": b2t_path_text,
        "cookie_path_text": cookie_path_text,
        "debug_log_path_text": debug_log_path_text,
        "provider_combo": provider_combo,
        "api_key_entry": api_key_entry,
        "model_combo": model_combo,
        "valley_var": valley_var,
        "queue_status_label": queue_status_label,
        "flush_btn": flush_btn,
        "email_sender_entry": email_sender_entry,
        "email_auth_entry": email_auth_entry,
        "email_enabled_var": email_enabled_var,
        "feishu_enabled_var": feishu_enabled_var,
        "feishu_webhook_entry": feishu_webhook_entry,
        "refresh_queue_status": _refresh_queue_status,
    }
    return scroll_canvas_3, ui

