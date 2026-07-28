"""
ETF 分析页面：多因子技术分析 + LLM 决策 + 持仓管理
"""
import sys
import os
import threading
import json
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

from backend.config_manager import get_setting, set_setting, get_risk_params, DEFAULTS
from backend.data_fetcher import fetch_etf_daily
from backend.factor_engine import run_factor_pipeline
from backend.llm_decision import decide
from backend.position_fetcher import format_positions_for_prompt, format_balance_for_prompt

from gui.timeline import get_timeline as _get_global_timeline

try:
    import requests
    _original_session_init = requests.Session.__init__
    def _patched_init(self, *a, **k):
        _original_session_init(self, *a, **k)
        self.trust_env = False
    requests.Session.__init__ = _patched_init
except ImportError:
    pass

ETF_NAME_MAP = {
    "510050": "上证50", "510300": "沪深300", "510500": "中证500",
    "159915": "创业板", "588000": "科创50", "512880": "证券ETF",
    "512100": "1000ETF", "513100": "纳指ETF", "518880": "黄金ETF",
    "159941": "纳指", "510880": "红利ETF", "512010": "医药ETF",
    "159845": "中证1000", "511260": "十年国债", "511010": "国债ETF",
    "513050": "中概互联", "159605": "互联中概", "516510": "云计算",
    "515790": "光伏ETF", "515030": "新能车", "512690": "酒ETF",
    "512660": "军工ETF", "512760": "芯片ETF", "515050": "5GETF",
}

PROVIDER_MODELS = {
    "deepseek": ["deepseek-v4-pro", "deepseek-v4-flash"],
    "volcengine": ["doubao-seed-2-0-lite-260428", "doubao-seed-2-0-mini-260428"],
}


def build_page_etf(window: tk.Tk, parent: tk.Frame):
    """构建 ETF 分析页面，返回 (parent, ui_dict)"""
    ui = {}

    # ── 取消机制 ──
    cancel_event = threading.Event()
    btn_cancel = None

    # ── 输出日志 ──
    output = scrolledtext.ScrolledText(parent, font=("Consolas", 10), wrap="word", state="disabled")
    output.vbar.pack_forget()
    output.pack(fill="both", expand=True, padx=8, pady=(0, 4))
    ui["output"] = output

    def _do_log(msg: str):
        output.configure(state="normal")
        output.insert(tk.END, msg + "\n")
        output.see(tk.END)
        output.configure(state="disabled")

    def _log(msg: str):
        if hasattr(_log, "widget") and _log.widget:
            window.after(0, lambda m=msg: _do_log(m))
    _log.widget = output

    # ── 顶栏：参数 + 模型 ──
    top_bar = tk.Frame(parent, bg="#F5F5F5")
    top_bar.pack(fill="x", padx=8, pady=(4, 0))

    # -- 左侧参数区 --
    param_frame = tk.LabelFrame(top_bar, text="分析参数", padding=4)
    param_frame.pack(side="left", fill="x", expand=True, padx=(0, 4))

    r0 = tk.Frame(param_frame)
    r0.pack(fill="x")
    tk.Label(r0, text="代码:").pack(side="left")
    etf_var = tk.StringVar(value=get_setting("default_etf", "510050"))
    etf_cb = ttk.Combobox(r0, textvariable=etf_var, width=10)
    etf_cb.pack(side="left", padx=(2, 0))
    def _on_etf_selected(e):
        v = etf_var.get().strip()
        if " " in v:
            etf_var.set(v.split()[0])
    etf_cb.bind("<<ComboboxSelected>>", _on_etf_selected)
    _refresh_etf_combo(etf_cb)

    tk.Label(r0, text=" 天数:").pack(side="left")
    days_var = tk.StringVar(value=str(get_setting("default_days", 60)))
    days_cb = ttk.Combobox(r0, textvariable=days_var, width=4, values=["1","7","30","60","90","180"])
    days_cb.pack(side="left", padx=(2, 0))

    tk.Label(r0, text=" 档位:").pack(side="left", padx=(4, 0))
    risk_var = tk.StringVar(value=get_setting("risk_profile", "standard"))
    risk_cb = ttk.Combobox(r0, textvariable=risk_var, values=["conservative","standard","aggressive"],
                           state="readonly", width=8)
    risk_cb.pack(side="left", padx=(2, 0))

    r1 = tk.Frame(param_frame)
    r1.pack(fill="x", pady=(2, 0))
    tk.Label(r1, text="数据源:").pack(side="left")
    src_var = tk.StringVar(value=get_setting("data_source", "baostock"))
    src_cb = ttk.Combobox(r1, textvariable=src_var, values=["baostock","akshare"], state="readonly", width=7)
    src_cb.pack(side="left", padx=(2, 0))
    src_cb.bind("<<ComboboxSelected>>", lambda e: set_setting("data_source", src_var.get()))

    tk.Label(r1, text=" 舆情:").pack(side="left", padx=(6, 0))
    sent_var = tk.StringVar()
    sent_label = tk.Label(r1, text="", fg="gray")
    def _refresh_sent():
        v = sent_var.get()
        if v:
            d = v if len(v) <= 40 else "..." + v[-37:]
            sent_label.config(text=d)
            sent_label.pack(side="left", padx=(2, 0))
        else:
            sent_label.pack_forget()
    def _browse_sent():
        f = filedialog.askopenfilename(initialdir="E:/", title="选择舆情总结",
            filetypes=[("JSON/TXT","*.json;*.txt"),("JSON","*.json"),("TXT","*.txt"),("所有","*.*")])
        if f:
            sent_var.set(f)
            set_setting("sentiment_dir", f)
            _refresh_sent()
    def _clear_sent():
        sent_var.set("")
        set_setting("sentiment_dir", "")
        _refresh_sent()
    tk.Button(r1, text="浏览", command=_browse_sent, width=5, font=("", 9)).pack(side="left", padx=(5, 0))
    sent_clear_btn = tk.Button(r1, text="✕", command=_clear_sent, width=2, font=("", 8), fg="red")
    sent_clear_btn.pack(side="left")
    init_sent = get_setting("sentiment_dir", "")
    sent_var.set(init_sent)
    _refresh_sent()

    # -- 右侧模型区 --
    model_frame = tk.LabelFrame(top_bar, text="模型设置", padding=4)
    model_frame.pack(side="right", padx=(4, 0))

    mr0 = tk.Frame(model_frame)
    mr0.pack(fill="x")
    tk.Label(mr0, text="Key:").pack(side="left")
    api_var = tk.StringVar(value=get_setting("llm_api_key", ""))
    api_entry = ttk.Entry(mr0, textvariable=api_var, width=20, show="*")
    api_entry.pack(side="left", padx=(2, 0))

    mr1 = tk.Frame(model_frame)
    mr1.pack(fill="x", pady=(2, 0))
    tk.Label(mr1, text="商:").pack(side="left")
    prov_var = tk.StringVar(value=get_setting("llm_provider", "deepseek"))
    prov_cb = ttk.Combobox(mr1, textvariable=prov_var, values=list(PROVIDER_MODELS.keys()),
                           state="readonly", width=8)
    prov_cb.pack(side="left", padx=(2, 0))
    tk.Label(mr1, text=" 型:").pack(side="left")
    cur_models = PROVIDER_MODELS.get(prov_var.get(), ["deepseek-v4-pro"])
    model_var = tk.StringVar(value=get_setting("llm_model", cur_models[0]))
    model_cb = ttk.Combobox(mr1, textvariable=model_var, values=cur_models, state="readonly", width=14)
    model_cb.pack(side="left", padx=(2, 0))
    def _save_prov(e):
        p = prov_var.get()
        ms = PROVIDER_MODELS.get(p, [])
        model_cb["values"] = ms
        if ms:
            model_var.set(ms[0])
        set_setting("llm_provider", p)
        set_setting("llm_model", ms[0] if ms else "")
    def _save_model(e=None):
        set_setting("llm_model", model_var.get())
    def _save_key(e=None):
        set_setting("llm_api_key", api_var.get())
    prov_cb.bind("<<ComboboxSelected>>", _save_prov)
    model_cb.bind("<<ComboboxSelected>>", _save_model)
    api_entry.bind("<FocusOut>", _save_key)
    api_entry.bind("<Return>", _save_key)

    ui["api_var"] = api_var
    ui["prov_var"] = prov_var
    ui["model_var"] = model_var

    # ── 持仓区 ──
    pos_frame = tk.LabelFrame(parent, text="持仓管理", padding=4)
    pos_frame.pack(fill="x", padx=8, pady=(4, 0))

    pos_bar = tk.Frame(pos_frame)
    pos_bar.pack(fill="x")
    pos_var = tk.StringVar(value="1")
    tk.Checkbutton(pos_bar, text="纳入决策", variable=pos_var, onvalue="1", offvalue="0").pack(side="left")
    tk.Label(pos_bar, text="（在下方粘贴同花顺持仓表格 → 点击解析）", fg="gray").pack(side="left", padx=(8, 0))

    paste_frame = tk.Frame(pos_frame)
    paste_frame.pack(fill="x", pady=(4, 0))
    paste_text = tk.Text(paste_frame, height=3, font=("Consolas", 9), wrap="none")
    paste_text.pack(side="left", fill="x", expand=True)
    paste_bar = tk.Frame(pos_frame)
    paste_bar.pack(fill="x", pady=(2, 0))
    tk.Button(paste_bar, text="解析持仓", command=lambda: _parse_clipboard(), font=("", 9)).pack(side="left")
    tk.Button(paste_bar, text="清空", command=lambda: _clear_positions(), width=5, font=("", 9)).pack(side="left", padx=(6, 0))

    # 4 行持仓
    pos_rows = []
    col_frame = tk.Frame(pos_frame)
    col_frame.pack(fill="x", pady=(4, 0))
    tk.Label(col_frame, text="代码", width=10).grid(row=0, column=0)
    tk.Label(col_frame, text="成本", width=10).grid(row=0, column=1, padx=2)
    tk.Label(col_frame, text="数量(份)", width=12).grid(row=0, column=2)
    for i in range(4):
        rf = tk.Frame(pos_frame)
        rf.pack(fill="x")
        cv, sv, qv = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Entry(rf, textvariable=cv, width=10).grid(row=0, column=0)
        ttk.Entry(rf, textvariable=sv, width=10).grid(row=0, column=1, padx=2)
        ttk.Entry(rf, textvariable=qv, width=12).grid(row=0, column=2)
        pos_rows.append((cv, sv, qv))

    bal_row = tk.Frame(pos_frame)
    bal_row.pack(fill="x", pady=(4, 0))
    bal_var = tk.StringVar()
    total_var = tk.StringVar()
    tk.Label(bal_row, text="可用资金:").pack(side="left")
    ttk.Entry(bal_row, textvariable=bal_var, width=12).pack(side="left", padx=(2, 0))
    tk.Label(bal_row, text="总资产:").pack(side="left", padx=(16, 0))
    ttk.Entry(bal_row, textvariable=total_var, width=12).pack(side="left", padx=(2, 0))

    # ── 持仓逻辑 ──
    def _save_positions():
        positions = []
        for cv, sv, qv in pos_rows:
            code = cv.get().strip()
            if not code:
                continue
            try:
                cost = float(sv.get().strip() or 0)
                qty = int(float(qv.get().strip() or 0))
            except ValueError:
                continue
            if qty > 0:
                positions.append({"code": code, "cost": cost, "qty": qty, "name": ""})
        set_setting("manual_positions", positions)
        bd = {}
        try:
            bd["available"] = float(bal_var.get().strip()) if bal_var.get().strip() else None
        except ValueError:
            pass
        try:
            bd["total_asset"] = float(total_var.get().strip()) if total_var.get().strip() else None
        except ValueError:
            pass
        set_setting("manual_balance", bd)

    def _load_positions():
        positions = get_setting("manual_positions", [])
        for i, p in enumerate(positions[:4]):
            if i < len(pos_rows):
                pos_rows[i][0].set(p.get("code", ""))
                pos_rows[i][1].set(str(p.get("cost", "")))
                pos_rows[i][2].set(str(int(p.get("qty", 0))))
        bd = get_setting("manual_balance", {})
        if bd:
            if bd.get("available"):
                bal_var.set(str(bd["available"]))
            if bd.get("total_asset"):
                total_var.set(str(bd["total_asset"]))

    def _parse_clipboard():
        text = paste_text.get("1.0", "end-1c").strip()
        if not text:
            _log("[持仓] 请先粘贴同花顺持仓表格")
            return
        lines = text.strip().split("\n")
        if len(lines) < 2:
            _log("[持仓] 格式错误：至少需要表头和数据行")
            return
        header = lines[0].strip().split("\t")
        try:
            ci = header.index("证券代码")
            ni = header.index("证券名称")
            qi = header.index("股票余额")
            si = header.index("成本价")
        except ValueError:
            _log("[持仓] 未找到必要列(证券代码/名称/余额/成本价)")
            return
        parsed = []
        for i, line in enumerate(lines[1:], 1):
            cells = line.strip().split("\t")
            if len(cells) <= max(ci, qi, si):
                continue
            try:
                code = cells[ci].strip()
                qty = int(float(cells[qi].strip()))
                cost = float(cells[si].strip())
                if code and qty > 0:
                    parsed.append({"code": code, "name": cells[ni].strip(), "qty": qty, "cost": cost})
            except (ValueError, IndexError):
                pass
        if parsed:
            for i, p in enumerate(parsed[:4]):
                if i < len(pos_rows):
                    pos_rows[i][0].set(p["code"])
                    pos_rows[i][1].set(str(p["cost"]))
                    pos_rows[i][2].set(str(p["qty"]))
            _save_positions()
            _log(f"[持仓] 已解析 {len(parsed)} 条")
        else:
            _log("[持仓] 未解析到有效数据")

    def _clear_positions():
        for cv, sv, qv in pos_rows:
            cv.set(""); sv.set(""); qv.set("")
        paste_text.delete("1.0", "end")
        _save_positions()
        _log("[持仓] 已清空")

    def _get_manual_account():
        positions = []
        for cv, sv, qv in pos_rows:
            code = cv.get().strip()
            if not code:
                continue
            try:
                cost = float(sv.get().strip() or 0)
                qty = int(float(qv.get().strip() or 0))
            except ValueError:
                continue
            if qty > 0:
                positions.append({"code": code, "cost": cost, "qty": qty, "name": ""})
        balance = {}
        try:
            v = bal_var.get().strip()
            if v:
                balance["available"] = float(v)
        except ValueError:
            pass
        try:
            v = total_var.get().strip()
            if v:
                balance["total_asset"] = float(v)
        except ValueError:
            pass
        return positions, balance

    # ── 自动保存 ──
    for cv, sv, qv in pos_rows:
        cv.trace_add("write", lambda *_: _save_positions())
        sv.trace_add("write", lambda *_: _save_positions())
        qv.trace_add("write", lambda *_: _save_positions())
    bal_var.trace_add("write", lambda *_: _save_positions())
    total_var.trace_add("write", lambda *_: _save_positions())
    _load_positions()

    # ── 按钮栏 ──
    btn_bar = tk.Frame(parent)
    btn_bar.pack(fill="x", padx=8, pady=(4, 0))

    run_btn = tk.Button(btn_bar, text="开始分析", font=("Microsoft YaHei", 10, "bold"),
                        bg="#0078D4", fg="white", relief="flat",
                        command=lambda: on_run(), cursor="hand2")
    run_btn.pack(side="left")

    ui["run_btn"] = run_btn

    def _finish_analysis():
        window.after(0, lambda: (
            run_btn.config(state="normal", text="开始分析"),
            cancel_btn.pack_forget() if cancel_btn else None,
        ))

    def on_run():
        nonlocal btn_cancel
        run_btn.config(state="disabled", text="分析中...")
        if btn_cancel is None:
            btn_cancel = tk.Button(btn_bar, text="取消", command=lambda: cancel_event.set(),
                                   font=("", 9), fg="red")
        btn_cancel.pack(side="left", padx=(8, 0))
        cancel_event.clear()
        threading.Thread(target=_run_analysis, daemon=True).start()
    cancel_btn = btn_cancel

    # ── 核心分析逻辑 ──
    def _load_sentiment() -> str:
        fp = sent_var.get().strip()
        if not fp:
            return ""
        p = Path(fp)
        json_file = None
        txt_file = None
        if p.is_dir():
            json_cands = sorted(p.glob("批次总结_*.json"), reverse=True)
            if json_cands:
                json_file = json_cands[0]
            else:
                txt_cands = sorted(p.glob("批次总结_*.txt"), reverse=True)
                if txt_cands:
                    txt_file = txt_cands[0]
        elif p.suffix.lower() == ".json" and p.is_file():
            json_file = p
        elif p.is_file():
            txt_file = p

        if json_file:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                return ""
            videos = data.get("videos", [])
            signals = data.get("entry_signals", [])
            parts = [f"=== 板块舆情（{data.get('video_count', len(videos))} 视频 {data.get('date','')}）===\n"]
            if videos:
                parts.append("【视频观点】")
                for v in videos:
                    parts.append(f"  [{v.get('bvid','')}] {v.get('opinion','')}")
                parts.append("")
            if signals:
                parts.append("【入场信号】")
                for es in signals:
                    parts.append(f"  {es.get('sector','')}: {es.get('reason','')}")
            if not videos and not signals:
                return data.get("raw_text", "").strip()
            return "\n".join(parts).strip()

        if txt_file:
            try:
                return txt_file.read_text(encoding="utf-8").strip()
            except Exception:
                return ""
        return ""

    def _save_result(symbol: str, result: dict, factor: dict):
        save_dir = get_setting("output_dir", "")
        if not save_dir:
            return
        try:
            out_dir = Path(save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = out_dir / f"ETF_{symbol}_{ts}.txt"
            am = {"buy":"买入","sell":"卖出","hold":"观望"}
            tm = {"bullish":"看涨","bearish":"看跌","neutral":"震荡"}
            lines = [f"ETF {symbol} LLM 决策报告", f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "="*40, "",
                     f"┌─ 决策: {am.get(result.get('action','hold'),result.get('action','N/A'))}  "
                     f"趋势: {tm.get(result.get('trend','neutral'),result.get('trend','N/A'))}  "
                     f"置信度: {result.get('confidence','N/A')}  当前价: {factor.get('price','N/A')}"]
            if result.get("entry_zone") or result.get("exit_zone") or result.get("position_ratio"):
                lines.append("├─ 操作")
                if result.get("entry_zone"):
                    lines.append(f"│  买入区间: {result['entry_zone']}")
                if result.get("exit_zone"):
                    lines.append(f"│  卖出区间: {result['exit_zone']}")
                if result.get("position_ratio"):
                    lines.append(f"│  仓位: {result['position_ratio']}")
            lines.append(f"├─ 风控: 止损 {result.get('stop_loss_price','N/A')}  止盈 {result.get('take_profit_price','N/A')}")
            if result.get("reasoning"):
                lines.append("├─ 依据")
                raw = result["reasoning"].replace("\r","")
                import re
                rs = [l.strip() for l in raw.split("\n") if l.strip()]
                if len(rs) == 1:
                    rs = [p.strip() for p in re.split(r'(?<!\d)(?=\d+\.\s|-\s)', rs[0]) if p.strip()]
                for rl in rs:
                    lines.append(f"│  {rl}")
            if result.get("position_advice"):
                lines.append("└─ " + result["position_advice"])
            else:
                lines.append("└─" + "─"*3)
            filepath.write_text("\n".join(lines), encoding="utf-8")
            _log(f"  已保存: {filepath}")
        except Exception as e:
            _log(f"  保存失败: {e}")

    def _check_cancel():
        if cancel_event.is_set():
            raise InterruptedError("用户取消")

    def _save_recent_etf(code):
        recent = list(get_setting("recent_etfs", []))
        if code in recent:
            recent.remove(code)
        recent.insert(0, code)
        set_setting("recent_etfs", recent[:10])

    def _refresh_etf_combo(cb):
        recent = get_setting("recent_etfs", [])
        vals = [f"{c} {ETF_NAME_MAP.get(c,'')}" for c in recent if c]
        hot = ["510050","510300","510500","159915","588000","512880","513100","518880"]
        for c in hot:
            d = f"{c} {ETF_NAME_MAP.get(c,'')}"
            if d not in vals:
                vals.append(d)
        cb["values"] = vals

    def _run_analysis():
        symbol = etf_var.get().strip().split()[0]
        try:
            days = int(days_var.get().strip())
        except ValueError:
            days = 60
        risk = risk_var.get()
        use_pos = pos_var.get() == "1"
        _save_key()

        api_key = get_setting("llm_api_key", "")
        if not api_key:
            _log("错误: API Key 未配置")
            _finish_analysis()
            return

        tl = _get_global_timeline()
        try:
            _log(f"=== {symbol} {days}天 {risk} ===")
            positions, balance = [], {}
            if use_pos:
                positions, balance = _get_manual_account()
                if positions:
                    _log(f"[持仓] {len(positions)} 条: {', '.join(p['code'] for p in positions)}")
                else:
                    _log("[持仓] 空仓")
                if balance:
                    parts = []
                    if balance.get("available"):
                        parts.append(f"可用 {balance['available']:.2f}")
                    if balance.get("total_asset"):
                        parts.append(f"总 {balance['total_asset']:.2f}")
                    _log(f"[资金] {', '.join(parts)}")

            if tl:
                tl.highlight("data")
            _log("[1/3] 获取行情...")
            df = fetch_etf_daily(symbol, count=max(days, 30))
            if df is None or df.empty:
                _log(f"错误: 无法获取 {symbol} 行情")
                _finish_analysis()
                return
            _log(f"  获取 {len(df)} 条, 最新 {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
            _check_cancel()

            if tl:
                tl.highlight("factor")
            _log("[2/3] 计算因子...")
            factor = run_factor_pipeline(df, get_risk_params(risk))
            _log(f"  价格: {factor['price']}  趋势: {factor['trend']}")
            _log(f"  信号: {', '.join(factor['signals']) or '无'}")

            sentiment = _load_sentiment()
            if sentiment:
                _log(f"  舆情: 已加载 ({len(sentiment)} 字)")

            _check_cancel()

            if tl:
                tl.highlight("llm")
            _log("[3/3] LLM 决策...")
            pt = format_positions_for_prompt(positions) if positions else ""
            bt = format_balance_for_prompt(balance) if balance else ""
            result = decide(symbol, factor, days=days, risk_profile=risk,
                           positions_text=pt, balance_text=bt, sentiment=sentiment)
            if "error" in result:
                _log(f"错误: {result['error']}")
                _finish_analysis()
                return

            if tl:
                tl.highlight("report")
            am = {"buy":"买入","sell":"卖出","hold":"观望"}
            tm = {"bullish":"看涨","bearish":"看跌","neutral":"震荡"}
            _log("")
            _log("┌─ 决策概览")
            _log(f"│  方向: {am.get(result.get('action','hold'),result.get('action','N/A'))}  "
                 f"趋势: {tm.get(result.get('trend','neutral'),result.get('trend','N/A'))}  "
                 f"置信度: {result.get('confidence','N/A')}  当前价: {factor['price']}")
            if result.get("entry_zone") or result.get("exit_zone") or result.get("position_ratio"):
                _log("├─ 操作建议")
                if result.get("entry_zone"):
                    _log(f"│  买入区间: {result['entry_zone']}")
                if result.get("exit_zone"):
                    _log(f"│  卖出区间: {result['exit_zone']}")
                if result.get("position_ratio"):
                    _log(f"│  仓位建议: {result['position_ratio']}")
            _log("├─ 风控参数")
            _log(f"│  止损: {result.get('stop_loss_price','N/A')}  止盈: {result.get('take_profit_price','N/A')}")
            if result.get("reasoning"):
                _log("├─ 决策依据")
                raw = result["reasoning"].replace("\r","")
                import re
                rs = [l.strip() for l in raw.split("\n") if l.strip()]
                if len(rs)==1:
                    rs = [p.strip() for p in re.split(r'(?<!\d)(?=\d+\.\s|-\s)', rs[0]) if p.strip()]
                for rl in rs:
                    _log(f"│  {rl}")
            if result.get("position_advice"):
                _log("└─ " + result["position_advice"])
            else:
                _log("└─" + "─"*3)
            _log("─"*40)
            _save_result(symbol, result, factor)
            _save_recent_etf(symbol)
            _refresh_etf_combo(etf_cb)
        except InterruptedError:
            _log("分析已取消")
        except Exception as e:
            _log(f"异常: {e}")
        finally:
            _finish_analysis()

    # ── 返回 ──
    ui["_log"] = _log
    ui["_timeline"] = _get_global_timeline
    return parent, ui
