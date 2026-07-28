"""
功能二：批量解析
对选中的UP主查询最新视频 → 批量调bili2text → 统一 AI 摘要
"""
import sys
import os
import re
import json
import time
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("batch_parser")

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).parent.parent

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backend.single_parser import parse_single, BILI2TEXT_DIR, BILI2TEXT_PY, VENV_PYTHON
import step1_fetch_videos as fetcher

SUMMARY_FILENAME = "ai_summary.txt"
BATCH_SUMMARY_FILENAME = "批次总结_{date}.txt"

# 批次总结文件名的正则（用于扫描时排除自身）
import re as _re
_BATCH_SUMMARY_PATTERN = _re.compile(r"^批次总结_\d{4}-\d{2}-\d{2}\.txt$")


def _is_valid_bvid(bvid: str) -> bool:
    """判断是否为合法 BV 号（必须以 BV 开头）"""
    return bool(bvid) and bvid.startswith("BV")

# 每视频最多送入 LLM 的字数（可从 settings.json 覆盖）
MAX_PER_VIDEO = 1500


def _get_max_per_video() -> int:
    """从配置读取 MAX_PER_VIDEO，默认 1500"""
    try:
        from backend.config_manager import get_setting
        val = get_setting("max_per_video_chars")
        return int(val) if val else MAX_PER_VIDEO
    except Exception:
        return MAX_PER_VIDEO


def batch_parse(uid_list: list, save_dir: str, callback=None, cancel_event=None, target_date=None):
    """批量解析选中UP主的最新视频

    两阶段执行：
      Phase 1 — 拉取视频 + bili2text 转写（逐个进行）
      Phase 2 — 全部转写完成后，一次性生成批次总结文档

    Args:
        uid_list: UID列表
        save_dir: 保存根目录
        callback: 回调函数 (type, message, percent)
        cancel_event: threading.Event，设为 True 时中止
        target_date: 目标日期 'YYYY-MM-DD'，默认今天
    """
    import threading as _th
    if cancel_event is None:
        cancel_event = _th.Event()

    # 统一日期来源：target_date 优先，否则用今天
    effective_date = _parse_effective_date(target_date)

    cookies = fetcher.load_cookies()
    if not cookies:
        if callback:
            callback("error", "B站Cookie无效，请检查 config/bilibili_cookies.txt", 0)
        return {"success": False, "error": "Cookie无效"}

    headers = fetcher.build_headers(cookies)
    total = len(uid_list)
    results = []

    # ── Phase 1: 拉取 + 转写 ──
    for idx, uid in enumerate(uid_list):
        if cancel_event.is_set():
            if callback:
                callback("cancelled", f"批量解析已取消，已完成 {idx}/{total} 个UP主", 0)
            return _build_return(results, cancelled=True)

        up_pct_start = int(idx / total * 100)
        if callback:
            callback("progress", f"正在查询UP主 {uid}... ({idx+1}/{total})", up_pct_start)

        date_label = target_date if target_date else "今日"
        videos = fetcher.get_up_videos(uid, headers, target_date=target_date, cancel_event=cancel_event)

        if cancel_event.is_set():
            if callback:
                callback("cancelled", f"批量解析已取消", 0)
            return _build_return(results, cancelled=True)

        if not videos:
            up_pct_next = int((idx + 1) / total * 100)
            if callback:
                callback("progress", f"UP主 {uid} {date_label}无新视频，跳过", up_pct_next)
            continue

        up_pct_query_done = min(int((idx + 0.3) / total * 100), 99)
        if callback:
            callback("progress", f"UP主 {uid} 有 {len(videos)} 个新视频，开始转写...", up_pct_query_done)

        for v_idx, v in enumerate(videos):
            if cancel_event.is_set():
                if callback:
                    callback("cancelled", f"批量解析已取消", 0)
                return _build_return(results, cancelled=True)

            bvid = v.get("bvid")
            title = v.get("title", "")
            if not bvid:
                continue

            batch_pct = min(int((idx + 0.3 + 0.7 * (v_idx + 1) / len(videos)) / total * 100), 99)

            date_prefix = effective_date.strftime("%m%d")
            video_dir = Path(save_dir) / date_prefix / uid / bvid
            video_dir.mkdir(parents=True, exist_ok=True)

            existing_txt = list(video_dir.glob("*.txt"))
            if existing_txt:
                if callback:
                    callback("progress", f"  跳过（已有转写）：{title} ({bvid})", batch_pct)
                results.append({"uid": uid, "bvid": bvid, "title": title, "video_dir": str(video_dir), "success": True, "path": str(existing_txt[0]), "skipped": True})
                continue

            if callback:
                callback("progress", f"  转写：{title} ({bvid})", batch_pct)

            result = parse_single(bvid, str(video_dir), cancel_event=cancel_event)
            results.append({"uid": uid, "bvid": bvid, "title": title, "video_dir": str(video_dir), **result})
            time.sleep(1)

    # ── Phase 2: 生成批次总结文档 ──
    today = effective_date.strftime("%Y-%m-%d")
    date_prefix = effective_date.strftime("%m%d")
    today_dir = Path(save_dir) / date_prefix
    existing_summary = today_dir / BATCH_SUMMARY_FILENAME.format(date=today)

    transcribe_success = [r for r in results if r.get("success") and r.get("path") and not r.get("skipped")]
    new_count = len(transcribe_success)

    if new_count == 0:
        skipped_count = sum(1 for r in results if r.get("skipped"))
        if existing_summary.exists():
            if callback:
                callback("done", f"批量解析完成：无新增转写，当天总结已存在（存量 {skipped_count} 个）", 100)
            return _build_return(results, summarized=1)
        # 有存量转写但没有总结 → 补生成
        all_success = [r for r in results if r.get("success") and r.get("path")]
        if all_success and today_dir.exists():
            if callback:
                callback("progress", f"无新增转写，但当天总结缺失，正在补生成（共 {len(all_success)} 个视频）...", 99)
            summary_input = []
            for r in all_success:
                summary_input.append(r)
            batch_summary_path = _generate_batch_summary(save_dir, summary_input, effective_date)
            if callback:
                if batch_summary_path:
                    callback("done", f"批量解析完成：总结已补生成（存量 {skipped_count} 个已有转写）", 100)
                else:
                    callback("done", f"批量解析完成：总结生成失败（存量 {skipped_count} 个已有转写）", 100)
            return _build_return(results, summarized=(1 if batch_summary_path else 0))
        else:
            if callback:
                callback("done", f"批量解析完成：无新增转写，跳过 AI 总结（存量 {skipped_count} 个已有转写）", 100)
            return _build_return(results)

    if existing_summary.exists() and today_dir.exists():
        summary_input = list(transcribe_success)
        seen = {(r["uid"], r["bvid"]) for r in transcribe_success}
        for txt_path in today_dir.rglob("*.txt"):
            if txt_path.name == SUMMARY_FILENAME or _BATCH_SUMMARY_PATTERN.match(txt_path.name):
                continue
            bvid = txt_path.parent.name
            uid = txt_path.parent.parent.name
            if not _is_valid_bvid(bvid):
                continue
            if (uid, bvid) not in seen:
                seen.add((uid, bvid))
                summary_input.append({"uid": uid, "bvid": bvid, "title": "", "path": str(txt_path)})
        if callback:
            callback("progress", f"转写完成，当天已有总结，正在重新汇总（共 {len(summary_input)} 个视频）...", 99)
    else:
        summary_input = transcribe_success
        if callback:
            callback("progress", f"转写完成，正在生成批次总结（新增 {new_count} 个视频）...", 99)

    batch_summary_path = _generate_batch_summary(save_dir, summary_input, effective_date)

    # ── 邮件通知 ──
    try:
        from backend.notifier import notify_batch_done
        notify_batch_done(save_dir, new_count, len(results), batch_summary_path)
    except Exception:
        pass

    # ── 飞书通知 ──
    try:
        from backend.feishu_notifier import notify_batch_done as notify_feishu_batch, send_transcript_text
        notify_feishu_batch()
        if batch_summary_path:
            with open(batch_summary_path, "r", encoding="utf-8") as _f:
                _summary_text = _f.read()
            send_transcript_text(_summary_text)
    except Exception as e:
        logger.debug(f"飞书通知失败: {e}")

    if callback:
        done_msg = f"批量解析完成：新增转写 {new_count}/{len(results)} 个视频"
        if batch_summary_path:
            done_msg += f"，总结已生成"
        callback("done", done_msg, 100)

    return _build_return(results, summarized=(1 if batch_summary_path else 0))


def _parse_effective_date(target_date: str | None) -> datetime:
    """解析 target_date，异常时 fallback 到今天"""
    if target_date:
        try:
            return datetime.strptime(target_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(f"target_date 格式异常: {target_date!r}，回退到今日")
    return datetime.now()


# ── 批次总结生成（拆分为 3 个子函数 #15）──

def _build_prompt(parts: list[str], invalid_bvids: list[str] | None = None) -> str | None:
    """构建发给 LLM 的批次总结 prompt"""
    if not parts:
        return None

    all_videos = "\n\n".join(parts)

    prompt = f"""以下是本批次中 {len(parts)} 个B站财经视频的转写文本。请输出一份总结文档，严格按以下两段格式：

一、视频观点速览
| BV号 | 主要观点 |

二、入场参考
| 板块/标的 | 入场理由 |

要求：
- 第一部分：每个视频一行，用80字以内提炼核心观点
- 第二部分：仅列出明确看多/可入场的标的，看空/分歧/观望全部略过；入场理由中附带对应BV号
- 若第二部分无可入场标的，写"本批次无可入场标的"
- 不要开头结尾、不要解释
- 转写文本可能存在语音识别错误，请根据上下文纠正为正确的股票术语。常见错误示例：'5G线'→'5日线'或'5周线'，'黄氏线'→'5日线'或'20日线'，'50线'→'5日线'，数字/字母与股票术语混淆时优先理解为均线指标

视频文本：
{all_videos}"""
    return prompt


def _parse_summary_to_json(result: str, today: str) -> dict:
    """从 LLM 返回文本解析出结构化 JSON"""
    videos = []
    entry_signals = []

    video_pattern = re.compile(r"^\|\s*(BV[0-9A-Za-z]+)\s*\|\s*(.+?)\s*\|", re.MULTILINE)
    for m in video_pattern.finditer(result):
        bvid = m.group(1)
        opinion = m.group(2).strip()
        if bvid.startswith("BV"):
            videos.append({"bvid": bvid, "opinion": opinion})

    entry_section_start = result.find("二、入场参考")
    if entry_section_start != -1:
        entry_section = result[entry_section_start:]
        entry_pattern = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", re.MULTILINE)
        header_skipped = False
        for m in entry_pattern.finditer(entry_section):
            col1 = m.group(1).strip()
            col2 = m.group(2).strip()
            if not header_skipped and ("板块" in col1 or "标的" in col1):
                header_skipped = True
                continue
            if col1.startswith("-") and col2.startswith("-"):
                continue
            if "无可入场" in col1 or "无可入场" in col2:
                break
            entry_signals.append({"sector": col1, "reason": col2})

    return {
        "date": today,
        "video_count": len(videos),
        "videos": videos,
        "entry_signals": entry_signals,
        "raw_text": result,
    }


def _save_reports(save_dir: str, result: str, json_data: dict, today: str, date_prefix: str = None):
    """保存 txt 和 json 两份报告

    Args:
        date_prefix: 如 '0725'，指定后报告写入 save_dir/date_prefix/ 子目录。
                     不传则写入 save_dir 根目录（向下兼容但推荐传入）。
    """
    target_dir = Path(save_dir)
    if date_prefix:
        target_dir = target_dir / date_prefix
    target_dir.mkdir(parents=True, exist_ok=True)

    report_path = target_dir / BATCH_SUMMARY_FILENAME.format(date=today)
    report_path.write_text(result, encoding="utf-8")

    json_path = target_dir / f"批次总结_{today}.json"
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(report_path)


def _generate_batch_summary(save_dir: str, transcribe_success: list, effective_date=None) -> str | None:
    """
    将批次内全部转写结果一次发给 LLM，生成总结文档。

    Args:
        save_dir: 保存目录
        transcribe_success: 转写成功列表
        effective_date: 目标日期（datetime），默认今天

    Returns:
        生成的文件路径，失败返回 None
    """
    from backend.llm_client import chat

    if effective_date is None:
        effective_date = datetime.now()

    limit = _get_max_per_video()
    parts = []
    invalid_bvids = []
    for r in transcribe_success:
        bvid = r["bvid"]
        if not _is_valid_bvid(bvid):
            invalid_bvids.append(bvid or "(空)")
            continue
        title = r["title"]
        try:
            text = Path(r["path"]).read_text(encoding="utf-8")[:limit]
        except Exception:
            continue
        parts.append(f"<video bvid=\"{bvid}\" title=\"{title}\">\n{text}\n</video>")

    prompt = _build_prompt(parts)
    if not prompt:
        return None

    try:
        result = chat(prompt)
    except Exception:
        return None

    if not result:
        return None

    today = effective_date.strftime("%Y-%m-%d")
    date_prefix = effective_date.strftime("%m%d")
    json_data = _parse_summary_to_json(result, today)
    return _save_reports(save_dir, result, json_data, today, date_prefix)


def _build_return(results: list, cancelled=False, summarized=0):
    success_count = sum(1 for r in results if r.get("success"))
    return {
        "success": not cancelled,
        "cancelled": cancelled,
        "total": len(results),
        "success_count": success_count,
        "summarized": summarized,
        "results": results,
    }


def regenerate_summary_for_today(save_dir: str, callback=None, cancel_event=None):
    """扫描 save_dir 下当天转写 txt，重新生成批次总结文档

    Args:
        save_dir: 批量解析保存根目录
        callback: 回调 (type, message, percent)
        cancel_event: threading.Event
    """
    import threading as _th
    if cancel_event is None:
        cancel_event = _th.Event()

    root = Path(save_dir)
    if not root.exists():
        if callback:
            callback("error", f"保存目录不存在：{save_dir}", 0)
        return {"success": False, "error": "目录不存在"}

    today = datetime.now().strftime("%Y-%m-%d")
    date_prefix = datetime.now().strftime("%m%d")
    today_dir = root / date_prefix

    entries = []
    if today_dir.exists():
        for txt_path in today_dir.rglob("*.txt"):
            if txt_path.name == SUMMARY_FILENAME or _BATCH_SUMMARY_PATTERN.match(txt_path.name):
                continue
            bvid = txt_path.parent.name
            if not _is_valid_bvid(bvid):
                continue
            entries.append({"bvid": bvid, "title": f"{txt_path.parent.parent.name}/{bvid}", "path": str(txt_path)})

    if not entries:
        if callback:
            callback("done", "未找到当天转写文件", 100)
        return {"success": True, "total": 0, "summarized": 0}

    if callback:
        callback("progress", f"发现 {len(entries)} 个转写文件，重新生成批次总结...", 50)

    result = _generate_batch_summary(save_dir, entries, effective_date=datetime.now())

    if callback:
        if result:
            callback("done", f"批次总结已生成：{os.path.basename(result)}", 100)
        else:
            callback("error", "批次总结生成失败", 100)

    return {"success": result is not None, "total": len(entries), "summarized": 1 if result else 0}


