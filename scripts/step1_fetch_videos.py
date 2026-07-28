# -*- coding: utf-8 -*-
"""
阶段1：B站API拉取当日最新视频
读取 stock_up_list.txt，调用 B站 API 批量拉取每个 UP 主 24 小时内新视频
"""

import os
import sys
import json
import time
import hashlib
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).parent.parent

# 统一从 config_manager 导入 CONFIG_DIR，避免多处重复计算
from backend.config_manager import CONFIG_DIR
from functools import reduce
from urllib.parse import urlencode

# 增量解析：导入解析记录管理模块
sys.path.insert(0, str(PROJECT_ROOT))
from backend.parsed_records import is_parsed_today, get_cached_video, get_today_parsed_bvids

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "fetch.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_up_list():
    """读取 UP 主列表配置文件（Excel）"""
    import pandas as pd
    up_list = []
    config_path = CONFIG_DIR / "stock_up_list.xlsx"
    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        return up_list

    df = pd.read_excel(config_path)
    for _, row in df.iterrows():
        mid = str(int(row.iloc[0])) if not pd.isna(row.iloc[0]) else None
        name = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else None
        weight = int(row.iloc[2]) if not pd.isna(row.iloc[2]) else 1
        if mid and name:
            up_list.append({'mid': mid, 'name': name, 'weight': weight})
    logger.info(f"加载 {len(up_list)} 位 UP 主")
    return up_list


def load_cookies():
    """从 Netscape 格式 cookies 文件提取 SESSDATA 等关键值"""
    cookie_path = CONFIG_DIR / "bilibili_cookies.txt"
    cookies = {}
    if not cookie_path.exists():
        logger.error(f"Cookies 文件不存在: {cookie_path}")
        return cookies

    with open(cookie_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.strip().split('\t')
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]

    return cookies


def build_headers(cookies):
    """构建请求头"""
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Cookie': cookie_str,
        'Referer': 'https://space.bilibili.com/',
    }


# ---- WBI 签名 ----
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 52, 44, 34,
]

def get_mixin_key(orig: str) -> str:
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]


_wbi_keys_cache = {"img_key": "", "sub_key": "", "ts": 0}

def get_wbi_keys(headers):
    """获取 wbi 签名密钥，缓存 30 分钟"""
    now = time.time()
    if now - _wbi_keys_cache["ts"] < 1800 and _wbi_keys_cache["img_key"]:
        return _wbi_keys_cache["img_key"], _wbi_keys_cache["sub_key"]

    try:
        resp = requests.get("https://api.bilibili.com/x/web-interface/nav", headers=headers, timeout=10)
        data = resp.json().get("data", {})
        wbi_img = data.get("wbi_img", {})
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")
        img_key = img_url.split("/")[-1].split(".")[0]
        sub_key = sub_url.split("/")[-1].split(".")[0]
        _wbi_keys_cache["img_key"] = img_key
        _wbi_keys_cache["sub_key"] = sub_key
        _wbi_keys_cache["ts"] = now
        return img_key, sub_key
    except Exception:
        return "", ""


def sign_params(params, img_key, sub_key):
    """对参数进行 wbi 签名"""
    mixin_key = get_mixin_key(img_key + sub_key)
    params["wts"] = int(time.time())
    sorted_params = sorted(params.items())
    query = urlencode(sorted_params)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params


def get_up_videos(mid, headers, target_date=None, hours=None, cancel_event=None):
    """拉取指定 UP 主的视频列表

    Args:
        mid: UP主mid
        headers: 请求头
        target_date: 目标日期字符串 'YYYY-MM-DD'，默认今天。仅保留该日发布的视频
        hours: 兼容旧参数，指定最近N小时（target_date优先级更高）
        cancel_event: threading.Event，设为 True 时提前中止
    """
    if cancel_event and cancel_event.is_set():
        return []

    params = {
        'mid': mid,
        'ps': 30,
        'pn': 1,
        'order': 'pubdate',
    }

    # WBI 签名
    img_key, sub_key = get_wbi_keys(headers)
    if img_key and sub_key:
        params = sign_params(params, img_key, sub_key)

    # 计算过滤窗口
    if target_date:
        try:
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
            day_start = target_dt
            day_end = target_dt + timedelta(days=1)
        except ValueError:
            logger.warning(f"  日期格式错误: {target_date}，回退到今天")
            target_dt = datetime.now()
            day_start = target_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
    elif hours:
        day_start = datetime.now() - timedelta(hours=hours)
        day_end = datetime.now() + timedelta(hours=1)  # 上界宽松
    else:
        # 默认：仅今天
        now = datetime.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

    try:
        resp = requests.get(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            params=params, headers=headers, timeout=8
        )
        if cancel_event and cancel_event.is_set():
            return []
        data = resp.json()
        if data.get('code') != 0:
            logger.warning(f"  API 返回错误 mid={mid}: {data.get('message')}")
            return []

        videos = data.get('data', {}).get('list', {}).get('vlist', [])

        recent_videos = []
        for v in videos:
            pub_ts = v.get('created', 0)
            pub_time = datetime.fromtimestamp(pub_ts)
            if day_start <= pub_time < day_end:
                # 用 or '' 而非 get(..., '')：B站 API 可能返回 null，.get 只在 key 不存在时用默认值
                description = v.get('description') or ''
                recent_videos.append({
                    'aid': v.get('aid'),
                    'bvid': v.get('bvid'),
                    'title': v.get('title'),
                    'description': description,
                    'pub_time': pub_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'duration': v.get('length', ''),
                    'play': v.get('play', 0),
                })

        return recent_videos

    except Exception as e:
        logger.error(f"  拉取失败 mid={mid}: {e}")
        return []


def enrich_description(bvid, headers):
    """兜底：通过 view API 获取视频完整简介（space/arc/search 可能返回空）"""
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers=headers, timeout=10
        )
        data = resp.json()
        if data.get('code') == 0:
            desc = data.get('data', {}).get('desc', '')
            return desc if desc else ''
    except Exception:
        pass
    return ''


def get_up_name(mid, headers):
    """根据 UID 查询 UP 主昵称"""
    params = {'mid': mid}
    img_key, sub_key = get_wbi_keys(headers)
    if img_key and sub_key:
        params = sign_params(params, img_key, sub_key)
    try:
        resp = requests.get(
            "https://api.bilibili.com/x/space/wbi/acc/info",
            params=params, headers=headers, timeout=10
        )
        data = resp.json()
        if data.get('code') == 0:
            return data['data'].get('name', '')
    except Exception:
        pass
    return ''


def filter_stock_videos(videos):
    """过滤：保留包含股票相关关键词的视频"""
    keywords = [
        '股票', '大盘', '赛道', '个股', '持仓', '建仓', '复盘',
        'ETF', 'etf', 'A股', '涨停', '跌停', '板块', '行情',
        '选股', '策略', '交易', '投资', '牛市', '熊市', '反弹',
        '趋势', '支撑', '压力', '成交量', '资金', '北向',
    ]
    filtered = []
    for v in videos:
        title_lower = v['title'].lower()
        if any(kw.lower() in title_lower for kw in keywords):
            filtered.append(v)
    return filtered


def save_video_meta(videos, up_name):
    """保存视频元信息到 JSON"""
    today = datetime.now().strftime('%Y%m%d')
    meta_dir = DATA_DIR / "videos" / today
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / f"{up_name}_{today}.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(videos, f, ensure_ascii=False, indent=2)
    return meta_path


def main(target_date=None):
    date_label = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
    logger.info("=" * 50)
    logger.info(f"开始拉取 {date_label} UP 主视频")
    logger.info("=" * 50)

    up_list = load_up_list()
    if not up_list:
        logger.error("UP 主列表为空，请在 config/stock_up_list.txt 中添加 UP 主")
        return []

    cookies = load_cookies()
    if not cookies:
        logger.error("Cookies 无效")
        return []

    headers = build_headers(cookies)
    all_videos = []

    today_str = datetime.now().strftime('%Y%m%d')
    skip_count = 0
    new_count = 0

    for up in up_list:
        logger.info(f"拉取 {up['name']} (mid={up['mid']}) ...")
        time.sleep(0.5)  # 礼貌间隔

        videos = get_up_videos(up['mid'], headers, target_date=target_date)
        stock_videos = filter_stock_videos(videos)

        for v in stock_videos:
            v['up_name'] = up['name']
            v['up_mid'] = up['mid']
            v['up_weight'] = up['weight']

            # 兜底：space/arc/search 的 description 可能为空，用 view API 补充
            # 注意：用 or '' 防止 B站 API 返回 null 导致 None.strip() 异常
            if not (v.get('description') or '').strip():
                desc = enrich_description(v['bvid'], headers)
                if desc:
                    v['description'] = desc
                    logger.info(f"  ✓ 简介已补充 ({len(desc)} 字符)")

            # ── 增量解析检查 ──
            bvid = v.get('bvid', '')
            cached = get_cached_video(bvid, today_str) if bvid else None
            if cached and cached.get('transcript_path'):
                v['_incremental_skip'] = True
                v['transcript_path'] = cached['transcript_path']
                v['transcript_method'] = cached.get('transcript_method', 'cached')
                v['transcript_length'] = cached.get('transcript_length', 0)
                skip_count += 1
                logger.info(f"  ⊘ 跳过(已解析): {v['title'][:40]}")
            else:
                v['_incremental_skip'] = False
                new_count += 1

        if stock_videos:
            save_video_meta(stock_videos, up['name'])
            all_videos.extend(stock_videos)
            new_in_batch = sum(1 for v in stock_videos if not v.get('_incremental_skip'))
            skip_in_batch = sum(1 for v in stock_videos if v.get('_incremental_skip'))
            logger.info(f"  → {len(stock_videos)} 个相关视频 (新:{new_in_batch} 跳过:{skip_in_batch}) (共 {len(videos)} 个)")
        else:
            logger.info(f"  → 当日无相关视频")

    logger.info(f"\n总计: {len(all_videos)} 个待处理视频 (新:{new_count} 增量跳过:{skip_count})")

    # 保存合并的元信息（含增量标记），供下游步骤使用
    combined_path = DATA_DIR / "videos" / today_str / "all_videos_with_skip.json"
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    with open(combined_path, 'w', encoding='utf-8') as f:
        json.dump(all_videos, f, ensure_ascii=False, indent=2)
    logger.info(f"合并元信息已保存: {combined_path}")
    return all_videos


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='拉取B站UP主视频')
    parser.add_argument('--date', type=str, default=None, help='指定日期 YYYY-MM-DD，默认今天')
    args = parser.parse_args()
    result = main(target_date=args.date)
    # 输出 JSON 供下游模块使用
    print(json.dumps(result, ensure_ascii=False, indent=2))

