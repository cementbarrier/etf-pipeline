# -*- coding: utf-8 -*-
"""
阶段4：股票实体提取 & 自动个股分类
词库匹配 + 模糊推理，按股票归档存储
"""

import os
import sys
import json
import re
import logging
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
LOG_DIR = PROJECT_ROOT / "logs"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "extract.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_stock_dict():
    """
    构建股票代码-简称映射表
    优先从 akshare 实时获取，失败则用内置精简版
    """
    stock_dict = {}
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        for _, row in df.iterrows():
            code = str(row['code'])
            name = str(row['name'])
            stock_dict[code] = name
        logger.info(f"从 akshare 加载 {len(stock_dict)} 只股票")
    except Exception as e:
        logger.warning(f"akshare 加载失败: {e}，使用内置词库")
        # 精简内置词库（热门股票）
        fallback = {
            '600519': '贵州茅台', '300750': '宁德时代', '000858': '五粮液',
            '002594': '比亚迪', '601318': '中国平安', '000333': '美的集团',
            '600036': '招商银行', '601166': '兴业银行', '002415': '海康威视',
            '000651': '格力电器', '600030': '中信证券', '601398': '工商银行',
            '600276': '恒瑞医药', '002475': '立讯精密', '300059': '东方财富',
            '601888': '中国中免', '000725': '京东方A', '002352': '顺丰控股',
            '688981': '中芯国际', '601899': '紫金矿业', '600809': '山西汾酒',
            '600900': '长江电力', '601012': '隆基绿能', '002714': '牧原股份',
            '603259': '药明康德',
        }
        stock_dict = fallback

    # 加载黑名单
    black_codes = load_blacklist()
    for code in black_codes:
        stock_dict.pop(code, None)

    return stock_dict


def load_blacklist():
    """加载股票黑名单（Excel）"""
    import pandas as pd
    black = set()
    path = CONFIG_DIR / "black_stock.xlsx"
    if path.exists():
        df = pd.read_excel(path)
        for _, row in df.iterrows():
            code = str(row.iloc[0]).strip().zfill(6)
            if code and code != 'nan':
                black.add(code)
    return black


def load_watchlist():
    """加载自选跟踪个股（Excel）"""
    import pandas as pd
    watch = set()
    path = CONFIG_DIR / "watch_stock.xlsx"
    if path.exists():
        df = pd.read_excel(path)
        for _, row in df.iterrows():
            code = str(row.iloc[0]).strip().zfill(6)
            if code and code != 'nan':
                watch.add(code)
    return watch


def extract_stocks_from_text(text, stock_dict):
    """从文本中提取涉及的股票"""
    found = {}

    # 构建反向映射：简称 -> 代码
    name_to_code = {v: k for k, v in stock_dict.items()}

    # 1. 精确匹配股票代码（6位数字）
    code_pattern = re.compile(r'\b(\d{6})\b')
    for match in code_pattern.finditer(text):
        code = match.group(1)
        if code in stock_dict:
            found[code] = stock_dict[code]

    # 2. 精确匹配股票简称
    for name, code in name_to_code.items():
        if name in text:
            found[code] = name

    # 3. 模糊匹配（含"股份""科技""集团"等后缀时也会匹配到核心名称）
    for name, code in name_to_code.items():
        core = re.sub(r'(股份|科技|集团|控股|实业|能源|药业|电子|银行|证券|保险)$', '', name)
        if len(core) >= 2 and core in text and core not in ['行业', '市场', '板块']:
            found[code] = name

    return found


def save_to_stock_folder(video, stocks_found):
    """将文稿按个股分类存储"""
    today = datetime.now().strftime('%Y%m%d')
    transcript_path = video.get('transcript_path')

    if not transcript_path or not os.path.exists(transcript_path):
        return []

    saved = []
    for code, name in stocks_found.items():
        stock_dir = DATA_DIR / "stocks" / f"{code}_{name}" / today
        stock_dir.mkdir(parents=True, exist_ok=True)

        bvid = video.get('bvid')
        dest = stock_dir / f"{bvid}_{video.get('up_name', '')}.txt"

        # 复制或硬链接文稿
        import shutil
        shutil.copy2(transcript_path, dest)
        saved.append({'code': code, 'name': name, 'path': str(dest)})

    return saved


def generate_summary_csv(all_results):
    """生成个股观点汇总 CSV"""
    today = datetime.now().strftime('%Y%m%d')
    csv_path = DATA_DIR / f"个股观点汇总_{today}.csv"

    import csv
    rows = []
    for item in all_results:
        for stock in item.get('stocks', []):
            video = item['video']
            rows.append({
                '股票代码': stock['code'],
                '股票名称': stock['name'],
                'UP主': video.get('up_name', ''),
                'UP权重': video.get('up_weight', 0),
                '发布日期': today,
                '视频标题': video.get('title', ''),
                '视频链接': f"https://www.bilibili.com/video/{video.get('bvid')}",
                '文稿路径': stock.get('path', ''),
            })

    if rows:
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"个股汇总 CSV 已保存: {csv_path}")
        return str(csv_path)
    return None


def main():
    logger.info("=" * 50)
    logger.info("开始股票实体提取与分类")
    logger.info("=" * 50)

    # 加载转写结果
    today = datetime.now().strftime('%Y%m%d')
    meta_path = DATA_DIR / "videos" / today / "all_videos_with_transcript.json"
    if not meta_path.exists():
        logger.error(f"无转写结果: {meta_path}")
        return []

    with open(meta_path, 'r', encoding='utf-8') as f:
        videos = json.load(f)

    # 过滤有转写结果的视频
    videos_with_text = [v for v in videos if v.get('transcript_path')]
    logger.info(f"{len(videos_with_text)} 个视频有转写文稿")

    stock_dict = load_stock_dict()
    watchlist = load_watchlist()

    all_results = []
    for v in videos_with_text:
        transcript_path = v.get('transcript_path')
        if not transcript_path:
            continue

        with open(transcript_path, 'r', encoding='utf-8') as f:
            text = f.read()

        stocks = extract_stocks_from_text(text, stock_dict)

        # 标记自选股
        for code in stocks:
            if code in watchlist:
                stocks[code] = stocks[code] + " ★"

        if stocks:
            saved = save_to_stock_folder(v, stocks)
            logger.info(f"  {v['up_name']}: {v['title'][:30]} → {len(stocks)} 只个股")
            all_results.append({'video': v, 'stocks': saved})
        else:
            logger.info(f"  {v['up_name']}: {v['title'][:30]} → 未发现个股")

    # 生成汇总 CSV
    csv_path = generate_summary_csv(all_results)

    # 保存结果
    result_path = DATA_DIR / f"extract_results_{today}.json"
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    total_stocks = sum(len(r['stocks']) for r in all_results)
    logger.info(f"\n提取完成: {total_stocks} 条个股关联")
    return all_results


if __name__ == '__main__':
    main()

