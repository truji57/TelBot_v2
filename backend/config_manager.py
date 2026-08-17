"""config_manager.py — Gestor unificado de configuracion (config.json + .env).

Prioridad: config.json > .env > defaults.
Al guardar, escribe en config.json y sincroniza cambios basicos a .env.
"""
import json
import os
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "config.json"
ENV_FILE = BASE_DIR / ".env"

DEFAULTS = {
    "global": {
        "telegram_api_id": "",
        "telegram_api_hash": "",
        "telegram_phone": "",
        "signal_channel": "",
        "forward_chat_id": "",
        "control_chat_id": "",
        "github_repo": "",
        "github_branch": "master",
        "polling_interval": 15,
        "message_limit": 20,
        "dry_run": True,
        "confirm_trades": False,
        "saved_channels": [],
    },
    "accounts": [],
}

_ENV_MAP = {
    "TELEGRAM_API_ID": ("global", "telegram_api_id"),
    "TELEGRAM_API_HASH": ("global", "telegram_api_hash"),
    "TELEGRAM_PHONE": ("global", "telegram_phone"),
    "SIGNAL_CHANNEL": ("global", "signal_channel"),
    "FORWARD_CHAT_ID": ("global", "forward_chat_id"),
    "CONTROL_CHAT_ID": ("global", "control_chat_id"),
    "GITHUB_REPO": ("global", "github_repo"),
    "GITHUB_BRANCH": ("global", "github_branch"),
    "POLLING_INTERVAL": ("global", "polling_interval"),
    "MESSAGE_LIMIT": ("global", "message_limit"),
    "DRY_RUN": ("global", "dry_run"),
    "CONFIRM_TRADES": ("global", "confirm_trades"),
}

ACCOUNT_ENV_MAP = {
    "MT5_LOGIN": "login",
    "MT5_PASSWORD": "password",
    "MT5_SERVER": "server",
    "MT5_TERMINAL_PATH": "terminal_path",
    "RISK_PERCENT": "risk_percent",
    "MAX_LOT_SIZE": "max_lot_size",
    "MIN_LOT_SIZE": "min_lot_size",
    "DEFAULT_MAGIC": "default_magic",
    "ORDER_COMMENT": "order_comment",
}


def _load_env() -> dict:
    values = {}
    if not ENV_FILE.is_file():
        return values
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key, val = stripped.split("=", 1)
                values[key.strip()] = val.strip()
    return values


def _coerce(value: str, default: Any) -> Any:
    if isinstance(default, bool):
        return value.lower() in ("true", "1", "yes")
    if isinstance(default, int):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    if isinstance(default, float):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    return value


def load_config() -> dict:
    config = json.loads(json.dumps(DEFAULTS))
    file_exists = CONFIG_FILE.is_file()

    if file_exists:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if "global" in saved:
                config["global"].update(saved["global"])
            if "accounts" in saved:
                config["accounts"] = saved["accounts"]
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Error leyendo config.json: {e}")

    env = _load_env()

    for env_key, (section, cfg_key) in _ENV_MAP.items():
        if env_key in env and env_key not in _get_override_keys(config):
            config[section][cfg_key] = _coerce(env[env_key], config[section][cfg_key])

    if config["accounts"] and env:
        acc = config["accounts"][0]
        for env_key, cfg_key in ACCOUNT_ENV_MAP.items():
            if env_key in env and env_key not in _get_override_keys(config):
                acc[cfg_key] = _coerce(env[env_key], acc.get(cfg_key, ""))

    if not config["accounts"] and env.get("MT5_LOGIN"):
        acc = {
            "id": "cuenta_1",
            "name": "Cuenta Principal",
            "login": env.get("MT5_LOGIN", ""),
            "password": env.get("MT5_PASSWORD", ""),
            "server": env.get("MT5_SERVER", ""),
            "terminal_path": env.get("MT5_TERMINAL_PATH", ""),
            "instance_id": env.get("MT5_INSTANCE_ID", "default"),
            "risk_percent": float(env.get("RISK_PERCENT", "1.0")),
            "max_lot_size": float(env.get("MAX_LOT_SIZE", "1.0")),
            "min_lot_size": float(env.get("MIN_LOT_SIZE", "0.01")),
            "default_magic": env.get("DEFAULT_MAGIC", ""),
            "order_comment": env.get("ORDER_COMMENT", ""),
            "daily_profit_limit": 0,
            "daily_loss_limit": 0,
            "random_offset_ticks": 0,
            "rr_ratio": 0,
            "tp_index": 0,
            "order_retry_count": 3,
            "order_retry_delay": 1.0,
            "anti_reverse": True,
            "enabled": True,
        }
        config["accounts"] = [acc]
        logger.info("Cuenta migrada desde .env a config.json")

    # Asegurar que todas las cuentas tengan los campos de trading per-account
    for acc in config.get("accounts", []):
        acc.setdefault("random_offset_ticks", 0)
        acc.setdefault("rr_ratio", 0)
        acc.setdefault("tp_index", 0)
        acc.setdefault("order_retry_count", 3)
        acc.setdefault("order_retry_delay", 1.0)
        acc.setdefault("anti_reverse", True)

    # Asegurar exactamente 3 cuentas (rellenar con desactivadas)
    while len(config.get("accounts", [])) < 3:
        config["accounts"].append({
            "id": f"cuenta_{len(config['accounts'])+1}",
            "name": f"Cuenta {len(config['accounts'])+1}",
            "login": "", "password": "", "server": "", "terminal_path": "",
            "instance_id": "default",
            "risk_percent": 1.0, "max_lot_size": 1.0, "min_lot_size": 0.01,
            "default_magic": "", "order_comment": "",
            "daily_profit_limit": 0, "daily_loss_limit": 0,
            "random_offset_ticks": 0, "rr_ratio": 0, "tp_index": 0,
            "order_retry_count": 3, "order_retry_delay": 1.0,
            "enabled": False,
        })

    # Asegurar saved_channels
    config["global"].setdefault("saved_channels", [])

    if not file_exists:
        os.makedirs(CONFIG_FILE.parent, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("config.json creado automaticamente")

    return config


def _get_override_keys(config: dict) -> set:
    return set()


def save_config(config: dict) -> None:
    os.makedirs(CONFIG_FILE.parent, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    global_cfg = config.get("global", {})
    env_lines = []
    if ENV_FILE.is_file():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    env_keys_written = set()
    new_lines = []
    for line in env_lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in _ENV_MAP:
                _, cfg_key = _ENV_MAP[key]
                val = global_cfg.get(cfg_key, "")
                if isinstance(val, bool):
                    val = "true" if val else "false"
                new_lines.append(f"{key}={val}\n")
                env_keys_written.add(key)
            elif key in ACCOUNT_ENV_MAP and config.get("accounts"):
                cfg_key = ACCOUNT_ENV_MAP[key]
                val = config["accounts"][0].get(cfg_key, "")
                new_lines.append(f"{key}={val}\n")
                env_keys_written.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    logger.info("Configuracion guardada en config.json y .env")


def _load() -> dict:
    return load_config()


_cfg_cache = None


def get_config() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        _cfg_cache = load_config()
    return _cfg_cache


def reload():
    global _cfg_cache
    _cfg_cache = load_config()


def get_global(key: str, default: Any = None) -> Any:
    cfg = get_config()
    return cfg["global"].get(key, default)


def get_accounts() -> list:
    cfg = get_config()
    return cfg.get("accounts", [])
