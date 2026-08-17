"""mt5_worker.py — Worker independiente para una cuenta MT5.

Se ejecuta como subproceso del bot principal.
Recibe comandos via HTTP (puerto asignado) y ejecuta en MT5.

Uso: python backend/mt5_worker.py --port 8771 --account-index 0

Endpoints:
  GET  /status   → estado cuenta, posiciones, ordenes, P&L diario
  POST /execute  → ejecutar orden (recibe parsed signal + lot_size)
  POST /pause    → pausar worker
  POST /resume   → reanudar worker
  POST /shutdown → detener worker
"""
import sys
import os
import json
import time
import logging
import threading
import argparse
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

sys.path.insert(0, str(Path(__file__).resolve().parent))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Telbot_v2/

import MetaTrader5 as mt5
from risk_manager import calcular_lotes, determine_order_type

# Lock para serializar llamadas a MT5 (no es thread-safe)
import threading
_mt5_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("mt5_worker")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "data" / "config.json"

# Estado del worker
worker_state = {
    "paused": False,
    "daily_pnl": 0.0,
    "profit_limit": 0,
    "loss_limit": 0,
    "date": datetime.now().strftime("%Y-%m-%d"),
    "account": {},
    "positions": [],
    "pending_orders": [],
}

# Config de cuenta (cargada al iniciar)
_account_cfg: dict = {}
_account_name: str = ""

def load_account_config(index: int) -> dict | None:
    if not CONFIG_FILE.is_file():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    accounts = cfg.get("accounts", [])
    if index >= len(accounts):
        return None
    return accounts[index]


def _get_current_price(symbol: str) -> float | None:
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return None
    if tick.bid and tick.ask:
        return (tick.bid + tick.ask) / 2.0
    return tick.bid or tick.ask


def _calc_lot(symbol: str, balance: float, entry: float, sl: float, risk_pct: float, max_lot: float, min_lot: float) -> float:
    if not sl or sl == 0 or not entry or entry == 0:
        return min_lot
    try:
        info = mt5.symbol_info(symbol)
        if not info:
            return min_lot
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return min_lot
        tick_size = info.trade_tick_size
        tick_value = info.trade_tick_value
        if not tick_size or not tick_value:
            return min_lot

        # Correccion de contract_size para brokers que reportan mal (XAUUSD)
        contract_size = getattr(info, "trade_contract_size", None)
        if contract_size:
            if symbol == "XAUUSD" and contract_size >= 1000:
                contract_size = 100.0
            expected = contract_size * tick_size
            if tick_value <= 0 or (expected > 0 and tick_value < expected * 0.3):
                tick_value = expected

        riesgo_usd = balance * (risk_pct / 100.0)
        sl_ticks = sl_dist / tick_size
        loss_per_lot = sl_ticks * tick_value
        if loss_per_lot <= 0:
            return min_lot
        lots = riesgo_usd / loss_per_lot
        lot_step = info.volume_step or 0.01
        raw = int(lots / lot_step) * lot_step
        result = max(info.volume_min or min_lot, raw)
        result = min(result, max_lot)
        return round(result, 2)
    except Exception as e:
        logger.warning(f"Error en _calc_lot: {e}")
        return min_lot


def _translate_symbol(symbol: str, server: str = "") -> str:
    mt5_symbols = mt5.symbols_get()
    if mt5_symbols:
        mt5_names = {s.name for s in mt5_symbols}
        if symbol in mt5_names:
            return symbol
        prefix_lower = symbol.lower()
        for mt5_name in mt5_names:
            if mt5_name.lower().startswith(prefix_lower):
                return mt5_name
    return symbol
    mt5_symbols = mt5.symbols_get()
    if mt5_symbols:
        mt5_names = {s.name for s in mt5_symbols}
        if symbol in mt5_names:
            return symbol
        prefix_lower = symbol.lower()
        for mt5_name in mt5_names:
            if mt5_name.lower().startswith(prefix_lower):
                return mt5_name
    return symbol


def init_mt5(acc: dict) -> bool:
    terminal_path = acc.get("terminal_path", "")
    init_kwargs = {}
    if terminal_path:
        init_kwargs["path"] = terminal_path
    if not mt5.initialize(**init_kwargs):
        logger.error(f"Inicializacion MT5 fallida: {mt5.last_error()}")
        return False
    login_val = int(acc.get("login", 0))
    if not mt5.login(login_val, password=acc.get("password", ""), server=acc.get("server", "")):
        logger.error(f"Login MT5 fallido: {mt5.last_error()}")
        mt5.shutdown()
        return False
    logger.info(f"Conectado a MT5: login={login_val} server={acc.get('server')}")
    return True


def _get_filling_mode(symbol: str) -> int:
    try:
        info = mt5.symbol_info(symbol)
        if info and hasattr(info, "trade_filling") and info.trade_filling:
            return info.trade_filling
    except Exception:
        pass
    return mt5.ORDER_FILLING_RETURN


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class WorkerHandler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status":
            self._handle_status()
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
        except Exception:
            body = {}

        if self.path == "/execute":
            self._handle_execute(body)
        elif self.path == "/pause":
            worker_state["paused"] = True
            logger.info("Worker PAUSADO")
            self._json({"ok": True})
        elif self.path == "/resume":
            worker_state["paused"] = False
            logger.info("Worker REANUDADO")
            self._json({"ok": True})
        elif self.path == "/reload":
            self._handle_reload()
        elif self.path == "/shutdown":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._json({"error": "Not found"}, 404)

    def _handle_status(self):
        try:
            self._do_handle_status()
        except Exception as e:
            logger.error(f"Error en /status: {e}")
            self._json({"error": str(e)}, 500)

    def _do_handle_status(self):
        try:
            with _mt5_lock:
                info = mt5.account_info()
                if info:
                    positions_data = []
                    positions = mt5.positions_get()
                    if positions:
                        for pos in positions:
                            tick = mt5.symbol_info_tick(pos.symbol)
                            cp = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask if tick else 0
                            positions_data.append({
                                "ticket": pos.ticket, "symbol": pos.symbol,
                                "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                                "volume": getattr(pos, "volume", 0),
                                "entry": getattr(pos, "price_open", 0),
                                "sl": getattr(pos, "sl", None) or 0,
                                "tp": getattr(pos, "tp", None) or 0,
                                "current_price": cp,
                                "profit": getattr(pos, "profit", 0),
                            })

                    orders_data = []
                    orders = mt5.orders_get()
                    if orders:
                        type_map = {mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT", mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
                                    mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP", mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP"}
                        for o in orders:
                            orders_data.append({
                                "ticket": o.ticket, "symbol": o.symbol,
                                "type": type_map.get(o.type, "UNKNOWN"),
                                "volume": getattr(o, "volume", None) or getattr(o, "volume_initial", 0),
                                "price": getattr(o, "price", None) or getattr(o, "price_open", 0),
                                "sl": o.sl or 0, "tp": o.tp or 0,
                            })

                    # Tracking P&L diario (desde historico de deals del dia)
                    today = datetime.now().strftime("%Y-%m-%d")
                    if worker_state["date"] != today:
                        worker_state["daily_pnl"] = 0.0
                        worker_state["paused"] = False
                        worker_state["date"] = today

                    import datetime as _dt
                    day_start = _dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    deals = mt5.history_deals_get(day_start, _dt.datetime.now())
                    today_profit = 0.0
                    if deals is None:
                        logger.warning(f"history_deals_get devolvio None: {mt5.last_error()}")
                    elif deals:
                        for deal in deals:
                            today_profit += getattr(deal, 'profit', 0) or 0
                    worker_state["daily_pnl"] = round(today_profit, 2)

                    # Auto-pausa por limites
                    if not worker_state["paused"]:
                        pl = worker_state.get("profit_limit", 0)
                        ll = worker_state.get("loss_limit", 0)
                        if pl > 0 and worker_state["daily_pnl"] >= pl:
                            worker_state["paused"] = True
                            logger.warning(f"LIMITE profit alcanzado ({pl}) → PAUSADO")
                        elif ll > 0 and worker_state["daily_pnl"] <= -ll:
                            worker_state["paused"] = True
                            logger.warning(f"LIMITE perdida alcanzado ({ll}) → PAUSADO")

                    worker_state["account"] = {
                        "balance": info.balance if info else 0,
                        "equity": info.equity if info else 0,
                        "profit": info.profit if info else 0,
                        "positions": len(positions_data),
                        "pending_orders": len(orders_data),
                        "server": info.server if info else "?",
                        "currency": info.currency if info else "",
                        "login": info.login if info else 0,
                    }
                    worker_state["positions"] = positions_data
                    worker_state["pending_orders"] = orders_data
                    worker_state["name"] = _account_name

            self._json(worker_state)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_reload(self):
        global _account_cfg
        try:
            # Obtener account-index del worker (guardado al iniciar)
            idx = int(_account_cfg.get("_index", -1))
            if idx < 0:
                self._json({"error": "No se pudo determinar indice de cuenta"})
                return
            acc = load_account_config(idx)
            if not acc:
                self._json({"error": "Cuenta no encontrada en config.json"})
                return
            _account_cfg = acc
            worker_state["profit_limit"] = float(acc.get("daily_profit_limit", 0) or 0)
            worker_state["loss_limit"] = float(acc.get("daily_loss_limit", 0) or 0)
            # Si se deshabilito, pausar
            if not acc.get("enabled", True):
                worker_state["paused"] = True
            logger.info(f"Worker recargado: risk={acc.get('risk_percent')}% rr={acc.get('rr_ratio')}")
            self._json({"ok": True})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_execute(self, body):
        try:
            self._do_handle_execute(body)
        except Exception as e:
            logger.error(f"Error en /execute: {e}")
            self._json({"success": False, "error": str(e)})

    def _do_handle_execute(self, body):
        if worker_state["paused"]:
            self._json({"success": False, "error": "Worker pausado"})
            return

        with _mt5_lock:
            parsed = body.get("parsed", {})
            action = parsed.get("action", "").upper()
            symbol = parsed.get("symbol")
            entry = float(parsed.get("entry")) if parsed.get("entry") is not None else None
            sl = float(parsed.get("sl")) if parsed.get("sl") is not None else None
            tp_list = [float(t) for t in parsed.get("tp", [])]

            if not action or not symbol:
                self._json({"success": False, "error": "Faltan action o symbol"})
                return

            symbol = _translate_symbol(symbol, worker_state.get("account", {}).get("server", ""))
            mt5.symbol_select(symbol, True)

            # Anti-reverse: si hay posicion u orden contraria abierta, ignorar
            if _account_cfg.get("anti_reverse", True):
                positions = mt5.positions_get(symbol=symbol)
                if positions:
                    for pos in positions:
                        if action == "BUY" and pos.type == mt5.ORDER_TYPE_SELL:
                            logger.info(f"[ANTI-REVERSE] SELL abierta ({pos.symbol}) → ignorando señal BUY")
                            self._json({"success": False, "error": "Posicion contraria abierta (anti-reverse)"})
                            return
                        elif action == "SELL" and pos.type == mt5.ORDER_TYPE_BUY:
                            logger.info(f"[ANTI-REVERSE] BUY abierta ({pos.symbol}) → ignorando señal SELL")
                            self._json({"success": False, "error": "Posicion contraria abierta (anti-reverse)"})
                            return
                orders = mt5.orders_get(symbol=symbol)
                if orders:
                    for o in orders:
                        if action == "BUY" and o.type in (mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP):
                            logger.info(f"[ANTI-REVERSE] SELL_LIMIT/STOP pendiente ({o.symbol}) → ignorando señal BUY")
                            self._json({"success": False, "error": "Orden contraria pendiente (anti-reverse)"})
                            return
                        elif action == "SELL" and o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP):
                            logger.info(f"[ANTI-REVERSE] BUY_LIMIT/STOP pendiente ({o.symbol}) → ignorando señal SELL")
                            self._json({"success": False, "error": "Orden contraria pendiente (anti-reverse)"})
                            return

            # Calcular lote con la config de riesgo de esta cuenta
            risk_pct = float(_account_cfg.get("risk_percent", 1.0))
            max_lot = float(_account_cfg.get("max_lot_size", 1.0))
            min_lot = float(_account_cfg.get("min_lot_size", 0.01))

            info = mt5.account_info()
            balance = info.balance if info else 1000

            try:
                lot = _calc_lot(symbol, balance, entry or 0, sl or 0, risk_pct, max_lot, min_lot)
            except Exception as e:
                logger.warning(f"Error calculando lote: {e}, usando min_lot={min_lot}")
                lot = min_lot

            # TP_INDEX: elegir TP segun config (0=ultimo, 1=TP1, 2=TP2, 3=TP3)
            tp_index = int(_account_cfg.get("tp_index", 0))
            if tp_index > 0 and len(tp_list) >= tp_index:
                tp = tp_list[tp_index - 1]
            elif tp_list:
                tp = tp_list[-1]
            else:
                tp = 0.0

            # RR_RATIO per-account
            rr_ratio = float(_account_cfg.get("rr_ratio", 0) or 0)
            if rr_ratio > 0 and entry and sl and action in ("BUY", "SELL"):
                if action == "BUY":
                    risk = entry - sl
                    tp = entry + risk * rr_ratio
                else:
                    risk = sl - entry
                    tp = entry - risk * rr_ratio
                logger.info(f"RR {rr_ratio}:1 → TP={tp:.5f}")

            # Random offset anti-group-trading
            random_offset = int(_account_cfg.get("random_offset_ticks", 0) or 0)
            if random_offset > 0 and entry:
                import random
                tick_size = 0.01
                try:
                    info_sym = mt5.symbol_info(symbol)
                    if info_sym and info_sym.trade_tick_size:
                        tick_size = info_sym.trade_tick_size
                except Exception:
                    pass
                abs_off = random.randint(1, random_offset) * tick_size
                tick = mt5.symbol_info_tick(symbol)
                current = None
                if tick:
                    current = (tick.bid + tick.ask) / 2 if tick.bid and tick.ask else (tick.bid or tick.ask)
                offset_price = abs_off if (entry < (current or entry + 1)) else -abs_off if current else 0
                if offset_price != 0:
                    entry += offset_price
                    sl += offset_price
                    tp += offset_price
                    logger.info(f"Random offset: {offset_price:.5f} ({abs_off/tick_size:.0f} ticks)")

            # Determinar tipo de orden
            order_type_str = determine_order_type(action, entry, symbol)

            if order_type_str == "market":
                order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
                price = 0.0
                trade_action = mt5.TRADE_ACTION_DEAL
            elif order_type_str == "limit":
                order_type = mt5.ORDER_TYPE_BUY_LIMIT if action == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
                price = entry
                trade_action = mt5.TRADE_ACTION_PENDING
            elif order_type_str == "stop":
                order_type = mt5.ORDER_TYPE_BUY_STOP if action == "BUY" else mt5.ORDER_TYPE_SELL_STOP
                price = entry
                trade_action = mt5.TRADE_ACTION_PENDING
            else:
                self._json({"success": False, "error": f"Tipo desconocido: {order_type_str}"})
                return

            mt5.symbol_select(symbol, True)

            magic = int(_account_cfg.get("default_magic", 0) or 0)
            comment = _account_cfg.get("order_comment", "") or ""

            request = {
                "action": trade_action,
                "symbol": symbol,
                "volume": lot,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 10,
                "magic": magic,
                "comment": comment,
                "type_filling": _get_filling_mode(symbol),
                "type_time": mt5.ORDER_TIME_GTC,
            }

            retry_count = int(_account_cfg.get("order_retry_count", 0) or 0)
            retry_delay = float(_account_cfg.get("order_retry_delay", 1.0) or 1.0)
            retryable = {10006, 10012, 10015, 10020, 10031}
            last_retcode = None

            logger.info(f"[ORDER] {action} {symbol} lot={lot:.2f} entry={entry} sl={sl} tp={tp} magic={magic}")

            for attempt in range(1 + retry_count):
                if attempt > 0:
                    logger.info(f"Reintento {attempt}/{retry_count}")
                    import time as _t
                    _t.sleep(retry_delay)

                result = mt5.order_send(request)
                if result is None:
                    mt5_err = mt5.last_error()
                    logger.warning(f"order_send devolvio None: {mt5_err} | request={request}")
                elif result.retcode == mt5.TRADE_RETCODE_DONE or result.retcode == mt5.TRADE_RETCODE_PLACED:
                    logger.info(f"Orden OK: {action} {symbol} ticket={result.order}")
                    self._json({"success": True, "ticket": result.order, "pending": result.retcode == mt5.TRADE_RETCODE_PLACED})
                    return

                last_retcode = result.retcode if result else None
                if last_retcode not in retryable:
                    break

            err = result.comment if result else f"order_send returned None: {mt5.last_error()}"
            rc = result.retcode if result else "?"
            logger.error(f"Orden fallida: {err} (retcode={rc})")
            self._json({"success": False, "error": str(err), "retcode": rc})


def main():
    global _account_cfg, _account_name
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--account-index", type=int, required=True)
    args = parser.parse_args()

    acc = load_account_config(args.account_index)
    if not acc:
        logger.error(f"Cuenta {args.account_index} no encontrada en config.json")
        sys.exit(1)

    if not acc.get("enabled", True):
        logger.info(f"Cuenta {acc.get('name', args.account_index)} deshabilitada — worker no inicia")
        sys.exit(0)

    _account_cfg = acc
    _account_cfg["_index"] = args.account_index
    _account_name = acc.get("name") or acc.get("server", f"Cuenta {args.account_index+1}")

    if not init_mt5(acc):
        sys.exit(1)

    # Cargar limites
    worker_state["profit_limit"] = float(acc.get("daily_profit_limit", 0) or 0)
    worker_state["loss_limit"] = float(acc.get("daily_loss_limit", 0) or 0)

    logger.info(f"Worker '{_account_name}' iniciado en puerto {args.port}")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), WorkerHandler)
    print("READY", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        mt5.shutdown()
        logger.info("Worker finalizado")


if __name__ == "__main__":
    main()
