"""
行情数据获取：支持多数据源切换（baostock / akshare），可选 token 认证
"""
import os
import sys
os.environ.setdefault("TQDM_DISABLE", "1")

# 强制禁用代理（akshare 内部新建 session 可能绕开全局 patch）
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['NO_PROXY'] = '*'
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['no_proxy'] = '*'

# Frozen 环境下指向打包的 SSL 证书
if getattr(sys, 'frozen', False):
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

from typing import Optional
from datetime import datetime, timedelta
import threading
import time
import pandas as pd

# ── 请求级代理 / UA 绕过（东方财富 WAF 检测） ──

def _patch_requests_for_em():
    """monkey-patch requests.Session.request 以绕过东方财富 WAF"""
    try:
        import requests
        _orig_request = requests.Session.request

        def _patched_request(self, method, url, *args, **kwargs):
            self.trust_env = False
            kwargs.setdefault('proxies', None)
            kwargs.setdefault('timeout', 30)
            if 'headers' not in kwargs:
                kwargs['headers'] = {}
            kwargs['headers'].setdefault(
                'User-Agent',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
            kwargs['headers'].setdefault('Referer', 'https://quote.eastmoney.com/')
            return _orig_request(self, method, url, *args, **kwargs)

        requests.Session.request = _patched_request
    except ImportError:
        pass

_patch_requests_for_em()

# akshare 调用超时（秒）
_AKSHARE_TIMEOUT = 30


def _call_with_timeout(func, timeout: float = _AKSHARE_TIMEOUT):
    """在独立线程中执行 func()，超时抛 TimeoutError（防止 akshare 无超时卡死）"""
    result = {}

    def _worker():
        try:
            result["value"] = func()
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"调用超时（>{timeout}s）")
    if "error" in result:
        raise result["error"]
    return result.get("value")


# ── 数据源配置 ──

DATA_SOURCES = {
    "baostock": {
        "label": "baostock (免费，偶有网络波动)",
        "needs_token": False,
    },
    "akshare": {
        "label": "akshare (免费，东方财富数据)",
        "needs_token": False,
    },
}

_DEFAULT_SOURCE = "baostock"


def get_data_source():
    """从配置文件读取当前数据源"""
    from backend.config_manager import get_setting
    src = get_setting("data_source", _DEFAULT_SOURCE)
    if src not in DATA_SOURCES:
        src = _DEFAULT_SOURCE
    return src


def get_data_source_token():
    """读取数据源 token（仅付费源需要）"""
    from backend.config_manager import get_setting
    return get_setting("data_source_token", "")


# ── baostock 实现 ──

def _ensure_baostock_login():
    import baostock as bs
    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")


def _symbol_to_code(symbol: str) -> str:
    s = symbol.strip()
    if s.startswith("5") or s.startswith("6"):
        return f"sh.{s}"
    else:
        return f"sz.{s}"


def _fetch_baostock_daily(symbol: str, count: int = 200) -> Optional[pd.DataFrame]:
    """baostock 日 K 线"""
    import baostock as bs
    _ensure_baostock_login()
    code = _symbol_to_code(symbol)
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=count * 2)).strftime("%Y-%m-%d")

    rs = bs.query_history_k_data_plus(
        code, "date,open,high,low,close,volume",
        start_date=start, end_date=today,
        frequency="d", adjustflag="2"
    )
    if rs.error_code != '0':
        raise RuntimeError(f"baostock 查询失败: {rs.error_msg}")

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce")
    return df.sort_values("date").tail(count).reset_index(drop=True).dropna(subset=["close"])


def _fetch_baostock_minute(symbol: str, period: str = "60", count: int = 200) -> Optional[pd.DataFrame]:
    """baostock 分钟 K 线"""
    import baostock as bs
    _ensure_baostock_login()
    code = _symbol_to_code(symbol)
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=count)).strftime("%Y-%m-%d")

    rs = bs.query_history_k_data_plus(
        code, "date,time,open,high,low,close,volume",
        start_date=start, end_date=end,
        frequency=period, adjustflag="2"
    )
    if rs.error_code != '0':
        raise RuntimeError(f"baostock 分钟查询失败: {rs.error_msg}")

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["date", "time", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["time"], format="%Y%m%d%H%M%S%f", errors="coerce")
    df = df.drop(columns=["time"]).sort_values("date").tail(count).reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce")
    return df.dropna(subset=["close"])


# ── akshare 实现 ──

def _fetch_akshare_daily(symbol: str, count: int = 200) -> Optional[pd.DataFrame]:
    """akshare ETF 日 K 线"""
    import akshare as ak
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=count * 3)).strftime("%Y%m%d")

    df = ak.fund_etf_hist_em(symbol=symbol.strip(), period="daily",
                             start_date=start_date, end_date=end_date,
                             adjust="qfq")
    if df is None or df.empty:
        return None

    df = df.rename(columns={
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    })
    df = df[["date", "open", "high", "low", "close", "volume"]]
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce")
    return df.sort_values("date").tail(count).reset_index(drop=True).dropna(subset=["close"])


def _fetch_akshare_minute(symbol: str, period: str = "60", count: int = 200) -> Optional[pd.DataFrame]:
    """akshare ETF 分钟 K 线"""
    import akshare as ak
    freq = {"5": "5", "15": "15", "30": "30", "60": "60"}
    period_key = freq.get(period, "60")

    df = ak.fund_etf_hist_min_em(symbol=symbol.strip(), period=period_key)
    if df is None or df.empty:
        return None

    df = df.rename(columns={
        "时间": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    })
    df = df[["date", "open", "high", "low", "close", "volume"]]
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce")
    return df.sort_values("date").tail(count).reset_index(drop=True).dropna(subset=["close"])


# ── 统一入口 ──

_last_fetch_error: Optional[str] = None


def get_last_fetch_error() -> Optional[str]:
    """返回最近一次 fetch_etf_daily 的失败原因，诊断用"""
    return _last_fetch_error


def fetch_etf_daily(symbol: str, count: int = 200) -> Optional[pd.DataFrame]:
    """获取 ETF 日 K 线（含今日实时行情），根据配置数据源路由。

    akshare 失败自动降级到 baostock，baostock 失败自动降级到 akshare。
    """
    global _last_fetch_error
    _last_fetch_error = None
    source = get_data_source()
    fallback = "baostock" if source == "akshare" else "akshare"

    def _try_baostock():
        df = _fetch_baostock_daily(symbol, count)
        if df is not None:
            last_date = df["date"].max()
            today_str = datetime.now().strftime("%Y-%m-%d")
            if last_date.strftime("%Y-%m-%d") != today_str:
                spot = _fetch_realtime_spot(symbol)
                if spot and spot['close'] > 0:
                    new_row = pd.DataFrame([spot])
                    new_row["date"] = pd.to_datetime(new_row["date"])
                    df = pd.concat([df, new_row], ignore_index=True)
                    df = df.sort_values("date").tail(count).reset_index(drop=True)
        return df

    def _try_akshare():
        return _call_with_timeout(lambda: _fetch_akshare_daily(symbol, count))

    primary_fn = _try_baostock if source == "baostock" else _try_akshare
    fallback_fn = _try_akshare if source == "baostock" else _try_baostock

    primary_error = None
    fallback_error = None

    try:
        df = primary_fn()
        if df is not None and not df.empty:
            return df
    except Exception as e:
        primary_error = str(e)

    try:
        df = fallback_fn()
        if df is not None and not df.empty:
            return df
    except Exception as e:
        fallback_error = str(e)

    parts = []
    if primary_error:
        parts.append(f"[{source}] {primary_error}")
    if fallback_error:
        parts.append(f"[{fallback}] {fallback_error}")
    if not parts:
        parts.append(f"{source} 和 {fallback} 均返回空数据")
    _last_fetch_error = "\n".join(parts)
    return None


def fetch_etf_minute(symbol: str, period: str = "60", count: int = 200) -> Optional[pd.DataFrame]:
    """获取 ETF 分钟 K 线，根据配置数据源路由。失败自动降级到另一数据源"""
    source = get_data_source()

    def _try_baostock():
        return _fetch_baostock_minute(symbol, period, count)

    def _try_akshare():
        return _call_with_timeout(lambda: _fetch_akshare_minute(symbol, period, count))

    primary_fn = _try_baostock if source == "baostock" else _try_akshare
    fallback_fn = _try_akshare if source == "baostock" else _try_baostock

    try:
        df = primary_fn()
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    try:
        return fallback_fn()
    except Exception:
        pass

    return None


def _fetch_realtime_spot(symbol: str) -> Optional[dict]:
    """akshare 实时行情（仅 baostock 模式兜底用），带 30s 超时保护"""
    try:
        import akshare as ak

        def _call():
            df = ak.fund_etf_spot_em()
            row = df[df['代码'] == symbol.strip()]
            if row.empty:
                return None
            r = row.iloc[0]
            today = datetime.now().strftime('%Y-%m-%d')
            return {
                'date': today,
                'open': float(r['开盘价']),
                'high': float(r['最高价']),
                'low': float(r['最低价']),
                'close': float(r['最新价']),
                'volume': int(r['成交量']),
            }

        return _call_with_timeout(_call)

    except Exception:
        return None

