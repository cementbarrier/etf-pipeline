"""
功能一：单视频解析
输入 BV号 → bili2text 下载字幕 → 保存到指定目录
"""
import re
import shutil
import subprocess
import sys
import threading
import queue
import time
from pathlib import Path

BILI2TEXT_DIR = Path(r"D:\bili2text")
BILI2TEXT_PY = BILI2TEXT_DIR / "main.py"
VENV_PYTHON = BILI2TEXT_DIR / ".venv" / "Scripts" / "python.exe"


def _get_b2t_paths():
    """动态获取 bili2text 路径，优先读配置"""
    try:
        from backend.config_manager import get_bili2text_path
        d = get_bili2text_path()
        if d.exists():
            return d, d / "main.py", d / ".venv" / "Scripts" / "python.exe"
    except Exception:
        pass
    return BILI2TEXT_DIR, BILI2TEXT_PY, VENV_PYTHON

# Windows 下隐藏子进程窗口
_creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ── bili2text tqdm 进度解析 ──

# 阶段关键词（中文/英文）→ 阶段名
_STAGE_KW = [
    (re.compile(r'已排队|Queued'), "queued"),
    (re.compile(r'准备中|Preparing'), "preparing"),
    (re.compile(r'下载中|Downloading'), "downloading"),
    (re.compile(r'提取音频|Extracting'), "extracting_audio"),
    (re.compile(r'转写中|Transcribing'), "transcribing"),
    (re.compile(r'写入中|Writing'), "writing_outputs"),
    (re.compile(r'更新索引|Indexing'), "indexing"),
    (re.compile(r'已完成|Completed|完成'), "completed"),
]

# 各阶段对应的总体进度区间（来自 bili2text progress.py）
_STAGE_RANGES = {
    "queued":            (0.0, 0.0),
    "preparing":         (0.0, 0.05),
    "downloading":       (0.05, 0.35),
    "extracting_audio":  (0.35, 0.55),
    "transcribing":      (0.55, 0.90),
    "writing_outputs":   (0.90, 0.96),
    "indexing":          (0.96, 0.99),
    "completed":         (1.0, 1.0),
}

# 匹配 tqdm 进度条行：\r{描述}:  {pct}%|...
_TQDM_LINE = re.compile(r'[\r]?(.+?)\s*:\s+(\d+)%\|')


def _detect_stage(text: str) -> str | None:
    """从文本中检测阶段关键词，返回阶段名"""
    for pattern, stage in _STAGE_KW:
        if pattern.search(text):
            return stage
    return None


def _calc_overall_pct(stage: str, stage_pct: float) -> int:
    """根据阶段和阶段内进度计算总体百分比"""
    rng = _STAGE_RANGES.get(stage)
    if not rng:
        return 0
    start, end = rng
    if start == end:
        return int(start * 100)
    return int((start + (end - start) * stage_pct / 100) * 100)


def parse_single(bv_id: str, save_dir: str, callback=None, cancel_event=None):
    """解析单视频，保存字幕

    Args:
        bv_id: BV号（如 BV1xx411c7mD）
        save_dir: 保存目录路径
        callback: 可选回调函数，接收 (type, message, percent)
            type: "progress" / "done" / "error" / "cancelled"
        cancel_event: threading.Event，设为 True 时中止解析
    """
    if cancel_event is None:
        cancel_event = threading.Event()

    output = Path(save_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    # 已有转写文件则跳过
    existing_txt = list(output.glob("*.txt"))
    if existing_txt:
        if callback:
            callback("progress", f"已存在转写文件，跳过", 100)
        return {"success": True, "path": str(existing_txt[0]), "skipped": True}

    if callback:
        callback("progress", "启动 bili2text...", 0)

    b2t_dir, b2t_py, venv_py = _get_b2t_paths()
    proc = subprocess.Popen(
        [str(venv_py), str(b2t_py), "transcribe", bv_id.strip()],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(BILI2TEXT_DIR),
        creationflags=_creationflags
    )

    q = queue.Queue()

    def _reader(pipe, tag):
        try:
            for line in iter(pipe.readline, ''):
                q.put((tag, line))
        except Exception:
            pass
        finally:
            pipe.close()

    threading.Thread(target=_reader, args=(proc.stdout, 'out'), daemon=True).start()
    threading.Thread(target=_reader, args=(proc.stderr, 'err'), daemon=True).start()

    stdout_chunks = []
    stderr_chunks = []
    current_stage = "preparing"
    last_pct = 0
    last_stage_label = ""

    while proc.poll() is None:
        if cancel_event.is_set():
            proc.kill()
            proc.wait()
            if callback:
                callback("cancelled", "用户取消了解析", 0)
            return {"success": False, "error": "用户取消了解析"}

        try:
            tag, line = q.get(timeout=1.0)
        except queue.Empty:
            continue

        if tag == 'out':
            stdout_chunks.append(line)
            continue

        # 解析 stderr 中的 tqdm 进度
        stderr_chunks.append(line)
        line_stripped = line.strip('\r\n')

        # 尝试匹配 tqdm 进度条行：{描述}: {pct}%|...
        tqdm_match = _TQDM_LINE.match(line_stripped)
        if tqdm_match:
            desc = tqdm_match.group(1).strip()
            stage_pct = int(tqdm_match.group(2))
            stage = _detect_stage(desc) or current_stage
            current_stage = stage
            pct = _calc_overall_pct(stage, stage_pct)
            if pct != last_pct:
                last_pct = pct
                if callback:
                    callback("progress", f"{desc}  {pct}%", pct)
        else:
            # 非 tqdm 行 → 检查是否阶段切换行（如 "准备中"、"下载中"）
            stage = _detect_stage(line_stripped)
            if stage:
                current_stage = stage
                last_stage_label = line_stripped

    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)

    if proc.returncode != 0:
        error_msg = stderr.strip() or stdout.strip() or "未知错误"
        if callback:
            callback("error", f"解析失败：{error_msg}", 0)
        return {"success": False, "error": error_msg}

    if callback:
        callback("progress", "正在保存字幕文件...", 98)

    # 从 stdout 解析转写文件路径
    transcript_path = None
    for line in stdout.splitlines():
        match = re.search(r'(?:转写结果已保存|transcript\s+saved)[：:]\s*(.+)', line)
        if match:
            transcript_path = b2t_dir / match.group(1).strip()
            break

    # 回退：按修改时间取最新 txt
    if not (transcript_path and transcript_path.exists()):
        transcripts_dir = b2t_dir / ".b2t" / "transcripts" / "original"
        if transcripts_dir.exists():
            txt_files = sorted(transcripts_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            if txt_files:
                transcript_path = txt_files[0]

    if transcript_path and transcript_path.exists():
        dest = output / transcript_path.name
        shutil.copy2(transcript_path, dest)
        if callback:
            callback("done", f"字幕已保存到：{dest}", 100)
        return {"success": True, "path": str(dest)}

    error_msg = "无法找到转写结果文件"
    if callback:
        callback("error", error_msg, 0)
    return {"success": False, "error": error_msg}

