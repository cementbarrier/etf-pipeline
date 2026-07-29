"""
流水线时间轴组件：显示当前执行步骤，高亮激活步骤。
"""
import tkinter as tk
from tkinter import ttk

# ── 各 Tab 对应的流水线步骤 ──
PIPELINE_STEPS = {
    "etf": [
        ("获取行情", "data"),
        ("计算因子", "factor"),
        ("LLM决策", "llm"),
        ("生成报告", "report"),
    ],
    "parse": [
        ("获取视频", "fetch"),
        ("下载音频", "audio"),
        ("转写字幕", "transcribe"),
        ("AI摘要", "summary"),
    ],
    "batch": [
        ("拉取视频", "fetch"),
        ("批量转写", "transcribe"),
        ("生成总结", "summary"),
    ],
    "config": [],
}

_instance = None


def set_timeline(inst):
    global _instance
    _instance = inst


def get_timeline():
    return _instance


STEP_COLORS = {
    "pending": "#CCCCCC",
    "active": "#0078D4",
    "done": "#107C10",
    "error": "#D13438",
    "text": "#999999",
    "active_text": "#FFFFFF",
    "done_text": "#FFFFFF",
}


class PipelineTimeline(tk.Frame):
    """水平流水线步骤条"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#EBEBEB", height=60, **kwargs)
        self._mode = "etf"
        self._step_status = {}
        self._step_labels = []
        self._step_circles = []
        self._connectors = []
        self._canvas = None
        self._build()
        global _instance
        _instance = self

    def _build(self):
        self._canvas = tk.Canvas(
            self, bg="#EBEBEB", height=60,
            bd=0, highlightthickness=0,
        )
        self._canvas.pack(fill="x", expand=True)

    def set_mode(self, mode: str):
        """切换流水线模式（etf / parse / batch / config）"""
        self._mode = mode
        self._step_status = {}
        self._redraw()

    def set_step_status(self, step_key: str, status: str):
        """更新单个步骤状态：pending / active / done / error"""
        self._step_status[step_key] = status
        self._redraw()

    def reset(self):
        """重置所有步骤状态"""
        self._step_status = {}
        self._redraw()

    def highlight(self, step_key: str):
        """高亮某个步骤为 active，之前的为 done，之后的为 pending"""
        steps = PIPELINE_STEPS.get(self._mode, [])
        found = False
        for label, key in steps:
            if key == step_key:
                self._step_status[key] = "active"
                found = True
            elif not found:
                self._step_status[key] = "done"
            else:
                self._step_status[key] = "pending"
        self._redraw()

    def _redraw(self):
        self._canvas.delete("all")
        steps = PIPELINE_STEPS.get(self._mode, [])
        if not steps:
            return

        w = self._canvas.winfo_width()
        if w < 50:
            w = 994

        n = len(steps)
        spacing = (w - 20) // max(n, 1)
        start_x = (w - (spacing * (n - 1))) // 2
        radius = 7

        self._step_labels.clear()
        self._step_circles.clear()
        self._connectors.clear()

        for i, (label, key) in enumerate(steps):
            cx = start_x + i * spacing
            cy = 20
            status = self._step_status.get(key, "pending")

            color = STEP_COLORS.get(status, "#CCCCCC")

            # 圆圈
            circle = self._canvas.create_oval(
                cx - radius, cy - radius,
                cx + radius, cy + radius,
                fill=color, outline=color,
                tags=(f"step_{key}",)
            )
            self._step_circles.append(circle)

            # 文字
            text_color = STEP_COLORS.get(f"{status}_text", "#333333")
            self._canvas.create_text(
                cx, cy + 22,
                text=label,
                fill=text_color,
                font=("Microsoft YaHei", 10),
                anchor="n",
                tags=(f"step_{key}",)
            )
            self._step_labels.append(label)

            # 连接线
            if i < n - 1:
                next_cx = start_x + (i + 1) * spacing
                line_color = "#0078D4" if status == "done" else "#CCCCCC"
                self._canvas.create_line(
                    cx + radius + 2, cy,
                    next_cx - radius - 2, cy,
                    fill=line_color, width=2,
                )

    def bind_step(self, step_key: str, callback):
        """绑定步骤点击事件"""
        self._canvas.tag_bind(f"step_{step_key}", "<Button-1>",
                              lambda e, k=step_key: callback(k))
        self._canvas.tag_bind(f"step_{step_key}", "<Enter>",
                              lambda e: self._canvas.config(cursor="hand2"))
        self._canvas.tag_bind(f"step_{step_key}", "<Leave>",
                              lambda e: self._canvas.config(cursor=""))
