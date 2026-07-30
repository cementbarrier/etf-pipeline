# -*- coding: utf-8 -*-
""" ETF分析：多因子 + LLM + 持仓 """
import sys,os,threading,json,re
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk,scrolledtext,messagebox,filedialog
from backend.config_manager import get_setting,set_setting,get_risk_params,DEFAULTS
from backend.data_fetcher import fetch_etf_daily, get_last_fetch_error as get_data_error
from backend.factor_engine import run_factor_pipeline
from backend.llm_decision import decide
from backend.position_fetcher import format_positions_for_prompt,format_balance_for_prompt
from gui.timeline import get_timeline as _get_global_timeline
try:
    import requests
    _o=requests.Session.__init__
    def _p(s,*a,**k):_o(s,*a,**k);s.trust_env=False
    requests.Session.__init__=_p
except:pass
ETF_NAME_MAP={"510050":"上证50","510300":"沪深300","510500":"中证500","159915":"创业板","588000":"科创50","512880":"证券ETF","512100":"1000ETF","513100":"纳指ETF","518880":"黄金ETF","159941":"纳指","510880":"红利ETF","512010":"医药ETF","159845":"中证1000","511260":"十年国债","511010":"国债ETF","513050":"中概互联","159605":"互联中概","516510":"云计算","515790":"光伏ETF","515030":"新能车","512690":"酒ETF","512660":"军工ETF","512760":"芯片ETF","515050":"5GETF"}
PROVIDER_MODELS={"deepseek":["deepseek-v4-pro","deepseek-v4-flash"],"volcengine":["doubao-seed-2-0-lite-260428","doubao-seed-2-0-mini-260428"]}
GAP=6
def build_page_etf(window,parent):
    ui={};cancel_event=threading.Event();btn_cancel=None
    pf=ttk.LabelFrame(parent,text="分析参数",padding=4)
    pf.pack(fill="x",padx=6,pady=(4,GAP))
    r1=tk.Frame(pf);r1.pack(fill="x")
    tk.Label(r1,text="代码:",width=8,anchor="e",font=("",16)).pack(side="left")
    etf_var=tk.StringVar(value=get_setting("default_etf","510050"))
    etf_cb=ttk.Combobox(r1,textvariable=etf_var,width=18)
    etf_cb.pack(side="left",padx=(2,0))
    etf_var.trace_add("write",lambda *_:set_setting("default_etf",etf_var.get().strip()))
    def _on_etf(e):
        v=etf_var.get().strip()
        if " " in v:etf_var.set(v.split()[0])
    etf_cb.bind("<<ComboboxSelected>>",_on_etf)
    def _refresh_etf_combo(cb):
        recent=get_setting("recent_etfs",[])
        vals=[c+" "+ETF_NAME_MAP.get(c,"") for c in recent if c]
        for c in["510050","510300","510500","159915","588000","512880","513100","518880"]:
            d=c+" "+ETF_NAME_MAP.get(c,"")
            if d not in vals:vals.append(d)
        cb["values"]=vals
    def _save_recent_etf(code):
        recent=list(get_setting("recent_etfs",[]))
        if code in recent:recent.remove(code)
        recent.insert(0,code);set_setting("recent_etfs",recent[:10])
    _refresh_etf_combo(etf_cb)
    r1b=tk.Frame(pf);r1b.pack(fill="x",pady=(GAP,0))
    tk.Label(r1b,text="天数:",width=8,anchor="e",font=("",16)).pack(side="left")
    days_var=tk.StringVar(value=str(get_setting("default_days",60)))
    days_cb=ttk.Combobox(r1b,textvariable=days_var,width=18,values=["1","7","30","60","90","180"])
    days_cb.pack(side="left",padx=(2,0))
    days_var.trace_add("write",lambda *_:set_setting("default_days",days_var.get()))
    r1c=tk.Frame(pf);r1c.pack(fill="x",pady=(GAP,0))
    tk.Label(r1c,text="档位:",width=8,anchor="e",font=("",16)).pack(side="left")
    risk_var=tk.StringVar(value=get_setting("risk_profile","standard"))
    risk_cb=ttk.Combobox(r1c,textvariable=risk_var,values=["conservative","standard","aggressive"],state="readonly",width=18)
    risk_cb.pack(side="left",padx=(2,0))
    r2a=tk.Frame(pf);r2a.pack(fill="x",pady=(GAP,0))
    tk.Label(r2a,text="数据源:",width=8,anchor="e",font=("",16)).pack(side="left")
    src_var=tk.StringVar(value=get_setting("data_source","baostock"))
    src_cb=ttk.Combobox(r2a,textvariable=src_var,values=["baostock","akshare"],state="readonly",width=18)
    src_cb.pack(side="left",padx=(2,0))
    src_cb.bind("<<ComboboxSelected>>",lambda e:set_setting("data_source",src_var.get()))
    r2b=tk.Frame(pf);r2b.pack(fill="x",pady=(GAP,0))
    tk.Label(r2b,text="舆情:",width=8,anchor="e",font=("",16)).pack(side="left")
    sent_var=tk.StringVar()
    sent_lbl=tk.Label(r2b,text="",fg="gray",anchor="w",width=30,font=("",16))
    def _refresh_sent():
        v=sent_var.get()
        sent_lbl.config(text=v if len(v)<=30 else"..."+v[-27:])
    def _browse_sent():
        f=filedialog.askopenfilename(initialdir="E:/",title="选择舆情",filetypes=[("JSON/TXT","*.json;*.txt"),("全部","*.*")])
        if f:sent_var.set(f);set_setting("sentiment_dir",f);_refresh_sent()
    def _clear_sent():sent_var.set("");set_setting("sentiment_dir","");_refresh_sent()
    tk.Button(r2b,text="浏览",command=_browse_sent,width=5,font=("",16)).pack(side="left",padx=(2,GAP))
    tk.Button(r2b,text="X",command=_clear_sent,width=2,font=("",16),fg="red").pack(side="left")
    sent_lbl.pack(side="left",padx=(GAP,0))
    sent_var.set(get_setting("sentiment_dir",""));_refresh_sent()
    r2c=tk.Frame(pf);r2c.pack(fill="x",pady=(GAP,0))
    tk.Label(r2c,text="保存:",width=8,anchor="e",font=("",16)).pack(side="left")
    save_var=tk.StringVar()
    save_lbl=tk.Label(r2c,text="",fg="gray",anchor="w",width=30,font=("",16))
    def _refresh_save():
        v=save_var.get()
        save_lbl.config(text=v if len(v)<=30 else"..."+v[-27:])
    def _browse_save():
        d=filedialog.askdirectory(initialdir=save_var.get()or"E:/",title="选择保存目录")
        if d:save_var.set(d);set_setting("output_dir",d);_refresh_save()
    def _clear_save():save_var.set("");set_setting("output_dir","");_refresh_save()
    tk.Button(r2c,text="浏览",command=_browse_save,width=5,font=("",16)).pack(side="left",padx=(2,GAP))
    tk.Button(r2c,text="X",command=_clear_save,width=2,font=("",16),fg="red").pack(side="left")
    save_lbl.pack(side="left",padx=(GAP,0))
    save_var.set(get_setting("output_dir",""));_refresh_save()
    mf=ttk.LabelFrame(parent,text="模型设置",padding=4)
    mf.pack(fill="x",padx=6,pady=(0,GAP))
    mr=tk.Frame(mf);mr.pack(fill="x",pady=(0,GAP))
    tk.Label(mr,text="Key:",width=8,anchor="e",font=("",16)).pack(side="left")
    api_var=tk.StringVar(value=get_setting("llm_api_key",""))
    api_entry=ttk.Entry(mr,textvariable=api_var,width=26,show="*")
    api_entry.pack(side="left",padx=(2,0))
    mr2=tk.Frame(mf);mr2.pack(fill="x",pady=(0,GAP))
    tk.Label(mr2,text="提供商:",width=8,anchor="e",font=("",16)).pack(side="left")
    prov_var=tk.StringVar(value=get_setting("llm_provider","deepseek"))
    prov_cb=ttk.Combobox(mr2,textvariable=prov_var,values=list(PROVIDER_MODELS.keys()),state="readonly",width=18)
    prov_cb.pack(side="left",padx=(2,0))
    mr3=tk.Frame(mf);mr3.pack(fill="x",pady=(0,GAP))
    tk.Label(mr3,text="模型:",width=8,anchor="e",font=("",16)).pack(side="left")
    cur_ms=PROVIDER_MODELS.get(prov_var.get(),["deepseek-v4-pro"])
    model_var=tk.StringVar(value=get_setting("llm_model",cur_ms[0]))
    model_cb=ttk.Combobox(mr3,textvariable=model_var,values=cur_ms,state="readonly",width=18)
    model_cb.pack(side="left",padx=(2,0))
    def _save_prov(e):
        p=prov_var.get();ms=PROVIDER_MODELS.get(p,[])
        model_cb["values"]=ms
        # 仅当当前模型不在新提供商的列表中时，才自动切到第一个
        current_model = model_var.get()
        if current_model not in ms:
            model_var.set(ms[0] if ms else "")
            set_setting("llm_model", ms[0] if ms else "")
        set_setting("llm_provider",p)
    def _save_model(e=None):set_setting("llm_model",model_var.get())
    def _save_key(e=None):set_setting("llm_api_key",api_var.get())
    prov_cb.bind("<<ComboboxSelected>>",_save_prov)
    model_cb.bind("<<ComboboxSelected>>",_save_model)
    api_entry.bind("<FocusOut>",_save_key);api_entry.bind("<Return>",_save_key)
    ui["api_var"]=api_var;ui["prov_var"]=prov_var;ui["model_var"]=model_var
    pos_frame=ttk.LabelFrame(parent,text="持仓管理",padding=4)
    pos_frame.pack(fill="x",padx=6,pady=(0,GAP))
    ctrl_bar=tk.Frame(pos_frame);ctrl_bar.pack(fill="x")
    pos_var=tk.StringVar(value="1")
    tk.Checkbutton(ctrl_bar,text="纳入决策",variable=pos_var,onvalue="1",offvalue="0",font=("",16)).pack(side="left")
    tk.Button(ctrl_bar,text="解析持仓",command=lambda:_parse_clipboard(),font=("",16)).pack(side="left",padx=(GAP,0))
    tk.Button(ctrl_bar,text="清空",command=lambda:_clear_positions(),width=5,font=("",16)).pack(side="left",padx=(GAP,0))
    paste_frame=tk.Frame(pos_frame);paste_frame.pack(fill="x",pady=(GAP,0))
    paste_text=tk.Text(paste_frame,height=2,font=("Consolas",16),wrap="none")
    paste_text.pack(fill="x")
    pos_table=tk.Frame(pos_frame)
    pos_rows=[]
    hdr=tk.Frame(pos_table);hdr.pack(fill="x",pady=(GAP,0))
    tk.Label(hdr,text="代码",width=10,font=("",16)).grid(row=0,column=0)
    tk.Label(hdr,text="成本",width=10,font=("",16)).grid(row=0,column=1,padx=2)
    tk.Label(hdr,text="数量(份)",width=12,font=("",16)).grid(row=0,column=2)
    for i in range(4):
        rf=tk.Frame(pos_table);rf.pack(fill="x")
        cv,sv,qv=tk.StringVar(),tk.StringVar(),tk.StringVar()
        ttk.Entry(rf,textvariable=cv,width=10,font=("",16)).grid(row=0,column=0)
        ttk.Entry(rf,textvariable=sv,width=10,font=("",16)).grid(row=0,column=1,padx=2)
        ttk.Entry(rf,textvariable=qv,width=12,font=("",16)).grid(row=0,column=2)
        pos_rows.append((cv,sv,qv))
    bal_row=tk.Frame(pos_table)
    bal_var=tk.StringVar();total_var=tk.StringVar()
    tk.Label(bal_row,text="可用资金:",font=("",16)).pack(side="left",pady=(GAP,0))
    ttk.Entry(bal_row,textvariable=bal_var,width=14,font=("",16)).pack(side="left",padx=(2,GAP))
    tk.Label(bal_row,text="总资产:",font=("",16)).pack(side="left",padx=(GAP,0))
    ttk.Entry(bal_row,textvariable=total_var,width=14,font=("",16)).pack(side="left",padx=(2,0))
    bal_row.pack(fill="x")
    _pos_table_shown=False
    def _show_pos_table():
        nonlocal _pos_table_shown
        if not _pos_table_shown:pos_table.pack(fill="x",before=paste_frame);_pos_table_shown=True
    def _hide_pos_table():
        nonlocal _pos_table_shown
        if _pos_table_shown:pos_table.pack_forget();_pos_table_shown=False
    def _save_positions():
        positions=[]
        for cv,sv,qv in pos_rows:
            code=cv.get().strip()
            if not code:continue
            try:cost=float(sv.get().strip()or 0);qty=int(float(qv.get().strip()or 0))
            except ValueError:continue
            if qty>0:positions.append({"code":code,"cost":cost,"qty":qty,"name":""})
        set_setting("manual_positions",positions)
        bd={}
        try:bd["available"]=float(bal_var.get().strip())if bal_var.get().strip()else None
        except ValueError:pass
        try:bd["total_asset"]=float(total_var.get().strip())if total_var.get().strip()else None
        except ValueError:pass
        set_setting("manual_balance",bd)
    def _load_positions():
        positions=get_setting("manual_positions",[])
        if positions:_show_pos_table()
        for i,p in enumerate(positions[:4]):
            if i<len(pos_rows):
                pos_rows[i][0].set(p.get("code",""))
                pos_rows[i][1].set(str(p.get("cost","")))
                pos_rows[i][2].set(str(int(p.get("qty",0))))
        bd=get_setting("manual_balance",{})
        if bd:
            if bd.get("available"):bal_var.set(str(bd["available"]))
            if bd.get("total_asset"):total_var.set(str(bd["total_asset"]))
    def _parse_clipboard():
        text=paste_text.get("1.0","end-1c").strip()
        if not text:_log("[持仓]请先粘贴同花顺持仓表格");return
        lines=text.strip().split("\n")
        if len(lines)<2:_log("[持仓]格式错误");return
        header=lines[0].strip().split("\t")
        try:ci=header.index("证券代码");ni=header.index("证券名称");qi=header.index("股票余额");si=header.index("成本价")
        except ValueError:_log("[持仓]缺少必要列");return
        parsed=[]
        for line in lines[1:]:
            cells=line.strip().split("\t")
            if len(cells)<=max(ci,qi,si):continue
            try:code=cells[ci].strip();qty=int(float(cells[qi].strip()));cost=float(cells[si].strip())
            except:continue
            if code and qty>0:parsed.append({"code":code,"name":cells[ni].strip(),"qty":qty,"cost":cost})
        if parsed:
            _show_pos_table()
            for i,p in enumerate(parsed[:4]):
                if i<len(pos_rows):
                    pos_rows[i][0].set(p["code"]);pos_rows[i][1].set(str(p["cost"]));pos_rows[i][2].set(str(p["qty"]))
            _save_positions();_log(f"[持仓]已解析{len(parsed)}条")
        else:_log("[持仓]未解析到有效数据")
    def _clear_positions():
        for cv,sv,qv in pos_rows:cv.set("");sv.set("");qv.set("");bal_var.set("");total_var.set("")
        paste_text.delete("1.0","end");_save_positions();_hide_pos_table();_log("[持仓]已清空")
    def _get_manual_account():
        positions=[]
        for cv,sv,qv in pos_rows:
            code=cv.get().strip()
            if not code:continue
            try:cost=float(sv.get().strip()or 0);qty=int(float(qv.get().strip()or 0))
            except ValueError:continue
            if qty>0:positions.append({"code":code,"cost":cost,"qty":qty,"name":""})
        balance={}
        try:
            v=bal_var.get().strip()
            if v:balance["available"]=float(v)
        except ValueError:pass
        try:
            v=total_var.get().strip()
            if v:balance["total_asset"]=float(v)
        except ValueError:pass
        return positions,balance
    for cv,sv,qv in pos_rows:
        cv.trace_add("write",lambda*_:_save_positions())
        sv.trace_add("write",lambda*_:_save_positions())
        qv.trace_add("write",lambda*_:_save_positions())
    bal_var.trace_add("write",lambda*_:_save_positions())
    total_var.trace_add("write",lambda*_:_save_positions())
    _load_positions()
    sep_bar=ttk.Separator(parent,orient="horizontal")
    sep_bar.pack(fill="x",padx=6,pady=(GAP,0))
    btn_bar=tk.Frame(parent)
    btn_bar.pack(fill="x",padx=6,pady=(GAP,0))
    run_btn=tk.Button(btn_bar,text="开始分析",font=("Microsoft YaHei",16,"bold"),bg="#0078D4",fg="white",relief="flat",command=lambda:on_run(),cursor="hand2")
    run_btn.pack(side="left")
    ui["run_btn"]=run_btn
    toggle_btn=tk.Button(btn_bar,text="显示输出",font=("",16),relief="flat",fg="#555",
                         command=lambda:_toggle_output())
    toggle_btn.pack(side="left",padx=(8,0))
    def _toggle_output():
        if output_container.winfo_manager():
            output_container.pack_forget();toggle_btn.config(text="显示输出")
        else:
            output_container.pack(fill="x",padx=6,pady=(GAP,2),before=sep_bar)
            toggle_btn.config(text="隐藏输出")
    def _finish_analysis():
        window.after(0,lambda:(run_btn.config(state="normal",text="开始分析"),btn_cancel.pack_forget()if btn_cancel else None))
    def on_run():
        nonlocal btn_cancel
        run_btn.config(state="disabled",text="分析中...")
        if btn_cancel is None:btn_cancel=tk.Button(btn_bar,text="取消",command=lambda:cancel_event.set(),font=("",16),fg="red")
        btn_cancel.pack(side="left",padx=(8,0))
        if not output_container.winfo_manager():
            output_container.pack(fill="x",padx=6,pady=(GAP,2),before=sep_bar)
            toggle_btn.config(text="隐藏输出")
        cancel_event.clear();threading.Thread(target=_run_analysis,daemon=True).start()
        tl = _get_global_timeline()
        if tl: window.after(0,tl.reset)
    # ── 输出区（可折叠，动态高度）──
    output_container=tk.Frame(parent,bg="#f0f0f0",highlightbackground="#ccc",highlightthickness=1)
    output_header=tk.Frame(output_container,bg="#e8e8e8")
    output_header.pack(fill="x")
    tk.Label(output_header,text="分析输出",font=("Microsoft YaHei",14,"bold"),bg="#e8e8e8").pack(side="left",padx=4,pady=1)
    output_hide_btn=tk.Button(output_header,text="×",font=("",14,"bold"),fg="#666",bg="#e8e8e8",relief="flat",width=2,
                              command=lambda:(output_container.pack_forget(),toggle_btn.config(text="显示输出")))
    output_hide_btn.pack(side="right",padx=1)
    output=scrolledtext.ScrolledText(output_container,font=("Consolas",16),wrap="word",state="disabled",height=10)
    output.vbar.pack_forget()
    output.pack(fill="both",expand=True,padx=2,pady=(0,2))
    ui["output"]=output;ui["output_container"]=output_container
    def _do_log(msg):
        output.configure(state="normal");output.insert(tk.END,msg+"\n");output.see(tk.END);output.configure(state="disabled")
        try:lines=int(output.index('end-1c').split('.')[0]);output.configure(height=max(8,min(lines+1,25)))
        except:pass
    def _log(msg):
        if hasattr(_log,"widget")and _log.widget:window.after(0,lambda m=msg:_do_log(m))
    _log.widget=output

    def _load_sentiment() -> str:
        """加载板块舆情总结文件，用于 LLM 决策的外部情绪参考

        优先级：JSON（stock-tool batch_parser 结构化输出） > TXT（旧格式）
        JSON 格式：{ videos: [{bvid, opinion}], entry_signals: [{sector, reason}] }
        """
        file_path = get_setting("sentiment_dir", DEFAULTS["sentiment_dir"])
        if not file_path:
            return ""
        p = Path(file_path)

        # 确定要读取的文件：JSON 优先，TXT 回退
        json_file = None
        txt_file = None

        if p.is_dir():
            json_candidates = sorted(p.glob("批次总结_*.json"), reverse=True)
            if json_candidates:
                json_file = json_candidates[0]
            else:
                txt_candidates = sorted(p.glob("批次总结_*.txt"), reverse=True)
                if txt_candidates:
                    txt_file = txt_candidates[0]
        elif p.suffix.lower() == ".json" and p.is_file():
            json_file = p
        elif p.is_file():
            txt_file = p

        # ── JSON 模式：解析结构化字段 ──
        if json_file:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                return ""
            videos = data.get("videos", [])
            entry_signals = data.get("entry_signals", [])
            video_count = data.get("video_count", len(videos))

            parts = [f"=== 板块舆情分析（基于 {video_count} 个视频，{data.get('date', '')}）===\n"]

            if videos:
                parts.append("【视频观点速览】")
                for v in videos:
                    bvid = v.get("bvid", "")
                    opinion = v.get("opinion", "")
                    parts.append(f"  [{bvid}] {opinion}")
                parts.append("")

            if entry_signals:
                parts.append("【入场参考信号】")
                for es in entry_signals:
                    sector = es.get("sector", "")
                    reason = es.get("reason", "")
                    parts.append(f"  {sector}: {reason}")

            if not videos and not entry_signals:
                # 仅有 raw_text 时直接返回
                return data.get("raw_text", "").strip()

            return "\n".join(parts).strip()

        # ── TXT 模式：直接读取 ──
        if txt_file:
            try:
                return txt_file.read_text(encoding="utf-8").strip()
            except Exception:
                return ""

        return ""


    def _save_result(symbol: str, result: dict, factor: dict):
        """将 LLM 决策结果保存为 txt 文件"""
        save_dir = get_setting("output_dir", DEFAULTS["output_dir"])
        if not save_dir:
            return
        try:
            from datetime import datetime
            out_dir = Path(save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ETF_{symbol}_{ts}.txt"
            filepath = out_dir / filename

            action_map = {"buy": "买入", "sell": "卖出", "hold": "观望"}
            trend_map = {"bullish": "看涨", "bearish": "看跌", "neutral": "震荡"}

            lines = []
            lines.append(f"ETF {symbol} LLM 决策报告")
            lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("=" * 40)
            lines.append("")
            lines.append("┌─ 决策概览")
            lines.append(f"│  方向: {action_map.get(result.get('action', 'hold'), result.get('action', 'N/A'))}  趋势: {trend_map.get(result.get('trend', 'neutral'), result.get('trend', 'N/A'))}  置信度: {result.get('confidence', 'N/A')}  当前价: {factor.get('price', 'N/A')}")

            if result.get("entry_zone") or result.get("exit_zone") or result.get("position_ratio"):
                lines.append("├─ 操作建议")
                if result.get("entry_zone"):
                    lines.append(f"│  买入区间: {result['entry_zone']}")
                if result.get("exit_zone"):
                    lines.append(f"│  卖出区间: {result['exit_zone']}")
                if result.get("position_ratio"):
                    lines.append(f"│  仓位建议: {result['position_ratio']}")

            lines.append("├─ 风控参数")
            lines.append(f"│  止损: {result.get('stop_loss_price', 'N/A')}  止盈: {result.get('take_profit_price', 'N/A')}")

            if result.get("reasoning"):
                lines.append("├─ 决策依据")
                import re
                raw = result["reasoning"].replace("\r", "")
                rlines = [l.strip() for l in raw.split("\n") if l.strip()]
                if len(rlines) == 1:
                    parts = re.split(r'(?<!\d)(?=\d+\.\s|-\s)', rlines[0])
                    rlines = [p.strip() for p in parts if p.strip()]
                for line in rlines:
                    lines.append(f"│  {line}")

            if result.get("position_advice"):
                lines.append("└─ " + result["position_advice"])
            else:
                lines.append("└─" + "─" * 3)

            filepath.write_text("\n".join(lines), encoding="utf-8")
            _log(f"  已保存: {filepath}")
        except Exception as e:
            _log(f"  保存失败: {e}")


    def _run_analysis():
        tl = ui.get("_timeline")
        def _hl(key): window.after(0,lambda: tl.set_step_status(key,"active")) if tl else None
        def _ok(key): window.after(0,lambda: tl.set_step_status(key,"done")) if tl else None
        def _err(key): window.after(0,lambda: tl.set_step_status(key,"error")) if tl else None

        symbol = etf_var.get().strip()
        try:
            days = int(days_var.get().strip())
        except ValueError:
            days = 60
        risk = risk_var.get()
        use_positions = pos_var.get() == "1"

        _save_api_key = lambda: set_setting("llm_api_key", api_var.get())
        _save_api_key()

        # API Key 未配置检查
        api_key = get_setting("llm_api_key", "")
        if not api_key:
            messagebox.showwarning("API Key 未配置", "请先在顶部填写 LLM API Key 后重试。")
            _log("错误: API Key 未配置，已弹窗提示")
            _finish_analysis()
            return

        try:
            _log(f"=== {symbol} {days}天 {risk} ===")

            # 持仓 + 资金
            positions = []
            account_balance = {}
            if use_positions:
                positions, account_balance = _get_manual_account()
                if not positions:
                    _log("[持仓] 空仓（请在持仓面板粘贴同花顺数据后重试）")
                else:
                    codes = [str(p.get("code", "")) for p in positions if isinstance(p, dict)]
                    _log(f"[持仓] 共 {len(positions)} 条: {', '.join(codes)}")
                if account_balance:
                    avail = account_balance.get("available")
                    total = account_balance.get("total_asset")
                    parts = []
                    if avail:
                        parts.append(f"可用 {avail:.2f}")
                    if total:
                        parts.append(f"总资产 {total:.2f}")
                    _log(f"[资金] {', '.join(parts)}")
                else:
                    _log("[资金] 无数据，将仅基于行情分析")
            else:
                _log("[账户] 未纳入决策，仅基于行情分析")

            _log("[1/3] 获取行情...")
            _hl("data")

            max_bars = max(days, 30)
            df = fetch_etf_daily(symbol, count=max_bars)
            if df is None or df.empty:
                err_detail = get_data_error()
                if err_detail:
                    _log(f"错误: 无法获取 {symbol} 行情数据\n  {err_detail}")
                else:
                    _log(f"错误: 无法获取 {symbol} 行情数据")
                _err("data")
                return

            _log(f"  获取 {len(df)} 条数据, 最新 {df['date'].iloc[-1].strftime('%Y-%m-%d')}")

            _check_cancel()
            _ok("data")

            _log("[2/3] 计算技术指标...")
            _hl("factor")
            risk_params = get_risk_params(risk)
            factor = run_factor_pipeline(df, risk_params)
            _log(f"  价格: {factor['price']}  趋势: {factor['trend']}")
            _log(f"  信号: {', '.join(factor['signals']) or '无'}")

            # 加载板块舆情
            sentiment = _load_sentiment()
            if sentiment:
                _log(f"  板块舆情: 已加载 ({len(sentiment)} 字)")
            else:
                _log("  板块舆情: 无外部数据，纯技术面分析")

            _check_cancel()
            _ok("factor")

            _log("[3/3] LLM 决策...")
            _hl("llm")

            # 格式化持仓和资金为 prompt 文本
            pos_text = format_positions_for_prompt(positions) if positions else ""
            bal_text = format_balance_for_prompt(account_balance) if account_balance else ""
            result = decide(symbol, factor, days=days, risk_profile=risk, positions_text=pos_text, balance_text=bal_text, sentiment=sentiment)

            _check_cancel()

            if "error" in result:
                _log(f"错误: {result['error']}")
                return

            action_en = result.get("action", "hold")
            action_map = {"buy": "买入", "sell": "卖出", "hold": "观望"}
            trend_en = result.get("trend", "neutral")
            trend_map = {"bullish": "看涨", "bearish": "看跌", "neutral": "震荡"}

            # ── 概览 ──
            _log("")
            _log("┌─ 决策概览")
            _log(f"│  方向: {action_map.get(action_en, action_en)}　趋势: {trend_map.get(trend_en, trend_en)}　置信度: {result.get('confidence', 'N/A')}　当前价: {factor['price']}")

            # ── 操作区间 ──
            if result.get("entry_zone") or result.get("exit_zone") or result.get("position_ratio"):
                _log("├─ 操作建议")
                if result.get("entry_zone"):
                    _log(f"│  买入区间: {result['entry_zone']}")
                if result.get("exit_zone"):
                    _log(f"│  卖出区间: {result['exit_zone']}")
                if result.get("position_ratio"):
                    _log(f"│  仓位建议: {result['position_ratio']}")

            # ── 风控 ──
            _log("├─ 风控参数")
            _log(f"│  止损: {result.get('stop_loss_price')}　止盈: {result.get('take_profit_price')}")

            # ── 依据（多行） ──
            if result.get("reasoning"):
                _log("├─ 决策依据")
                raw = result["reasoning"].replace("\r", "")
                lines = [l.strip() for l in raw.split("\n") if l.strip()]
                # 如果只有一行且包含编号模式（1. 2. 或 - 开头），智能拆分
                if len(lines) == 1:
                    import re
                    parts = re.split(r'(?<!\d)(?=\d+\.\s|-\s)', lines[0])
                    lines = [p.strip() for p in parts if p.strip()]
                for line in lines:
                    _log(f"│  {line}")

            # ── 总建议 ──
            if result.get("position_advice"):
                _log("└─ " + result["position_advice"])
            else:
                _log("└─" + "─" * 3)

            _log("─" * 40)

            _ok("llm")
            _hl("report")

            # 保存结果
            _save_result(symbol, result, factor)

            # 保存最近常用 ETF，刷新下拉列表
            if symbol:
                _save_recent_etf(symbol)
                _refresh_etf_combo(etf_cb)

            _ok("report")

        except InterruptedError:
            _log("分析已取消")
            _err(_current_active_step())
        except Exception as e:
            _log(f"异常: {e}")
            _err(_current_active_step())
        finally:
            _finish_analysis()


    def _current_active_step():
        steps = PIPELINE_STEPS.get("etf", [])
        for label, key in steps:
            if tl and tl._step_status.get(key) == "active":
                return key
        return "llm"


    def _check_cancel():
        """检查取消标志，若已设置则抛出异常中断分析"""
        if cancel_event.is_set():
            raise InterruptedError("用户取消")


    # output packed on first run
    ui["_log"]=_log;ui["_timeline"]=_get_global_timeline
    return parent,ui
