# -*- coding: utf-8 -*-
"""
阶段2：下载视频音频流
使用 yt-dlp 批量下载当日视频的音频轨道（仅音频，降低存储）
"""

import os
import sys
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
COOKIE_FILE = PROJECT_ROOT / "config" / "bilibili_cookies.txt"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "download.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_video_meta():
    """加载当日所有视频元信息"""
    today = datetime.now().strftime('%Y%m%d')
    video_dir = DATA_DIR / "videos" / today
    if not video_dir.exists():
        logger.error(f"视频元信息目录不存在: {video_dir}")
        return []

    all_videos = []
    for f in video_dir.glob("*.json"):
        with open(f, 'r', encoding='utf-8') as fp:
            videos = json.load(fp)
            all_videos.extend(videos)

    logger.info(f"加载 {len(all_videos)} 个视频元信息")
    return all_videos


def download_audio(video, output_dir):
    """使用 yt-dlp 下载音频"""
    bvid = video.get('bvid')
    aid = video.get('aid')
    title = video.get('title', '').replace('/', '_').replace('\\', '_')

    # 安全的文件名
    safe_title = title[:50]
    out_template = str(output_dir / f"{bvid}_{safe_title}")

    cmd = [
        'yt-dlp',
        f'https://www.bilibili.com/video/{bvid}',
        '-f', 'bestaudio[ext=m4a]/bestaudio',
        '--extract-audio',
        '--audio-format', 'mp3',
        '--audio-quality', '0',
        '-o', f'{out_template}.%(ext)s',
        '--cookies', str(COOKIE_FILE),
        '--no-playlist',
        '--socket-timeout', '30',
        '--retries', '3',
        '--quiet',
        '--no-warnings',
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            # 查找输出文件
            for ext in ['mp3', 'm4a']:
                output_path = Path(f"{out_template}.{ext}")
                if output_path.exists():
                    return str(output_path)
        else:
            logger.warning(f"  下载失败 {bvid}: {result.stderr[-200:]}")
            return None
    except subprocess.TimeoutExpired:
        logger.warning(f"  下载超时 {bvid}")
        return None
    except Exception as e:
        logger.error(f"  下载异常 {bvid}: {e}")
        return None


def main():
    logger.info("=" * 50)
    logger.info("开始下载当日视频音频")
    logger.info("=" * 50)

    videos = load_video_meta()
    if not videos:
        logger.error("无视频元信息，请先执行 step1_fetch_videos.py")
        return []

    today = datetime.now().strftime('%Y%m%d')
    audio_dir = DATA_DIR / "videos" / today / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, v in enumerate(videos, 1):
        # ── 增量解析：跳过已缓存视频 ──
        if v.get('_incremental_skip') and v.get('transcript_path'):
            v['audio_path'] = None  # 不需要重新下载音频
            results.append(v)
            logger.info(f"[{i}/{len(videos)}] ⊘ 跳过(已解析): {v['up_name']}: {v.get('title', '')[:40]}")
            continue

        logger.info(f"[{i}/{len(videos)}] {v['up_name']}: {v['title'][:40]}")
        audio_path = download_audio(v, audio_dir)
        if audio_path:
            v['audio_path'] = audio_path
            results.append(v)
            logger.info(f"  ✓ 已下载: {Path(audio_path).name}")
        else:
            v['audio_path'] = None
            results.append(v)
            logger.info(f"  ✗ 下载失败")

    # 保存含音频路径的元信息
    meta_path = DATA_DIR / "videos" / today / "all_videos_with_audio.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success = sum(1 for r in results if r['audio_path'])
    logger.info(f"\n下载完成: {success}/{len(results)} 成功")
    return results


if __name__ == '__main__':
    main()

