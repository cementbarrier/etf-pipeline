# -*- coding: utf-8 -*-
"""
阶段3：三层视频转文字分流策略
优先级：本地字幕提取 > SenseVoice(中文优化) > 云端兜底
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

import zhconv

# SenseVoice 模型路径
SENSEVOICE_MODEL_DIR = r"E:\SenseVoice\tool models\models\iic--SenseVoiceSmall\snapshots\master"

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

# 增量解析：导入解析记录管理
import sys as _sys
_sys.path.insert(0, str(PROJECT_ROOT))
from backend.parsed_records import mark_parsed

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "transcribe.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def to_simplified(text: str) -> str:
    """将文本中的繁体中文统一转为简体"""
    if not text:
        return text
    return zhconv.convert(text, "zh-cn")


def load_videos_with_audio():
    """加载含音频路径的视频元信息"""
    today = datetime.now().strftime('%Y%m%d')
    meta_path = DATA_DIR / "videos" / today / "all_videos_with_audio.json"
    if not meta_path.exists():
        logger.error(f"元信息文件不存在: {meta_path}，请先执行 step2")
        return []

    with open(meta_path, 'r', encoding='utf-8') as f:
        videos = json.load(f)
    return videos


_sensevoice_model = None


def transcribe_sensevoice(audio_path):
    """使用 SenseVoice Small 本地转写，中文识别专用优化（走 FunASR 内置实现）
    设备策略：优先 CUDA，资源不足时自动回退 CPU"""
    global _sensevoice_model

    try:
        from funasr import AutoModel

        if _sensevoice_model is None:
            logger.info("  加载 SenseVoice Small 模型（首次）...")
            try:
                _sensevoice_model = AutoModel(
                    model=SENSEVOICE_MODEL_DIR,
                    device="cuda:0",
                    trust_remote_code=False,
                )
                logger.info("  SenseVoice 使用 CUDA:0")
            except Exception as cuda_err:
                logger.warning(f"  SenseVoice CUDA 加载失败 ({cuda_err})，回退 CPU")
                _sensevoice_model = AutoModel(
                    model=SENSEVOICE_MODEL_DIR,
                    device="cpu",
                    trust_remote_code=False,
                )
                logger.info("  SenseVoice 使用 CPU")

        result = _sensevoice_model.generate(
            input=audio_path,
            language="zh",
            use_itn=False,
        )

        if not result or len(result) == 0:
            return None

        raw = result[0]
        # generate 可能返回 str 或 dict
        text = raw.get("text", "") if isinstance(raw, dict) else str(raw)
        text = to_simplified(text.strip())
        logger.info(f"  SenseVoice 转写完成: {len(text)} 字符")
        return text

    except ImportError as e:
        logger.error(f"  SenseVoice 依赖缺失 (funasr): {e}")
        return None
    except Exception as e:
        logger.error(f"  SenseVoice 转写失败: {e}")
        return None


def transcribe_whisper(audio_path, model_size="large-v3"):
    """使用 faster-whisper 本地转写
    设备策略：优先 CUDA (FP16)，资源不足时自动回退 CPU (int8)"""
    try:
        from faster_whisper import WhisperModel

        logger.info(f"  加载 Whisper 模型: {model_size}")

        # 优先 CUDA
        device = "cuda"
        compute_type = "float16"
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info(f"  Whisper 使用 CUDA (float16)")
        except Exception as cuda_err:
            logger.warning(f"  Whisper CUDA 加载失败 ({cuda_err})，回退 CPU (int8)")
            device = "cpu"
            compute_type = "int8"
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info(f"  Whisper 使用 CPU (int8)")

        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            language="zh",
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )

        text_parts = []
        for segment in segments:
            text_parts.append(segment.text)

        full_text = to_simplified("".join(text_parts))
        logger.info(f"  转写完成: {len(full_text)} 字符, 检测语言: {info.language}")
        return full_text.strip()

    except ImportError:
        logger.error("  faster-whisper 未安装，请执行: pip install faster-whisper")
        return None
    except Exception as e:
        logger.error(f"  Whisper 转写失败: {e}")
        return None


def transcribe_ocr_subtitle(video_bvid):
    """
    尝试从 B站获取 CC 字幕
    B站部分视频有官方字幕（JSON格式），可直接下载
    """
    try:
        import requests

        # B站字幕 API (需要先获取 cid)
        cookies_path = PROJECT_ROOT / "config" / "bilibili_cookies.txt"
        cookies = {}
        with open(cookies_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip():
                    continue
                parts = line.strip().split('\t')
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]

        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': cookie_str,
        }

        # 获取视频 cid
        info_url = f"https://api.bilibili.com/x/web-interface/view?bvid={video_bvid}"
        resp = requests.get(info_url, headers=headers, timeout=10)
        data = resp.json()
        if data.get('code') != 0:
            return None

        cid = data['data']['cid']

        # 获取字幕列表
        subtitle_url = f"https://api.bilibili.com/x/player/v2?bvid={video_bvid}&cid={cid}"
        resp2 = requests.get(subtitle_url, headers=headers, timeout=10)
        data2 = resp2.json()
        subtitle_list = data2.get('data', {}).get('subtitle', {}).get('subtitles', [])

        if not subtitle_list:
            return None

        # 优先选中文
        zh_sub = None
        for sub in subtitle_list:
            if 'zh' in sub.get('lan', '').lower():
                zh_sub = sub
                break
        if not zh_sub:
            zh_sub = subtitle_list[0]

        sub_url = zh_sub['subtitle_url']
        if sub_url.startswith('//'):
            sub_url = 'https:' + sub_url

        sub_resp = requests.get(sub_url, headers=headers, timeout=10)
        sub_data = sub_resp.json()
        texts = [item['content'] for item in sub_data.get('body', [])]
        full_text = to_simplified(''.join(texts))
        logger.info(f"  CC字幕提取: {len(full_text)} 字符")
        return full_text.strip()

    except Exception as e:
        logger.debug(f"  CC字幕提取跳过: {e}")
        return None


def save_transcript(video, text):
    """保存转写文稿"""
    today = datetime.now().strftime('%Y%m%d')
    transcript_dir = DATA_DIR / "transcripts" / today
    transcript_dir.mkdir(parents=True, exist_ok=True)

    bvid = video.get('bvid')
    up_name = video.get('up_name', '')
    title = video.get('title', '').replace('/', '_')[:30]
    filename = f"{bvid}_{up_name}_{title}.txt"
    filepath = transcript_dir / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"UP主: {up_name}\n")
        f.write(f"标题: {video.get('title')}\n")
        f.write(f"发布时间: {video.get('pub_time')}\n")
        f.write(f"视频链接: https://www.bilibili.com/video/{bvid}\n")
        f.write(f"UP权重: {video.get('up_weight')}\n")

        # 视频简介
        description = video.get('description', '')
        if description and description.strip():
            f.write("\n【视频简介】\n")
            f.write(f"{description.strip()}\n")

        f.write("\n" + "=" * 50 + "\n\n")
        f.write(text)

    return str(filepath)


def main():
    logger.info("=" * 50)
    logger.info("开始视频转文字")
    logger.info("=" * 50)

    videos = load_videos_with_audio()
    if not videos:
        logger.error("无待处理视频")
        return []

    results = []
    for i, v in enumerate(videos, 1):
        bvid = v.get('bvid')
        audio_path = v.get('audio_path')

        # ── 增量解析：跳过已缓存视频（已有转写文件） ──
        if v.get('_incremental_skip') and v.get('transcript_path'):
            existing_path = v.get('transcript_path', '')
            if os.path.exists(existing_path):
                results.append(v)
                logger.info(f"[{i}/{len(videos)}] ⊘ 跳过(已解析): {v['up_name']}: {v['title'][:40]}")
                continue
            else:
                # 缓存的转写文件不存在，回退为重新解析
                logger.warning(f"[{i}/{len(videos)}] 缓存文件丢失，重新解析: {v['up_name']}: {v['title'][:40]}")
                v['_incremental_skip'] = False

        logger.info(f"[{i}/{len(videos)}] {v['up_name']}: {v['title'][:40]}")

        text = None
        method = "none"

        # 策略1：尝试 B站 CC 字幕
        text = transcribe_ocr_subtitle(bvid)
        if text:
            method = "cc_subtitle"

        # 策略2：本地 SenseVoice 转写（中文优化）
        if not text and audio_path and os.path.exists(audio_path):
            logger.info("  启动 SenseVoice 转写...")
            text = transcribe_sensevoice(audio_path)
            if text:
                method = "sensevoice"

        # 策略3：云端兜底（此处预留接口，后续接入阿里云/百度语音）
        if not text and audio_path:
            logger.warning(f"  本地转写失败，标记为待云端兜底")
            method = "pending_cloud"

        # 保存
        if text:
            transcript_path = save_transcript(v, text)
            v['transcript_path'] = transcript_path
            v['transcript_method'] = method
            v['transcript_length'] = len(text)
            # ── 增量解析：标记为今日已解析 ──
            try:
                mark_parsed(bvid, {
                    'up_name': v.get('up_name', ''),
                    'title': v.get('title', ''),
                    'transcript_path': transcript_path,
                    'transcript_method': method,
                    'transcript_length': len(text),
                    'aid': v.get('aid'),
                    'pub_time': v.get('pub_time'),
                    'up_mid': v.get('up_mid'),
                    'up_weight': v.get('up_weight'),
                    'bvid': bvid,
                })
            except Exception as e:
                logger.warning(f"  标记已解析失败: {e}")
            logger.info(f"  ✓ {method}: {len(text)} 字符")
        else:
            v['transcript_path'] = None
            v['transcript_method'] = method
            v['transcript_length'] = 0
            logger.info(f"  ✗ 转写失败")

        results.append(v)

    # 保存结果
    today = datetime.now().strftime('%Y%m%d')
    result_path = DATA_DIR / "videos" / today / "all_videos_with_transcript.json"
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success = sum(1 for r in results if r['transcript_path'])
    logger.info(f"\n转写完成: {success}/{len(results)} 成功")
    return results


if __name__ == '__main__':
    main()

