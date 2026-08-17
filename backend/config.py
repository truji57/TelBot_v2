r"""config.py  carga de variables de entorno para el bot.

Lee primero el archivo `.env`. Si alguna variable relacionada con Anthropic (clave o base URL)
no está definida, intenta obtenerla del archivo de configuración de Claude Code
de `%USERPROFILE%\.claude\settings.json`.
"""

import os
import json
import logging
from pathlib import Path
try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    load_dotenv = lambda path=None: None
    logging.getLogger(__name__).warning("python-dotenv not installed; .env file will not be loaded automatically")

# ---------------------------------------------------------------------------
# 1️⃣ Cargar .env (si existe)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
dotenv_path = BASE_DIR / ".env"
if dotenv_path.is_file():
    load_dotenv(dotenv_path)

# ---------------------------------------------------------------------------
# 2️⃣ Variables de entorno esenciales
# ---------------------------------------------------------------------------
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
SIGNAL_CHANNEL = os.getenv("SIGNAL_CHANNEL", "")
FORWARD_CHAT_ID = os.getenv("FORWARD_CHAT_ID", "")
CONTROL_CHAT_ID = os.getenv("CONTROL_CHAT_ID", "")
# ---------------------------------------------------------------------------
# 5️⃣ Configuración de MetaTrader 5
# ---------------------------------------------------------------------------
MT5_LOGIN = os.getenv("MT5_LOGIN", "")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")
MT5_INSTANCE_ID = os.getenv("MT5_INSTANCE_ID", "default")

# ---------------------------------------------------------------------------
# 6️⃣ Configuración de riesgo y parámetros de trading
# ---------------------------------------------------------------------------
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1.0"))
MAX_LOT_SIZE = float(os.getenv("MAX_LOT_SIZE", "1.0"))
MIN_LOT_SIZE = float(os.getenv("MIN_LOT_SIZE", "0.01"))
_magic = os.getenv("DEFAULT_MAGIC", "20240101")
DEFAULT_MAGIC = int(_magic) if _magic.strip() else 0
ORDER_COMMENT = os.getenv("ORDER_COMMENT", "")
RANDOM_OFFSET_TICKS = int(os.getenv("RANDOM_OFFSET_TICKS", "0"))
ORDER_RETRY_COUNT = int(os.getenv("ORDER_RETRY_COUNT", "0"))
ORDER_RETRY_DELAY = float(os.getenv("ORDER_RETRY_DELAY", "1.0"))
TP_INDEX = int(os.getenv("TP_INDEX", "0"))
RR_RATIO = float(os.getenv("RR_RATIO", "0"))
CONFIRM_TRADES = os.getenv("CONFIRM_TRADES", "false").lower() in ("true", "1", "yes")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# 7️⃣ GitHub auto-update
# ---------------------------------------------------------------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "master")

# ---------------------------------------------------------------------------
# 3️⃣ Variables de Anthropic (clave y base URL)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")

# ---------------------------------------------------------------------------
# 4️⃣ Fallback: leer de settings.json de Claude Code si faltan valores
# ---------------------------------------------------------------------------
if not ANTHROPIC_API_KEY or not ANTHROPIC_BASE_URL:
    try:
        settings_path = os.path.expanduser("~/.claude/settings.json")
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
            env_vars = settings.get("env", {})
            if not ANTHROPIC_API_KEY:
                ANTHROPIC_API_KEY = env_vars.get("ANTHROPIC_AUTH_TOKEN", "")
            if not ANTHROPIC_BASE_URL:
                # OpenRouter suele usar la URL especificada en settings.json
                ANTHROPIC_BASE_URL = env_vars.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    except Exception:
        # Si no se puede leer el archivo, dejamos los valores vacíos; el parser reportará
        # un error de autenticación más claro al usuario.
        pass

# Si la URL sigue vacía, usar la predeterminada de Anthropic (para compatibilidad)
if not ANTHROPIC_BASE_URL:
    ANTHROPIC_BASE_URL = "https://api.anthropic.com"
