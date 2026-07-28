"""
量化因子引擎：均线 / BOLL / MACD / RSI / 支撑压力位
所有计算为本地纯规则，无随机性，无 LLM 依赖
"""
import pandas as pd
import numpy as np
from typing import Optional


def calc_ma(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    """计算多个周期的简单均线，追加 MA{N} 列"""
    df = df.copy()
    for p in periods:
        df[f"MA{p}"] = df["close"].rolling(window=p).mean()
    return df


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """计算 MACD，追加 DIF / DEA / MACD 列"""
    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["DIF"] = ema_fast - ema_slow
    df["DEA"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD"] = 2 * (df["DIF"] - df["DEA"])
    return df


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算 RSI，追加 RSI 列"""
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def calc_boll(df: pd.DataFrame, period: int = 20, std: int = 2) -> pd.DataFrame:
    """计算 BOLL 带，追加 BOLL_MID / BOLL_UP / BOLL_DN 列"""
    df = df.copy()
    df["BOLL_MID"] = df["close"].rolling(window=period).mean()
    rolling_std = df["close"].rolling(window=period).std()
    df["BOLL_UP"] = df["BOLL_MID"] + std * rolling_std
    df["BOLL_DN"] = df["BOLL_MID"] - std * rolling_std
    return df


def calc_support_resistance(df: pd.DataFrame, lookback: int = 60) -> dict:
    """
    基于近期高低点和均线，输出关键支撑/压力位。
    返回: {"supports": [...], "resistances": [...]}
    """
    recent = df.tail(lookback)
    high = recent["high"].max()
    low = recent["low"].min()
    close = recent["close"].iloc[-1]

    supports = [round(low, 3)]
    resistances = [round(high, 3)]

    # 加入 MA 作为辅助参考
    for ma_col in ["MA5", "MA10", "MA20", "MA60"]:
        if ma_col in recent.columns:
            val = recent[ma_col].iloc[-1]
            if pd.notna(val):
                val = round(val, 3)
                if val < close and val not in supports:
                    supports.append(val)
                elif val > close and val not in resistances:
                    resistances.append(val)

    supports.sort()
    resistances.sort()
    return {"supports": supports, "resistances": resistances}


def run_factor_pipeline(df: pd.DataFrame, risk_params: dict) -> dict:
    """
    运行全量因子计算管线，返回结构化结果。
    """
    ma_short = risk_params.get("ma_short", 10)
    ma_long = risk_params.get("ma_long", 30)

    df = calc_ma(df, [ma_short, ma_long, 5, 20, 60])
    df = calc_macd(df)
    df = calc_rsi(df)
    df = calc_boll(df)

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    sr = calc_support_resistance(df)

    # ── 趋势判定 ──
    ma_short_val = latest.get(f"MA{ma_short}")
    ma_long_val = latest.get(f"MA{ma_long}")
    price = latest["close"]

    if pd.notna(ma_short_val) and pd.notna(ma_long_val):
        if price > ma_short_val > ma_long_val:
            trend = "bullish"
        elif price < ma_short_val < ma_long_val:
            trend = "bearish"
        else:
            trend = "neutral"
    else:
        trend = "neutral"

    # ── 信号生成 ──
    signals = []
    rsi = latest.get("RSI")
    rsi_oversold = risk_params.get("rsi_oversold", 25)
    rsi_overbought = risk_params.get("rsi_overbought", 75)

    if pd.notna(rsi):
        if rsi < rsi_oversold:
            signals.append("RSI_超卖")
        elif rsi > rsi_overbought:
            signals.append("RSI_超买")

    # MACD 金叉/死叉
    dif_cross = latest["DIF"] - latest["DEA"]
    prev_dif_cross = prev["DIF"] - prev["DEA"]
    if prev_dif_cross <= 0 < dif_cross:
        signals.append("MACD_金叉")
    elif prev_dif_cross >= 0 > dif_cross:
        signals.append("MACD_死叉")

    # BOLL 位置
    if price <= latest["BOLL_DN"]:
        signals.append("BOLL_下轨")
    elif price >= latest["BOLL_UP"]:
        signals.append("BOLL_上轨")

    # ── 收盘价相对均线 ──
    if pd.notna(ma_short_val):
        if price > ma_short_val:
            signals.append("价在MA短之上")
        else:
            signals.append("价在MA短之下")

    return {
        "price": round(price, 3),
        "trend": trend,
        "signals": signals,
        "indicators": {
            "MACD_DIF": round(latest["DIF"], 4) if pd.notna(latest.get("DIF")) else None,
            "MACD_DEA": round(latest["DEA"], 4) if pd.notna(latest.get("DEA")) else None,
            "RSI": round(rsi, 2) if pd.notna(rsi) else None,
            "BOLL_UP": round(latest["BOLL_UP"], 3) if pd.notna(latest.get("BOLL_UP")) else None,
            "BOLL_MID": round(latest["BOLL_MID"], 3) if pd.notna(latest.get("BOLL_MID")) else None,
            "BOLL_DN": round(latest["BOLL_DN"], 3) if pd.notna(latest.get("BOLL_DN")) else None,
            f"MA{ma_short}": round(ma_short_val, 3) if pd.notna(ma_short_val) else None,
            f"MA{ma_long}": round(ma_long_val, 3) if pd.notna(ma_long_val) else None,
        },
        "support_resistance": sr,
    }

