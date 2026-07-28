"""
配置管理器：统一 JSON 读写 + Fernet 加密 + 开发/冻结双模式
合并自 ETF-Advisor 和 BiliDigest，使用持久化密钥文件方案。
"""
import json
import sys
import os
import shutil
from pathlib import Path

_SENSITIVE_KEYS = {"llm_api_key", "email_auth_code"}

_IS_FROZEN = getattr(sys, "frozen", False)

if _IS_FROZEN:
    _APPDATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "etf-pipeline")
    os.makedirs(_APPDATA, exist_ok=True)
    CONFIG_DIR = Path(_APPDATA)
    _BUNDLE_CONFIG = Path(sys._MEIPASS) / "config" / "settings.json"
    if _BUNDLE_CONFIG.exists() and not (CONFIG_DIR / "settings.json").exists():
        shutil.copy2(str(_BUNDLE_CONFIG), str(CONFIG_DIR / "settings.json"))
else:
    CONFIG_DIR = Path(__file__).parent.parent / "config"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
KEY_FILE = CONFIG_DIR / ".fernet_key"

DEFAULTS = {
    "llm_provider": "deepseek",
    "llm_model": "deepseek-v4-pro",
    "llm_api_key": "",
    "llm_temperature": 0.7,
    "risk_profile": "standard",
    "default_etf": "510050",
    "default_days": 60,
    "max_bars": 200,
    "data_source": "baostock",
    "data_source_token": "",
    "sentiment_dir": "",
    "output_dir": "",
    "recent_etfs": [],
    "manual_positions": [],
    "manual_balance": {},
    "risk_params": {
        "conservative": {
            "rsi_oversold": 30, "rsi_overbought": 70,
            "take_profit_pct": 3.0, "stop_loss_pct": 2.0,
            "ma_short": 20, "ma_long": 60,
        },
        "standard": {
            "rsi_oversold": 25, "rsi_overbought": 75,
            "take_profit_pct": 5.0, "stop_loss_pct": 3.0,
            "ma_short": 10, "ma_long": 30,
        },
        "aggressive": {
            "rsi_oversold": 20, "rsi_overbought": 80,
            "take_profit_pct": 8.0, "stop_loss_pct": 5.0,
            "ma_short": 5, "ma_long": 20,
        },
    },
    "bili2text_dir": "D:\\bili2text",
    "cookie_file": "D:\\bili2text\\.b2t\\cookies.txt",
    "batch_save_path": "E:/video2txt",
    "max_per_video_chars": 1500,
    "debug_log": "",
    "valley_scheduler_enabled": "true",
    "email_enabled": "false",
    "email_smtp_server": "smtp.qq.com",
    "email_smtp_port": "465",
    "email_sender": "",
    "email_auth_code": "",
    "email_receiver": "",
    "feishu_enabled": "false",
    "feishu_webhook": "",
    "close_action": "tray",
    "close_dont_ask": "false",
    "peak_skip_today": "",
}


def _get_cipher():
    from cryptography.fernet import Fernet
    if KEY_FILE.exists():
        key = KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(key)
    return Fernet(key)


def _encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    return _get_cipher().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt_value(ciphertext: str):
    if not ciphertext or not ciphertext.startswith("gAAAAA"):
        return None
    try:
        return _get_cipher().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


_settings_cache = None


def load_settings():
    global _settings_cache
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        data = {}

    has_plain = any(
        k in data and isinstance(data.get(k), str)
        and not data[k].startswith("gAAAAA")
        for k in _SENSITIVE_KEYS
    )
    if has_plain:
        for k in _SENSITIVE_KEYS:
            val = data.get(k)
            if val and isinstance(val, str) and not val.startswith("gAAAAA"):
                data[k] = _encrypt_value(val)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if v is not None})
    _settings_cache = merged
    return merged


def save_settings(settings: dict):
    global _settings_cache
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    _settings_cache = settings.copy()


def get_setting(key: str, default=None):
    global _settings_cache
    if _settings_cache is None:
        load_settings()
    val = _settings_cache.get(key)
    if val is None:
        return default if default is not None else DEFAULTS.get(key)
    if key in _SENSITIVE_KEYS and isinstance(val, str) and val.startswith("gAAAAA"):
        decrypted = _decrypt_value(val)
        if decrypted is not None:
            return decrypted
    return val


def get_raw_setting(key: str):
    global _settings_cache
    if _settings_cache is None:
        load_settings()
    return _settings_cache.get(key, DEFAULTS.get(key, ""))


def set_setting(key: str, value):
    global _settings_cache
    if _settings_cache is None:
        load_settings()
    store = value
    if key in _SENSITIVE_KEYS and value and not str(value).startswith("gAAAAA"):
        store = _encrypt_value(str(value))
    _settings_cache[key] = store
    save_settings(_settings_cache)


def get_risk_params(profile: str = None) -> dict:
    if profile is None:
        profile = get_setting("risk_profile", "standard")
    risk_map = get_setting("risk_params", {})
    return risk_map.get(profile, risk_map.get("standard", {}))


def get_bili2text_path() -> Path:
    return Path(get_setting("bili2text_dir", DEFAULTS["bili2text_dir"]))


def get_debug_log_path() -> Path:
    p = get_setting("debug_log", "")
    if p:
        return Path(p)
    return CONFIG_DIR / "debug.log"


def get_cookie_path() -> str:
    return get_setting("cookie_file", DEFAULTS["cookie_file"])
