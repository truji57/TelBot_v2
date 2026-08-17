"""api_server.py — Servidor HTTP + WebSocket para TelBot v2.

Proporciona:
- WebSocket /ws → estado en tiempo real para el frontend
- REST /api/start, /api/stop → control del bot
- REST /api/config (GET/POST) → leer/guardar .env
- REST /api/status → estado actual de la cuenta MT5
"""

import asyncio
import json
import os
import logging
import threading
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

from config_manager import load_config, save_config, get_config, reload

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# Estado compartido
state = {
    "running": True,
    "stopped": False,
    "signals": [],
    "account": {},
    "accounts": [],
    "positions": [],
    "pending_orders": [],
    "last_update": None,
}

# Cola de reintentos (el bot la consume en su loop)
retry_queue = []

# Cola de test de mensajes
test_message_queue = []

# Estado por cuenta: { "cuenta1": { "daily_pnl": 0.0, "paused": False, "date": "2026-08-05" } }
account_states = {}

# Callback que registra el bot para notificar eventos
# Workers MT5 (referencia compartida con telegram_listener)
_workers_ref = None

def set_workers_ref(workers):
    global _workers_ref
    _workers_ref = workers


def register_listener(notify_fn):
    """El bot llama a esto para notificar señales y estado."""
    global _listener
    _listener = notify_fn


def notify_frontend(event_type: str, data: dict):
    """Envía un evento al frontend vía REST (polling)."""
    global state
    if event_type == "signal":
        data["_retry"] = json.dumps(data.get("_retry", {}))
        state["signals"].insert(0, data)
        state["signals"] = state["signals"][:50]
    elif event_type == "signal_result":
        for s in state["signals"]:
            if s.get("status") == "pending":
                s["status"] = data.get("status", "pending")
                break
    elif event_type == "status":
        state["account"] = data.get("account", {})
        state["accounts"] = data.get("accounts", [])
        state["positions"] = data.get("positions", [])
        state["pending_orders"] = data.get("pending_orders", [])
        state["running"] = data.get("running", state["running"])
    state["last_update"] = datetime.now().isoformat()


class APIHandler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors_preflight(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._cors_preflight()

    def do_GET(self):
        if self.path == "/api/status":
            try:
                self._json({
                    "running": state["running"],
                    "stopped": state["stopped"],
                    "signals": state["signals"][-10:],
                    "account": state["account"],
                    "accounts": state["accounts"],
                    "positions": state["positions"],
                    "pending_orders": state["pending_orders"],
                    "account_states": account_states,
                    "last_update": state["last_update"],
                })
            except Exception as e:
                logger.error(f"Error serializando status: {e}")
                self._json({"error": "Error interno"}, 500)
        elif self.path == "/api/config":
            self._json(get_config())
        elif self.path == "/ws":
            self._json({"error": "Use WebSocket, not HTTP"}, 426)
        else:
            self._json({"error": "Not found"}, 404)

    def _handle_account_action(self, action):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            name = body.get("name", "")
            if not name or not _workers_ref:
                self._json({"error": "Falta nombre de cuenta o workers no disponibles"})
                return
            for w in _workers_ref.values():
                if w["name"] == name:
                    import urllib.request
                    req = urllib.request.Request(f"http://127.0.0.1:{w['port']}/{action}", method="POST")
                    urllib.request.urlopen(req, timeout=5)
                    logger.info(f"Worker '{name}' → {action}")
                    self._json({"ok": True})
                    return
            self._json({"error": f"Worker '{name}' no encontrado"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        if self.path == "/api/start":
            state["running"] = True
            state["stopped"] = False
            logger.info("Bot RUN vía API")
            self._json({"ok": True, "running": True, "stopped": False})
        elif self.path == "/api/pause":
            state["running"] = False
            state["stopped"] = False
            logger.info("Bot PAUSADO vía API")
            self._json({"ok": True, "running": False, "stopped": False})
        elif self.path == "/api/stop":
            state["running"] = False
            state["stopped"] = True
            if _workers_ref:
                import urllib.request
                for w in _workers_ref.values():
                    try:
                        req = urllib.request.Request(f"http://127.0.0.1:{w['port']}/shutdown", method="POST")
                        urllib.request.urlopen(req, timeout=3)
                    except Exception:
                        pass
            logger.info("Bot STOP vía API")
            self._json({"ok": True, "running": False, "stopped": True})
        elif self.path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                updates = json.loads(body)
                save_config(updates)
                reload()
                if _workers_ref:
                    import urllib.request
                    for w in _workers_ref.values():
                        try:
                            req = urllib.request.Request(f"http://127.0.0.1:{w['port']}/reload", method="POST")
                            urllib.request.urlopen(req, timeout=3)
                            logger.info(f"Worker '{w['name']}' recargado")
                        except Exception as e:
                            logger.warning(f"No se pudo recargar worker '{w['name']}': {e}")
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif self.path == "/api/test-account":
            if state["running"]:
                self._json({"error": "Pausa el bot antes de testear una cuenta"}, 409)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body)
                from mt5_connector import test_account_connection
                result = test_account_connection(
                    data.get("login", ""),
                    data.get("password", ""),
                    data.get("server", ""),
                    data.get("terminal_path", ""),
                )
                self._json(result)
            except Exception as e:
                self._json({"success": False, "error": str(e)}, 500)
        elif self.path == "/api/retry":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body)
                retry_queue.append(data)
                logger.info(f"Reintento encolado: {data.get('symbol', '?')} {data.get('action', '?')}")
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif self.path == "/api/test-forward":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body)
                test_message_queue.append(data.get("chat_id", ""))
                logger.info(f"Test forward encolado para {data.get('chat_id')}")
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif self.path == "/api/pause-account":
            self._handle_account_action("pause")
        elif self.path == "/api/resume-account":
            self._handle_account_action("resume")
        else:
            self._json({"error": "Not found"}, 404)


def start_api_server(port=8766):
    """Arranca el servidor API en un hilo separado."""
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    logger.info(f"API server en http://localhost:{port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
