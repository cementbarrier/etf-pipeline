"""
持仓与资金获取：通过 easytrader 从同花顺客户端读取。
"""
import os
from backend.config_manager import get_setting

# 同花顺 balance 字段 → 内部统一 key
_BALANCE_FIELD_MAP = {
    "可用资金": "available", "可用金额": "available",
    "可取资金": "withdrawable", "可取金额": "withdrawable",
    "资金余额": "balance",
    "总资产": "total_asset",
    "股票市值": "market_value",
    "参考市值": "ref_market_value",
    "浮动盈亏": "float_pnl",
}


def _normalize_balance(raw_bal) -> dict:
    """将 easytrader 返回的余额数据（dict 或 DataFrame）标准化为 {available, total_asset, ...}"""
    if raw_bal is None:
        return {}
    import pandas as pd
    if isinstance(raw_bal, pd.DataFrame):
        if raw_bal.empty:
            return {}
        row = raw_bal.iloc[0]
        result = {}
        for col, key in _BALANCE_FIELD_MAP.items():
            if col in row.index:
                try:
                    result[key] = float(row[col])
                except (ValueError, TypeError):
                    pass
        return result
    if isinstance(raw_bal, dict):
        result = {}
        for col, key in _BALANCE_FIELD_MAP.items():
            if col in raw_bal:
                try:
                    result[key] = float(raw_bal[col])
                except (ValueError, TypeError):
                    pass
        return result
    return {}


def _connect_ths():
    """连接同花顺，返回 (user, error_msg)"""
    try:
        import easytrader
    except ImportError:
        return None, "easytrader 未安装，请执行 pip install easytrader"

    ths_path = get_setting("ths_xiadan_path", r"C:\同花顺软件\xiadan.exe")
    if not os.path.exists(ths_path):
        return None, f"找不到同花顺下单程序: {ths_path}\n可在 config/settings.json 中设置 ths_xiadan_path"

    try:
        user = easytrader.use("ths")
        user.connect(ths_path)
    except Exception as e:
        msg = str(e).split("\n")[0][:120]
        return None, f"连接同花顺失败: {msg}\n请确认: ①同花顺已登录运行 ②窗口未最小化 ③xiadan.exe 已启动"

    return user, ""


def get_positions_from_ths() -> dict:
    """
    通过 easytrader 从同花顺客户端读取持仓。
    返回: {"success": True, "data": [...]} 或 {"success": False, "error": "原因"}
    """
    user, err = _connect_ths()
    if err:
        return {"success": False, "data": [], "error": err}

    try:
        raw = user.position
    except Exception as e:
        msg = str(e).split("\n")[0][:120]
        return {"success": False, "data": [], "error": f"读取持仓失败: {msg}"}

    if raw is None or (hasattr(raw, "empty") and raw.empty):
        return {"success": True, "data": [], "error": ""}

    import logging as _logging
    _log3 = _logging.getLogger("etf_trader")
    _log3.debug(f"[position] type={type(raw).__name__} empty={hasattr(raw, 'empty') and raw.empty if hasattr(raw, 'empty') else 'N/A'}")

    positions = []
    try:
        import pandas as pd
        if isinstance(raw, pd.DataFrame):
            # 调试：输出 DataFrame 列名和行数
            try:
                import logging
                _log = logging.getLogger("etf_trader")
                _log.debug(f"[position] DataFrame columns: {list(raw.columns)} rows={len(raw)}")
            except Exception:
                pass
            for _, row in raw.iterrows():
                code = str(row.get("证券代码", "")).strip()
                if not code:
                    for alt_col in ["代码", "stock_code", "code", "证券代码", "标的代码"]:
                        if alt_col in row.index:
                            code = str(row.get(alt_col, "")).strip()
                            if code:
                                break
                if not code:
                    continue
                positions.append({
                    "code": code,
                    "name": str(row.get("证券名称", "")).strip(),
                    "cost": float(row.get("成本价", 0)),
                    "qty": int(float(row.get("股票余额", 0))),
                    "market_value": float(row.get("市值", 0)),
                    "pnl_pct": round(float(row.get("盈亏比例", 0) or 0), 2) if "盈亏比例" in row else None,
                })
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    positions.append(item)
    except Exception as e:
        return {"success": False, "data": [], "error": f"解析持仓数据失败: {e}"}

    return {"success": True, "data": positions, "error": ""}


def get_balance_from_ths() -> dict:
    """
    读取账户资金信息。
    返回: {"success": True, "data": {"available": 可用资金, "total_asset": 总资产, ...}}
    """
    user, err = _connect_ths()
    if err:
        return {"success": False, "data": {}, "error": err}

    try:
        raw = user.balance
    except Exception as e:
        msg = str(e).split("\n")[0][:120]
        return {"success": False, "data": {}, "error": f"读取资金失败: {msg}"}

    if raw is None or (hasattr(raw, "empty") and raw.empty):
        return {"success": False, "data": {}, "error": "资金数据为空"}

    balance = _normalize_balance(raw)
    if not balance:
        return {"success": False, "data": {}, "error": "未识别到资金字段"}

    return {"success": True, "data": balance, "error": ""}


def get_account_snapshot(verify_pause: int = 0) -> dict:
    """
    一次性读取持仓 + 资金，返回组合结果。

    Args:
        verify_pause: 连接成功后等待秒数，给用户手动输入验证码的时间。默认 0 不等待。

    返回: {
        "success": bool, "error": str,
        "positions": [...], "balance": {...},
    }
    """
    user, err = _connect_ths()
    if err:
        return {"success": False, "error": err, "positions": [], "balance": {}, "_debug": f"connect failed: {err}"}

    if verify_pause > 0:
        import time
        time.sleep(verify_pause)

    result = {"success": True, "error": "", "positions": [], "balance": {}, "_debug": ""}

    # 配置 Tesseract OCR 路径（easytrader 内部用 pytesseract 识别同花顺界面）
    try:
        import pytesseract
        tesseract_exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(tesseract_exe):
            pytesseract.pytesseract.tesseract_cmd = tesseract_exe
    except Exception:
        pass

    # 读持仓
    try:
        raw_pos = user.position
        debug_lines = [f"position type={type(raw_pos).__name__}"]
        if raw_pos is None:
            debug_lines.append("raw_pos is None")
            result["_debug"] = " | ".join(debug_lines)
        elif hasattr(raw_pos, "empty") and raw_pos.empty:
            debug_lines.append("raw_pos is empty (DataFrame/list empty)")
            result["_debug"] = " | ".join(debug_lines)
        else:
            import pandas as pd
            import logging as _logging
            _log2 = _logging.getLogger("etf_trader")
            _log2.debug(f"[position] type={type(raw_pos).__name__} empty={hasattr(raw_pos, 'empty') and raw_pos.empty if hasattr(raw_pos, 'empty') else 'N/A'}")
            if isinstance(raw_pos, pd.DataFrame):
                debug_lines.append(f"DataFrame columns={list(raw_pos.columns)} rows={len(raw_pos)}")
                result["_debug"] = " | ".join(debug_lines)
                # 调试：输出 DataFrame 列名和行数
                try:
                    import logging
                    _log = logging.getLogger("etf_trader")
                    _log.debug(f"[position] DataFrame columns: {list(raw_pos.columns)} rows={len(raw_pos)}")
                except Exception:
                    pass
                for _, row in raw_pos.iterrows():
                    code = str(row.get("证券代码", "")).strip()
                    if not code:
                        # 尝试其他可能的列名
                        for alt_col in ["代码", "stock_code", "code", "证券代码", "标的代码"]:
                            if alt_col in row.index:
                                code = str(row.get(alt_col, "")).strip()
                                if code:
                                    break
                    if not code:
                        continue
                    result["positions"].append({
                        "code": code,
                        "name": str(row.get("证券名称", "")).strip(),
                        "cost": float(row.get("成本价", 0)),
                        "qty": int(float(row.get("股票余额", 0))),
                        "market_value": float(row.get("市值", 0)),
                        "pnl_pct": round(float(row.get("盈亏比例", 0) or 0), 2) if "盈亏比例" in row else None,
                    })
            elif isinstance(raw_pos, list):
                debug_lines.append(f"list len={len(raw_pos)}")
                if raw_pos and isinstance(raw_pos[0], dict):
                    debug_lines.append(f"first keys={list(raw_pos[0].keys())}")
                result["_debug"] = " | ".join(debug_lines)
                for item in raw_pos:
                    if isinstance(item, dict):
                        # 尝试从 dict 中提取标准字段
                        code = (
                            str(item.get("code", "")).strip()
                            or str(item.get("证券代码", "")).strip()
                            or str(item.get("stock_code", "")).strip()
                            or str(item.get("代码", "")).strip()
                        )
                        if not code:
                            continue  # 跳过无法识别代码的条目
                        result["positions"].append({
                            "code": code,
                            "name": str(item.get("name", "") or item.get("证券名称", "") or item.get("stock_name", "") or "").strip(),
                            "cost": float(item.get("cost", 0) or item.get("成本价", 0) or 0),
                            "qty": int(float(item.get("qty", 0) or item.get("股票余额", 0) or item.get("volume", 0) or 0)),
                            "market_value": float(item.get("market_value", 0) or item.get("市值", 0) or 0),
                            "pnl_pct": (
                                round(float(item.get("pnl_pct", 0) or item.get("盈亏比例", 0) or 0), 2)
                                if any(k in item for k in ("pnl_pct", "盈亏比例"))
                                else None
                            ),
                        })
            else:
                # 无法识别的类型：直接记录 repr 摘要
                try:
                    debug_lines.append(f"unexpected type repr={repr(raw_pos)[:200]}")
                except Exception:
                    debug_lines.append("unexpected type repr failed")
                result["_debug"] = " | ".join(debug_lines)
    except Exception as ex:
        result["_debug"] = f"exception: {type(ex).__name__}: {str(ex)[:200]}"

    # 读资金
    try:
        raw_bal = user.balance
        if raw_bal is not None:
            result["balance"] = _normalize_balance(raw_bal)
    except Exception:
        pass

    return result


def format_positions_for_prompt(positions: list[dict]) -> str:
    """将持仓列表格式化为 LLM prompt 文本"""
    if not positions:
        return "空仓"

    lines = []
    total_value = 0
    for p in positions:
        code = p.get("code", "?")
        name = p.get("name", "")
        cost = p.get("cost", 0)
        qty = p.get("qty", 0)
        mv = p.get("market_value", 0)
        pnl = p.get("pnl_pct")
        total_value += mv

        label = f"{code} {name}".strip()
        line = f"  {label}: 成本 {cost}, 持有 {qty} 份, 市值 {mv:.0f}"
        if pnl is not None:
            line += f" (浮盈 {pnl:+.2f}%)"
        lines.append(line)

    if total_value > 0:
        lines.append(f"  持仓总市值: {total_value:.0f}")

    return "\n".join(lines)


def format_balance_for_prompt(balance: dict) -> str:
    """将资金信息格式化为 LLM prompt 文本"""
    if not balance:
        return "无资金信息"

    labels = {
        "total_asset": "总资产", "available": "可用资金",
        "balance": "资金余额", "market_value": "持仓市值",
        "withdrawable": "可取资金", "float_pnl": "浮动盈亏",
    }
    lines = []
    for key, label in labels.items():
        if key in balance and balance[key]:
            lines.append(f"  {label}: {balance[key]:.2f}")
    return "\n".join(lines) if lines else "无资金信息"

