"""
功能一：单视频解析
输入 BV号 → bili2text 下载字幕 → 保存到指定目录
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import queue
import time
from pathlib import Path

_log = logging.getLogger("single_parser")
_log.setLevel(logging.DEBUG)
_log.propagate = False
if not _log.handlers:
    _h = logging.FileHandler(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "single_parser.log"),
        encoding="utf-8"
    )
    _h.setFormatter(logging.Formatter("%(asctime)s [%(threadName)s] %(message)s"))
    _log.addHandler(_h)

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
    """解析单视频，保存字幕"""
    _log.info("=== parse_single START ===")
    _log.info("bv_id=%r  save_dir=%r", bv_id, save_dir)

    if cancel_event is None:
        cancel_event = threading.Event()

    output = Path(save_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    _log.info("output dir: %s  (exists=%s)", output, output.exists())

    # 已有转写文件则跳过
    existing_txt = list(output.glob("*.txt"))
    _log.info("existing_txt glob(*.txt) → %d files: %s", len(existing_txt), [str(p) for p in existing_txt])
    if existing_txt:
        _log.info("SKIP: found existing txt, returning skipped=True")
        if callback:
            callback("progress", f"已存在转写文件，跳过", 100)
        return {"success": True, "path": str(existing_txt[0]), "skipped": True}

    if callback:
        callback("progress", "启动 bili2text...", 0)

    b2t_dir, b2t_py, venv_py = _get_b2t_paths()
    _log.info("b2t_dir=%s  b2t_py=%s  venv_py=%s", b2t_dir, b2t_py, venv_py)
    cmd = [str(venv_py), str(b2t_py), "transcribe", bv_id.strip()]
    _log.info("Popen cmd: %s", cmd)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"  # 强制清零 stdio 缓冲，tqdm 进度条实时推送
    proc = subprocess.Popen(
        [str(venv_py), str(b2t_py), "transcribe", bv_id.strip()],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        bufsize=0,
        cwd=str(BILI2TEXT_DIR),
        env=env,
        creationflags=_creationflags
    )
    _log.info("Popen pid=%s", proc.pid)

    q = queue.Queue()

    def _reader(pipe, tag):
        try:
            buf = b''
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                buf += chunk
                # tqdm 用 \r 刷新而非 \n 换行，PIPE 下 readline 会攒到进程结束。
                # 这里按 \r / \n 实时切分，确保每条进度行立即入队。
                while True:
                    pos_r = buf.find(b'\r')
                    pos_n = buf.find(b'\n')
                    if pos_r == -1 and pos_n == -1:
                        break
                    # 取最近的分隔符
                    pos = min(
                        pos_r if pos_r != -1 else len(buf),
                        pos_n if pos_n != -1 else len(buf),
                    )
                    seg = buf[:pos]
                    buf = buf[pos + 1:]
                    if seg:
                        line = seg.decode("utf-8", errors="replace")
                        q.put((tag, line))
            # 残留尾部
            if buf:
                line = buf.decode("utf-8", errors="replace")
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
    line_count_err = 0
    line_count_out = 0

    while proc.poll() is None:
        if cancel_event.is_set():
            _log.info("CANCEL signal received, killing process")
            proc.kill()
            proc.wait()
            if callback:
                callback("cancelled", "用户取消了解析", 0)
            return {"success": False, "error": "用户取消了解析"}

        try:
            tag, line = q.get(timeout=1.0)
        except queue.Empty:
            # 长阶段心跳：每秒推 1% 进度，让 UI 条持续爬升而非静止 10 秒
            rng = _STAGE_RANGES.get(current_stage)
            if rng and (rng[1] - rng[0]) > 0.03:
                heartbeat_pct = last_pct + 1
                cap = int(rng[1] * 100) - 1  # 留 1% 余量，不顶到上限
                if heartbeat_pct <= cap:
                    last_pct = heartbeat_pct
                    if callback:
                        callback("progress", f"{last_stage_label or current_stage}  {heartbeat_pct}%", heartbeat_pct)
            continue

        if tag == 'out':
            stdout_chunks.append(line)
            line_count_out += 1
            if line_count_out <= 20:
                _log.debug("stdout[%d]: %r", line_count_out, line.rstrip('\n'))
        else:
            stderr_chunks.append(line)
            line_count_err += 1
            if line_count_err <= 40:
                _log.debug("stderr[%d]: %r", line_count_err, line.strip('\r\n')[:200])

        # 统一处理 stdout 和 stderr 中的进度信息
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
                _log.debug("progress: stage=%s pct=%s desc=%r", stage, pct, desc)
                if callback:
                    callback("progress", f"{desc}  {pct}%", pct)
        else:
            # 非 tqdm 行 → 检查是否阶段切换行（如 "准备中"、"下载中"）
            stage = _detect_stage(line_stripped)
            if stage and stage != current_stage:
                current_stage = stage
                last_stage_label = line_stripped
                rng = _STAGE_RANGES.get(stage)
                pct = int(rng[0] * 100) if rng else 0
                _log.debug("stage changed: %s → pct=%s from line %r", stage, pct, line_stripped[:100])
                if callback:
                    callback("progress", line_stripped, pct)

    _log.info("process ended. rc=%s  stderr_lines=%d  stdout_lines=%d",
              proc.returncode, line_count_err, line_count_out)

    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    _log.info("stdout tail: %r", stdout[-500:] if stdout else "(empty)")
    _log.info("stderr tail: %r", stderr[-500:] if stderr else "(empty)")

    if proc.returncode != 0:
        error_msg = stderr.strip() or stdout.strip() or "未知错误"
        _log.error("NONZERO exit: rc=%s  error=%r", proc.returncode, error_msg)
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
            _log.info("transcript path from stdout regex: %s", transcript_path)
            break

    # 回退：按修改时间取最新 txt
    if not (transcript_path and transcript_path.exists()):
        transcripts_dir = b2t_dir / ".b2t" / "transcripts" / "original"
        _log.info("fallback: checking %s  (exists=%s)", transcripts_dir, transcripts_dir.exists())
        if transcripts_dir.exists():
            txt_files = sorted(transcripts_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            _log.info("fallback: %d txt files found, newest=%s",
                      len(txt_files), str(txt_files[0]) if txt_files else "(none)")
            if txt_files:
                transcript_path = txt_files[0]

    if transcript_path and transcript_path.exists():
        dest = output / transcript_path.name
        shutil.copy2(transcript_path, dest)
        _log.info("copied transcript to dest: %s", dest)
        if callback:
            callback("done", f"字幕已保存到：{dest}", 100)
        return {"success": True, "path": str(dest)}

    error_msg = "无法找到转写结果文件"
    _log.error("transcript not found. transcript_path=%s", transcript_path)
    if callback:
        callback("error", error_msg, 0)
    return {"success": False, "error": error_msg}

