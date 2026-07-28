# -*- coding: utf-8 -*-
"""
主调度脚本：串行执行全部 5 个阶段
每日 18:00 由 Marvis 定时触发
"""

import os
import sys
import subprocess
import logging
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "pipeline.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

STEPS = [
    ("step1_fetch_videos.py", "拉取 UP 主视频"),
    ("step2_download_audio.py", "下载视频音频"),
    ("step3_transcribe.py", "音频转文字"),
    ("step4_extract_stocks.py", "股票实体提取"),
    ("step5_analyze.py", "AI 交叉验证分析"),
]


def run_step(script_name, step_desc):
    """运行单个步骤"""
    logger.info(f"=" * 50)
    logger.info(f"执行: {step_desc}")
    logger.info(f"=" * 50)

    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        logger.error(f"脚本不存在: {script_path}")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 分钟超时（Whisper 转写可能较慢）
            cwd=str(PROJECT_ROOT),
        )

        if result.stdout:
            # 打印最后 500 字符作为摘要
            logger.info(result.stdout[-500:])

        if result.returncode != 0:
            logger.error(f"步骤失败 (返回码 {result.returncode}):")
            logger.error(result.stderr[-500:])
            return False

        logger.info(f"✓ {step_desc} 完成")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"步骤超时: {step_desc}")
        return False
    except Exception as e:
        logger.error(f"步骤异常: {step_desc}: {e}")
        return False


def main():
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(f"股票博主观点采集工作流启动 - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    failed_steps = []

    for script, desc in STEPS:
        success = run_step(script, desc)
        if not success:
            failed_steps.append(desc)
            logger.warning(f"步骤 [{desc}] 失败，继续执行后续步骤")

    elapsed = datetime.now() - start_time
    logger.info("=" * 60)
    logger.info(f"工作流完成，耗时: {elapsed}")

    if failed_steps:
        logger.warning(f"失败步骤: {', '.join(failed_steps)}")
    else:
        logger.info("全部步骤执行成功！")

    # 输出报告路径
    today = datetime.now().strftime('%Y%m%d')
    report_path = PROJECT_ROOT / "data" / "reports" / f"每日个股分析报告_{today}.md"
    if report_path.exists():
        logger.info(f"最终报告: {report_path}")

    logger.info("=" * 60)


if __name__ == '__main__':
    main()

