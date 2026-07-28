# -*- coding: utf-8 -*-
"""
阶段5：AI交叉验证分析
观点聚合 + 技术面数据 + AI 综合判断 → 每日选股报告
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

# 增量解析：导入时段标题
import sys as _sys
_sys.path.insert(0, str(PROJECT_ROOT))
from backend.parsed_records import get_period_title

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "analyze.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_extract_results():
    """加载上一步的股票提取结果"""
    today = datetime.now().strftime('%Y%m%d')
    path = DATA_DIR / f"extract_results_{today}.json"
    if not path.exists():
        logger.error(f"提取结果不存在: {path}")
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def aggregate_opinions(results):
    """聚合多博主观点：按个股统计 UP 主态度和权重"""
    stocks_opinions = {}

    for item in results:
        video = item['video']
        up_name = video.get('up_name', '')
        up_weight = video.get('up_weight', 1)
        title = video.get('title', '')
        transcript_path = video.get('transcript_path', '')

        # 读取文稿前 3000 字符用于快速判断态度
        text_preview = ''
        if transcript_path and os.path.exists(transcript_path):
            with open(transcript_path, 'r', encoding='utf-8') as f:
                text_preview = f.read(3000)

        # 简单态度判断：基于关键词
        sentiment = judge_sentiment(title + text_preview)

        for stock in item.get('stocks', []):
            code = stock['code']
            name = stock['name']

            if code not in stocks_opinions:
                stocks_opinions[code] = {
                    'name': name,
                    'ups': [],
                    'bullish': 0,
                    'bearish': 0,
                    'neutral': 0,
                    'weighted_score': 0,
                }

            entry = {
                'up_name': up_name,
                'up_weight': up_weight,
                'sentiment': sentiment,
                'title': title,
                'transcript_path': transcript_path,
            }
            stocks_opinions[code]['ups'].append(entry)

            if sentiment == '看多':
                stocks_opinions[code]['bullish'] += 1
                stocks_opinions[code]['weighted_score'] += up_weight
            elif sentiment == '看空':
                stocks_opinions[code]['bearish'] += 1
                stocks_opinions[code]['weighted_score'] -= up_weight
            else:
                stocks_opinions[code]['neutral'] += 1

    logger.info(f"聚合完成: {len(stocks_opinions)} 只个股")
    return stocks_opinions


def judge_sentiment(text):
    """快速判断文本态度"""
    text_lower = text.lower()

    bullish_keywords = [
        '看多', '看涨', '买入', '加仓', '建仓', '抄底', '看好', '利好',
        '突破', '反弹', '上涨', '牛市', '底部', '低估', '机会',
    ]
    bearish_keywords = [
        '看空', '看跌', '卖出', '减仓', '清仓', '不看好', '利空',
        '破位', '下跌', '熊市', '顶部', '高估', '风险', '回避',
    ]

    bull_count = sum(1 for kw in bullish_keywords if kw in text_lower)
    bear_count = sum(1 for kw in bearish_keywords if kw in text_lower)

    if bull_count > bear_count + 1:
        return '看多'
    elif bear_count > bull_count + 1:
        return '看空'
    else:
        return '中性'


def fetch_technical_data(stock_code):
    """获取个股技术面数据（新浪接口，比东方财富兼容性更好）"""
    try:
        import requests

        # 新浪行情接口
        if stock_code.startswith('6'):
            symbol = f"sh{stock_code}"
        else:
            symbol = f"sz{stock_code}"

        # 获取日K线（新浪接口）
        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": 60}
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200 or not resp.text.strip():
            return None

        data = resp.json()
        if not data:
            return None

        closes = [float(d['close']) for d in data if d.get('close')]
        volumes = [float(d['volume']) for d in data if d.get('volume')]

        if len(closes) < 5:
            return None

        current = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else current
        change_pct = round((current - prev) / prev * 100, 2)

        ma5 = round(sum(closes[-5:]) / 5, 2)
        ma20 = round(sum(closes[-20:]) / 20, 2) if len(closes) >= 20 else None
        ma60 = round(sum(closes[-60:]) / 60, 2) if len(closes) >= 60 else None

        vol_5 = sum(volumes[-5:]) / 5
        vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else vol_5
        vol_ratio = round(vol_5 / vol_20, 2) if vol_20 > 0 else 1.0

        rsi = calc_rsi(closes, 14)
        macd_data = calc_macd(closes)

        return {
            'current_price': round(current, 2),
            'change_pct': change_pct,
            'ma5': ma5,
            'ma20': ma20,
            'ma60': ma60,
            'rsi_14': round(rsi, 2) if rsi else None,
            'macd': macd_data,
            'vol_ratio': vol_ratio,
        }

    except Exception as e:
        logger.warning(f"  获取 {stock_code} 行情数据失败: {e}")
        return None


def calc_rsi(close, period=14):
    """计算 RSI"""
    if len(close) < period + 1:
        return None
    deltas = [close[i] - close[i-1] for i in range(1, len(close))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [max(-d, 0) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(close):
    """计算 MACD"""
    if len(close) < 26:
        return None

    def ema(data, period):
        alpha = 2 / (period + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(alpha * data[i] + (1 - alpha) * result[-1])
        return result

    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(ema12))]
    dea = ema(dif, 9)
    macd_hist = [2 * (dif[i] - dea[i]) for i in range(len(dif))]

    return {
        'dif': round(dif[-1], 4),
        'dea': round(dea[-1], 4),
        'macd': round(macd_hist[-1], 4),
    }


def cross_validate(stocks_opinions):
    """AI 交叉验证：舆情 vs 技术面"""
    validations = []

    for code, opinion in stocks_opinions.items():
        total_ups = opinion['bullish'] + opinion['bearish'] + opinion['neutral']
        if total_ups == 0:
            continue

        # 获取技术面
        tech = fetch_technical_data(code)

        # 舆情判断
        bullish_ratio = opinion['bullish'] / total_ups
        bearish_ratio = opinion['bearish'] / total_ups

        if bullish_ratio >= 0.6:
            sentiment_label = '集体看多'
        elif bearish_ratio >= 0.6:
            sentiment_label = '集体看空'
        elif bullish_ratio < 0.4 and bearish_ratio < 0.4:
            sentiment_label = '观点分歧'
        else:
            sentiment_label = '中性偏多' if bullish_ratio > bearish_ratio else '中性偏空'

        # 技术面判断
        tech_label = '数据缺失'
        tech_detail = ''
        if tech:
            price = tech['current_price']
            ma20 = tech.get('ma20')
            rsi = tech.get('rsi_14')
            macd_data = tech.get('macd')

            signals = []
            if ma20 and price > ma20:
                signals.append('站上MA20')
            elif ma20:
                signals.append('跌破MA20')

            if rsi:
                if rsi > 70:
                    signals.append('超买(RSI>70)')
                elif rsi < 30:
                    signals.append('超卖(RSI<30)')

            if macd_data:
                if macd_data['macd'] > 0:
                    signals.append('MACD红柱')
                else:
                    signals.append('MACD绿柱')

            tech_detail = ', '.join(signals)

            # 判断：技术面偏多/偏空
            bullish_signals = sum(1 for s in signals if s in ['站上MA20', '超卖(RSI<30)', 'MACD红柱'])
            bearish_signals = sum(1 for s in signals if s in ['跌破MA20', '超买(RSI>70)', 'MACD绿柱'])
            if bullish_signals > bearish_signals:
                tech_label = '技术面偏多'
            elif bearish_signals > bullish_signals:
                tech_label = '技术面偏空'
            else:
                tech_label = '技术面中性'

        # 交叉验证结论
        if sentiment_label in ['集体看多', '中性偏多'] and tech_label == '技术面偏多':
            conclusion = '入场参考'
        elif sentiment_label in ['集体看多', '中性偏多'] and tech_label == '技术面偏空':
            conclusion = '风险，观点与走势背离'
        elif sentiment_label in ['集体看空', '中性偏空'] and tech_label == '技术面偏空':
            conclusion = '规避'
        elif sentiment_label == '观点分歧' and tech_label in ['技术面中性', '数据缺失']:
            conclusion = '观望，无明确信号'
        else:
            conclusion = '观望'

        validations.append({
            'code': code,
            'name': opinion['name'],
            'ups_count': total_ups,
            'bullish': opinion['bullish'],
            'bearish': opinion['bearish'],
            'neutral': opinion['neutral'],
            'weighted_score': opinion['weighted_score'],
            'sentiment': sentiment_label,
            'tech_label': tech_label,
            'tech_detail': tech_detail,
            'current_price': tech['current_price'] if tech else None,
            'change_pct': tech['change_pct'] if tech else None,
            'conclusion': conclusion,
            'up_list': [u['up_name'] for u in opinion['ups']],
        })

        time.sleep(0.3)  # 控制 API 频率

    return validations


def generate_report(validations):
    """生成 Markdown 格式的每日分析报告"""
    today = datetime.now().strftime('%Y-%m-%d')
    period = get_period_title()
    report_lines = []

    report_lines.append(f"# {period} - 每日个股分析报告")
    report_lines.append(f"**日期**: {today}")
    report_lines.append(f"**时段**: {period}")
    report_lines.append(f"**生成时间**: {datetime.now().strftime('%H:%M:%S')}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # 按结论分组
    entry_list = [v for v in validations if v['conclusion'] == '入场参考']
    risk_list = [v for v in validations if v['conclusion'] == '风险，观点与走势背离']
    avoid_list = [v for v in validations if v['conclusion'] == '规避']
    watch_list = [v for v in validations if v['conclusion'] == '观望' or v['conclusion'] == '观望，无明确信号']

    # 入场参考
    if entry_list:
        report_lines.append("## 入场参考")
        report_lines.append("")
        report_lines.append("| 股票 | 价格 | 涨跌 | UP数 | 看多 | 看空 | 舆情 | 技术面 |")
        report_lines.append("|------|------|------|------|------|------|------|--------|")
        for v in sorted(entry_list, key=lambda x: x['weighted_score'], reverse=True):
            report_lines.append(
                f"| {v['name']}({v['code']}) | {v['current_price'] or '-'} | {v['change_pct'] or '-'}% | "
                f"{v['ups_count']} | {v['bullish']} | {v['bearish']} | {v['sentiment']} | {v['tech_detail']} |"
            )
        report_lines.append("")

    # 风险提示
    if risk_list:
        report_lines.append("## 风险提示（观点与走势背离）")
        report_lines.append("")
        report_lines.append("| 股票 | 价格 | 涨跌 | UP数 | 看多 | 看空 | 舆情 | 技术面 |")
        report_lines.append("|------|------|------|------|------|------|------|--------|")
        for v in risk_list:
            report_lines.append(
                f"| {v['name']}({v['code']}) | {v['current_price'] or '-'} | {v['change_pct'] or '-'}% | "
                f"{v['ups_count']} | {v['bullish']} | {v['bearish']} | {v['sentiment']} | {v['tech_detail']} |"
            )
        report_lines.append("")

    # 规避
    if avoid_list:
        report_lines.append("## 规避")
        report_lines.append("")
        report_lines.append("| 股票 | 价格 | UP数 | 看空 | 技术面 |")
        report_lines.append("|------|------|------|------|--------|")
        for v in avoid_list:
            report_lines.append(
                f"| {v['name']}({v['code']}) | {v['current_price'] or '-'} | "
                f"{v['ups_count']} | {v['bearish']} | {v['tech_detail']} |"
            )
        report_lines.append("")

    # 观望
    if watch_list:
        report_lines.append("## 观望")
        report_lines.append("")
        report_lines.append("| 股票 | 价格 | UP数 | 舆情 | 技术面 |")
        report_lines.append("|------|------|------|------|--------|")
        for v in watch_list:
            report_lines.append(
                f"| {v['name']}({v['code']}) | {v['current_price'] or '-'} | "
                f"{v['ups_count']} | {v['sentiment']} | {v['tech_detail']} |"
            )
        report_lines.append("")

    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 免责声明")
    report_lines.append("本报告由 AI 自动生成，基于 UP 主视频观点和技术面数据交叉验证，仅供参考，不构成投资建议。投资有风险，入市需谨慎。")

    # 保存
    today_str = datetime.now().strftime('%Y%m%d')
    report_path = DATA_DIR / "reports" / f"每日个股分析报告_{today_str}.md"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "reports").mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    logger.info(f"报告已生成: {report_path}")
    return str(report_path)


def main():
    logger.info("=" * 50)
    logger.info("开始 AI 交叉验证分析")
    logger.info("=" * 50)

    results = load_extract_results()
    if not results:
        logger.error("无提取结果")
        return

    # 1. 观点聚合
    opinions = aggregate_opinions(results)
    opinion_count = len(opinions)
    logger.info(f"聚合 {opinion_count} 只个股观点")

    # 2. 交叉验证
    validations = cross_validate(opinions)

    # 3. 生成报告
    report_path = generate_report(validations)

    # 统计
    entry = sum(1 for v in validations if v['conclusion'] == '入场参考')
    risk = sum(1 for v in validations if '风险' in v['conclusion'])
    avoid = sum(1 for v in validations if v['conclusion'] == '规避')

    logger.info(f"\n分析完成:")
    logger.info(f"  入场参考: {entry} 只")
    logger.info(f"  风险提示: {risk} 只")
    logger.info(f"  规避: {avoid} 只")
    logger.info(f"  报告: {report_path}")

    # 输出报告内容预览
    if report_path:
        with open(report_path, 'r', encoding='utf-8') as f:
            print(f.read())

    return validations


if __name__ == '__main__':
    main()

