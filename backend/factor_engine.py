"""
量化因子引擎：均线 / BOLL / MACD / RSI / KDJ / BIAS / W&R / ASI / VR / CCI / DMI / 支撑压力位
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


# ── KDJ ──
def calc_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """KDJ 随机指标，追加 K/D/J 列"""
    df = df.copy()
    low_n = df["low"].rolling(window=n).min()
    high_n = df["high"].rolling(window=n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100

    k_vals, d_vals = [], []
    k_prev, d_prev = 50.0, 50.0
    for v in rsv:
        if pd.isna(v):
            k_vals.append(np.nan)
            d_vals.append(np.nan)
        else:
            k_prev = 2 / 3 * k_prev + 1 / 3 * v
            d_prev = 2 / 3 * d_prev + 1 / 3 * k_prev
            k_vals.append(k_prev)
            d_vals.append(d_prev)
    df["K"] = k_vals
    df["D"] = d_vals
    df["J"] = 3 * df["K"] - 2 * df["D"]
    return df


# ── BIAS ──
def calc_bias(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
    """乖离率，追加 BIAS{N} 列。默认 [6, 12, 24]"""
    if periods is None:
        periods = [6, 12, 24]
    df = df.copy()
    for p in periods:
        ma = df["close"].rolling(window=p).mean()
        df[f"BIAS{p}"] = (df["close"] - ma) / ma.replace(0, np.nan) * 100
    return df


# ── W&R (Williams %R) ──
def calc_wr(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """威廉指标，追加 WR 列（范围 -100 ~ 0）"""
    df = df.copy()
    high_n = df["high"].rolling(window=n).max()
    low_n = df["low"].rolling(window=n).min()
    df["WR"] = (high_n - df["close"]) / (high_n - low_n).replace(0, np.nan) * -100
    return df


# ── ASI ──
def calc_asi(df: pd.DataFrame, limit_move: float = 1.0) -> pd.DataFrame:
    """
    累计摆动指标，追加 ASI 列。
    limit_move: 涨跌停幅度（ETF 默认 1.0，即无涨跌停限制）
    """
    df = df.copy()
    close, open_, high, low = df["close"], df["open"], df["high"], df["low"]
    prev_close = close.shift(1)
    prev_open = open_.shift(1)

    # SI 的 R 分量
    a = (high - prev_close).abs()
    b = (low - prev_close).abs()
    c = (high - low).abs()
    r_vals = pd.concat([a, b, c], axis=1).max(axis=1)

    si = 50 * ((close - prev_close) + 0.5 * (close - open_) + 0.25 * (prev_close - prev_open))
    si = si / r_vals.replace(0, np.nan) * (c / limit_move)
    df["ASI"] = si.cumsum()
    return df


# ── VR ──
def calc_vr(df: pd.DataFrame, n: int = 26) -> pd.DataFrame:
    """成交量变异率，追加 VR 列"""
    df = df.copy()
    chg = df["close"].diff()
    avs = df["volume"].where(chg > 0, 0).rolling(n).sum()
    bvs = df["volume"].where(chg < 0, 0).rolling(n).sum()
    cvs = df["volume"].where(chg == 0, 0).rolling(n).sum()
    denom = bvs + cvs * 0.5
    df["VR"] = (avs + cvs * 0.5) / denom.replace(0, np.nan) * 100
    return df


# ── CCI ──
def calc_cci(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """商品通道指数，追加 CCI 列"""
    df = df.copy()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma_tp = tp.rolling(window=n).mean()
    md = tp.rolling(window=n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    df["CCI"] = (tp - ma_tp) / (0.015 * md.replace(0, np.nan))
    return df


# ── DMI ──
def calc_dmi(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """趋向指标，追加 ADX / +DI / -DI 列"""
    df = df.copy()
    high, low, close = df["high"], df["low"], df["close"]
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)

    # True Range
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).ewm(alpha=1/n, adjust=False).mean()

    # +DM / -DM
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    plus_dm = pd.Series(plus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean()
    minus_dm = pd.Series(minus_dm, index=df.index).ewm(alpha=1/n, adjust=False).mean()

    df["+DI"] = plus_dm / tr.replace(0, np.nan) * 100
    df["-DI"] = minus_dm / tr.replace(0, np.nan) * 100
    dx = (df["+DI"] - df["-DI"]).abs() / (df["+DI"] + df["-DI"]).replace(0, np.nan) * 100
    df["ADX"] = dx.ewm(alpha=1/n, adjust=False).mean()
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
    df = calc_kdj(df)
    df = calc_bias(df, [6, 12, 24])
    df = calc_wr(df)
    df = calc_asi(df)
    df = calc_vr(df)
    df = calc_cci(df)
    df = calc_dmi(df)

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
            "KDJ_K": round(latest["K"], 2) if pd.notna(latest.get("K")) else None,
            "KDJ_D": round(latest["D"], 2) if pd.notna(latest.get("D")) else None,
            "KDJ_J": round(latest["J"], 2) if pd.notna(latest.get("J")) else None,
            "BIAS6": round(latest.get("BIAS6"), 2) if pd.notna(latest.get("BIAS6")) else None,
            "BIAS12": round(latest.get("BIAS12"), 2) if pd.notna(latest.get("BIAS12")) else None,
            "BIAS24": round(latest.get("BIAS24"), 2) if pd.notna(latest.get("BIAS24")) else None,
            "WR": round(latest["WR"], 2) if pd.notna(latest.get("WR")) else None,
            "ASI": round(latest["ASI"], 2) if pd.notna(latest.get("ASI")) else None,
            "VR": round(latest["VR"], 2) if pd.notna(latest.get("VR")) else None,
            "CCI": round(latest["CCI"], 2) if pd.notna(latest.get("CCI")) else None,
            "ADX": round(latest["ADX"], 2) if pd.notna(latest.get("ADX")) else None,
            "+DI": round(latest["+DI"], 2) if pd.notna(latest.get("+DI")) else None,
            "-DI": round(latest["-DI"], 2) if pd.notna(latest.get("-DI")) else None,
            f"MA{ma_short}": round(ma_short_val, 3) if pd.notna(ma_short_val) else None,
            f"MA{ma_long}": round(ma_long_val, 3) if pd.notna(ma_long_val) else None,
        },
        "support_resistance": sr,
    }

