# -*- coding: utf-8 -*-
"""
增量解析记录管理
跟踪每个 BV 号的解析状态，24小时内已解析的视频不再重复解析
但结果仍合并入当天报告
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RECORDS_FILE = DATA_DIR / "parsed_records.json"


def _load_records() -> dict:
    """加载全部解析记录"""
    if not RECORDS_FILE.exists():
        return {}
    try:
        with open(RECORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save_records(records: dict):
    """保存解析记录"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RECORDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def is_parsed_today(bvid: str, date_str: str = None) -> bool:
    """
    检查 BV 号在今天（或指定日期）是否已解析。

    Args:
        bvid: 视频 BV 号
        date_str: 日期字符串 YYYYMMDD，默认今天

    Returns:
        True 表示该视频在今天已解析过
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    records = _load_records()
    return bvid in records.get(date_str, {})


def get_cached_video(bvid: str, date_str: str = None) -> dict | None:
    """
    获取已缓存视频的信息（含 transcript_path）。

    Returns:
        视频信息字典，或 None（未缓存或文件已不存在）
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    records = _load_records()
    day_records = records.get(date_str, {})
    cached = day_records.get(bvid)
    if cached is None:
        return None
    # 验证转写文件是否存在
    transcript_path = cached.get('transcript_path', '')
    if transcript_path and os.path.exists(transcript_path):
        return cached
    return None


def mark_parsed(bvid: str, video_info: dict, date_str: str = None):
    """
    标记 BV 号为今天已解析。

    Args:
        bvid: 视频 BV 号
        video_info: 视频信息字典，至少包含:
            - up_name: UP 主名称
            - title: 视频标题
            - transcript_path: 转写文件路径
            - aid: 视频 aid（可选）
            - pub_time: 发布时间（可选）
            - up_mid: UP 主 mid（可选）
            - up_weight: UP 主权重（可选）
        date_str: 日期字符串，默认今天
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    records = _load_records()
    if date_str not in records:
        records[date_str] = {}

    existing = records[date_str].get(bvid, {})
    existing.update(video_info)
    existing['parsed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    records[date_str][bvid] = existing
    _save_records(records)


def get_today_parsed_bvids(date_str: str = None) -> set:
    """
    获取今天所有已解析的 BV 号集合。

    Args:
        date_str: 日期字符串，默认今天
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    records = _load_records()
    return set(records.get(date_str, {}).keys())


def get_period_title(now: datetime = None) -> str:
    """
    根据当前北京时间返回时段名称。

    时段划分：
        - 09:00-09:30 → 早盘预览
        - 09:30-11:30 → 早盘中
        - 11:30-13:00 → 午盘预览
        - 13:00-15:00 → 午盘中
        - 15:00-18:00 → 今日复盘
        - 18:00-次日09:00 → 明日策略
    """
    if now is None:
        now = datetime.now()
    t = now.time()
    h = t.hour
    m = t.minute

    if h == 9 and m < 30:
        return "早盘预览"
    elif (h == 9 and m >= 30) or h == 10 or (h == 11 and m < 30):
        return "早盘中"
    elif (h == 11 and m >= 30) or h == 12:
        return "午盘预览"
    elif h == 13 or h == 14:
        return "午盘中"
    elif 15 <= h < 18:
        return "今日复盘"
    else:
        return "明日策略"


def cleanup_old_records(days: int = 7):
    """
    清理超过指定天数的旧记录。

    Args:
        days: 保留天数，默认 7 天
    """
    records = _load_records()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    kept = {k: v for k, v in records.items() if k >= cutoff}
    if len(kept) != len(records):
        _save_records(kept)

