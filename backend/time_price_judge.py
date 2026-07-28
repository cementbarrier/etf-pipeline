"""
时段判断工具：判断当前是否处于 DeepSeek 峰谷定价时段（北京时间）
"""
from datetime import datetime, time


# 高峰时段（双倍价）：工作日 09:00-12:00, 14:00-18:00
PEAK_WINDOWS = [
    (time(9, 0),  time(12, 0)),
    (time(14, 0), time(18, 0)),
]


def _now_beijing() -> datetime:
    """获取当前北京时间"""
    return datetime.now()


def is_peak(now: datetime = None) -> bool:
    """判断当前是否高峰时段（双倍价）。周末全天为低谷。"""
    if now is None:
        now = _now_beijing()
    # 周末全天低谷
    if now.weekday() >= 5:  # 5=周六, 6=周日
        return False
    t = now.time()
    for start, end in PEAK_WINDOWS:
        if start <= t < end:
            return True
    return False


def is_valley(now: datetime = None) -> bool:
    """判断当前是否低谷时段（平价）"""
    return not is_peak(now)


def get_price_label(now: datetime = None) -> str:
    """返回当前时段标签"""
    return "高峰（2倍价）" if is_peak(now) else "低谷（平价）"


def get_price_multiplier(now: datetime = None) -> int:
    """返回当前价格倍数"""
    return 2 if is_peak(now) else 1


def get_warning_text(now: datetime = None) -> str:
    """高峰时段的提醒文案"""
    if is_peak(now):
        return "当前为 DeepSeek 高峰时段（09:00-12:00 / 14:00-18:00），Token 价格翻倍。\n建议加入延迟队列，低谷时段自动执行。"
    return ""


def next_valley_time(now: datetime = None) -> datetime:
    """计算下一个低谷时段的起始时间"""
    if now is None:
        now = _now_beijing()
    if now.weekday() >= 5:
        return now  # 已在周末低谷
    t = now.time()
    # 如果当前在午休低谷 (12:00-14:00)，下一个低谷就是现在
    if time(12, 0) <= t < time(14, 0):
        return now
    # 如果在上午高峰 (9:00-12:00)，下一个低谷是 12:00
    if time(9, 0) <= t < time(12, 0):
        return now.replace(hour=12, minute=0, second=0, microsecond=0)
    # 如果在下午高峰 (14:00-18:00)，下一个低谷是 18:00
    if time(14, 0) <= t < time(18, 0):
        return now.replace(hour=18, minute=0, second=0, microsecond=0)
    # 如果在前夜低谷 (18:00-23:59)，下一个低谷就是现在
    if t >= time(18, 0):
        return now
    # 如果在深夜/凌晨低谷 (00:00-09:00)，下一个低谷就是现在
    return now

