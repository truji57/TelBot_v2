"""telegram_listener.py
Escucha el canal de señales y reenvía mensajes al chat de destino.

DRY_RUN se omita la conexión a MT5, solo funciona Telegram.
"""
import os
import sys
import json
import csv
import logging
import asyncio
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from telethon.tl.types import PeerChannel
from telethon.errors import RPCError
import MetaTrader5 as mt5

# Cargar configuración desde .env
from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_PHONE,
    SIGNAL_CHANNEL,
    FORWARD_CHAT_ID,
    CONTROL_CHAT_ID,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_TERMINAL_PATH,
    CONFIRM_TRADES,
    DRY_RUN,
    RANDOM_OFFSET_TICKS,
)
from api_server import notify_frontend, start_api_server, state as api_state, set_workers_ref

# ---------------------------------------------------------------------------
# Preparar logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/trading_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
    logger.error("Faltan TELEGRAM_API_ID o TELEGRAM_API_HASH en .env")
    raise SystemExit(1)

# Variables globales para entidades de canales
CHANNEL_SRC_ENTITY = None
CHANNEL_FORWARD_ENTITY = None
CHANNEL_CONTROL_ENTITY = None

# Conjunto global para rastrear IDs de mensajes procesados y evitar duplicados
PROCESSED_MESSAGES = set()
# Variable global que mantiene el último ID de mensaje procesado
last_processed_id = 0
# Indica si el primer ciclo de polling ya se ejecutó (evita procesar historial al iniciar)
FIRST_POLL_DONE = False

# Variables globales para confirmación de trades y balance
PENDING_CONFIRMATIONS = {}
ACCOUNT_BALANCE = 0.0

# Variables de configuración del polling (leídas desde .env)
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL", "15"))  # Segundos entre revisiones
MESSAGE_LIMIT = int(os.getenv("MESSAGE_LIMIT", "20"))         # Máximo de mensajes a revisar por ciclo

# Ruta para el archivo de persistencia del último ID procesado
LAST_PROCESSED_ID_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "last_processed_id.txt")

# Ruta para el archivo CSV de mensajes procesados
MESSAGES_CSV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed_messages.csv")

def load_last_processed_id():
    """Carga el último ID procesado desde el archivo persistente"""
    try:
        if os.path.exists(LAST_PROCESSED_ID_FILE):
            with open(LAST_PROCESSED_ID_FILE, "r") as f:
                return int(f.read().strip())
        return 0
    except:
        return 0

def save_last_processed_id(msg_id):
    """Guarda el último ID procesado en el archivo persistente"""
    with open(LAST_PROCESSED_ID_FILE, "w") as f:
        f.write(str(msg_id))

# ---------------------------------------------------------------------------
# Crear cliente Telethon (dentro de main para tener event loop)
# ---------------------------------------------------------------------------
client = None

# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------
def _print_banner():
    banner = r"""
████████╗███████╗██╗     ██████╗  ██████╗ ████████╗
╚══██╔══╝██╔════╝██║     ██╔══██╗██╔═══██╗╚══██╔══╝
   ██║   █████╗  ██║     ██████╔╝██║   ██║   ██║
   ██║   ██╔══╝  ██║     ██╔══██╗██║   ██║   ██║
   ██║   ███████╗███████╗██████╔╝╚██████╔╝   ██║
   ╚═╝   ╚══════╝╚══════╝╚═════╝  ╚═════╝    ╚═╝
                       v2.24
    """
    print(banner)

async def main():
    global client, last_processed_id, CHANNEL_SRC_ENTITY, CHANNEL_FORWARD_ENTITY, CHANNEL_CONTROL_ENTITY, ACCOUNT_BALANCE
    _print_banner()

    # Arrancar servidor API para el frontend
    api_server = start_api_server(port=8766)
    logger.info("API server iniciado en http://localhost:8766")

    # Inicializar dentro del event loop (necesario en Python 3.12+)
    csv_lock = asyncio.Lock()
    client = TelegramClient("trading_bot", int(TELEGRAM_API_ID), TELEGRAM_API_HASH)

    async def save_message_to_csv(msg_id, text, timestamp=None):
        nonlocal csv_lock
        if timestamp is None:
            timestamp = datetime.now()
        file_exists = os.path.exists(MESSAGES_CSV_FILE)
        async with csv_lock:
            with open(MESSAGES_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['message_id', 'text', 'timestamp'])
                writer.writerow([msg_id, text, timestamp.isoformat()])

    def get_all_processed_ids():
        message_ids = set()
        if not os.path.exists(MESSAGES_CSV_FILE):
            return message_ids
        with open(MESSAGES_CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                next(reader)
            except:
                return message_ids
            for row in reader:
                if len(row) >= 1:
                    try:
                        message_ids.add(int(row[0]))
                    except:
                        continue
        return message_ids

    # Cargar último ID procesado desde archivo persistente al iniciar
    last_processed_id = load_last_processed_id()

    # Conectar cliente
    await client.start(phone=TELEGRAM_PHONE)
    logger.info("Cliente Telethon conectado")

    # ---------------------------------------------------------------
    # Resolver entidades de canales
    # ---------------------------------------------------------------
    try:
        # Canal de origen
        if SIGNAL_CHANNEL.lstrip("-").isdigit():
            src_id = int(SIGNAL_CHANNEL)
            CHANNEL_SRC_ENTITY = PeerChannel(src_id)
        else:
            CHANNEL_SRC_ENTITY = await client.get_input_entity(SIGNAL_CHANNEL)
        logger.info(f"Canal origen resuelto: {SIGNAL_CHANNEL}")
    except Exception as e:
        logger.error(f"No se pudo resolver el canal de origen {SIGNAL_CHANNEL}: {e}")
        raise SystemExit(1)

    try:
        # Canal de destino
        if FORWARD_CHAT_ID.lstrip("-").isdigit():
            dst_id = int(FORWARD_CHAT_ID)
            CHANNEL_FORWARD_ENTITY = PeerChannel(dst_id)
        else:
            CHANNEL_FORWARD_ENTITY = await client.get_input_entity(FORWARD_CHAT_ID)
        logger.info(f"Canal de destino resuelto: {FORWARD_CHAT_ID}")
    except Exception as e:
        logger.error(f"No se pudo resolver el canal de destino {FORWARD_CHAT_ID}: {e}")
        raise SystemExit(1)

    # Chat de control (comandos) — opcional
    if CONTROL_CHAT_ID:
        try:
            ctrl_id = int(CONTROL_CHAT_ID)
            CHANNEL_CONTROL_ENTITY = abs(ctrl_id)
            logger.info(f"Chat de control configurado: {ctrl_id}")
        except ValueError:
            try:
                CHANNEL_CONTROL_ENTITY = await client.get_input_entity(CONTROL_CHAT_ID)
                logger.info(f"Chat de control resuelto: {CONTROL_CHAT_ID}")
            except Exception as e:
                logger.warning(f"No se pudo resolver el chat de control {CONTROL_CHAT_ID}: {e}. Comandos deshabilitados.")
                CHANNEL_CONTROL_ENTITY = None
    else:
        logger.info("CONTROL_CHAT_ID no configurado — comandos deshabilitados")

    # ---------------------------------------------------------------
    # Workers MT5 (uno por cuenta configurada, max 3)
    # ---------------------------------------------------------------
    workers = {}  # { account_index: {"port": int, "name": str, "proc": Popen} }
    from config_manager import get_config
    cfg = get_config()
    accounts = cfg.get("accounts", [])[:3]

    if not DRY_RUN and accounts:
        for i, acc in enumerate(accounts):
            if not acc.get("enabled", True):
                logger.info(f"Cuenta '{acc.get('name', i)}' deshabilitada, omitiendo worker")
                continue
            port = 8771 + i
            log_file = open(os.path.join("logs", f"worker_{i}.log"), "w")
            proc = subprocess.Popen(
                [sys.executable, os.path.join(os.path.dirname(__file__), "mt5_worker.py"),
                 "--port", str(port), "--account-index", str(i)],
                stdout=log_file, stderr=subprocess.STDOUT,
            )
            name = acc.get("name") or acc.get("server", f"Cuenta {i+1}")
            workers[i] = {"port": port, "name": name, "proc": proc, "log": log_file}
            logger.info(f"Worker '{name}' lanzado en puerto {port} (PID {proc.pid})")

        # Esperar a que cada worker responda via HTTP (timeout 30s)
        import urllib.request as _ur
        for i, w in list(workers.items()):
            ready = False
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    req = _ur.Request(f"http://127.0.0.1:{w['port']}/status")
                    _ur.urlopen(req, timeout=2)
                    ready = True
                    break
                except Exception:
                    time.sleep(1)
            if not ready:
                logger.warning(f"Worker '{w['name']}' no responde — se omitira")
                try:
                    w["proc"].terminate()
                except Exception:
                    pass
                w["log"].close()
                del workers[i]
    elif not DRY_RUN and not accounts:
        logger.warning("No hay cuentas configuradas — no se lanzaran workers")
    else:
        logger.info("MODO SECO activado: no se lanzan workers MT5")

    set_workers_ref(workers)

    # ---------------------------------------------------------------
    # Función reutilizable para procesar mensajes (evento o fetch)
    # ---------------------------------------------------------------
    async def process_message(msg_or_event, is_fetched=False):
        """Procesa el mensaje recibido ya sea de un evento en tiempo real o mediante polling.
        is_fetched indica si el origen es una llamada a get_messages (True) o un evento (False).
        """
        try:
            # Si es un mensaje fetch, usamos .id y .message directamente; si es evento, usamos event.message
            if is_fetched:
                msg = msg_or_event
                chat_id = msg.chat_id
                text = msg.message
                msg_id = msg.id
            else:
                msg = msg_or_event.message
                chat_id = msg_or_event.chat_id
                text = msg.message
                msg_id = msg_or_event.id

            # Evitar procesar mensajes ya manejados
            if msg_id in PROCESSED_MESSAGES:
                return

            if api_state["stopped"]:
                logger.info(f"[STOP] Bot detenido — mensaje {msg_id} ignorado")
                return

            PROCESSED_MESSAGES.add(msg_id)

            logger.info(f"Mensaje recibido de chat_id: {chat_id} (esperado: {SIGNAL_CHANNEL})")
            logger.info(f"[MSJ] Mensaje ID:{msg_id} recibido en canal {SIGNAL_CHANNEL}: {text!r}")

            # Guardar mensaje en el archivo CSV
            await save_message_to_csv(msg_id, text)

            # Verificar que el chat_id coincide con el canal esperado
            if abs(chat_id) != int(SIGNAL_CHANNEL.lstrip('-')):
                logger.warning(f"Mensaje de chat incorrecto (ID: {chat_id}), ignorando")
                return

            logger.info(f"Mensaje recibido en canal {SIGNAL_CHANNEL}: {text!r}")

            if DRY_RUN:
                await client.send_message(CHANNEL_FORWARD_ENTITY, text, parse_mode='html')
                logger.info(f"Mensaje reenviado a {FORWARD_CHAT_ID} (modo seco)")
                return

            # 1️⃣ Parsear la señal
            from local_signal_parser import parse_signal
            parsed = parse_signal(text)
            if not parsed.get("is_signal", False):
                logger.info("El mensaje no es una señal válida → se ignora el parsing.")
                prefixed_text = f"""⚠️ *No detectado como señal*

{text}

---"""
                await client.send_message(CHANNEL_FORWARD_ENTITY, prefixed_text, parse_mode='html')
                logger.info(f"Mensaje con prefijo enviado a {FORWARD_CHAT_ID}")
                return

            # 2️⃣ Obtener parámetros y balance
            symbol = parsed.get("symbol")
            entry = parsed.get("entry")
            sl = parsed.get("sl")
            action = parsed.get("action")

            if not all([symbol, entry, sl, action]):
                logger.warning(f"Datos incompletos en señal: {parsed}")
                await client.send_message(CHANNEL_FORWARD_ENTITY, "Datos incompletos → señal ignorada")
                return

            # Resumen simple (sin lote, cada worker calcula el suyo)
            tp_list = parsed.get("tp", [])
            tp_str = " | ".join(f"TP{i+1}={t:.5f}" for i, t in enumerate(tp_list[:3])) if tp_list else "N/A"
            summary_msg = (
                f"📋 <b>RESUMEN DE OPERACIÓN</b>\n"
                f"  Señal: <b>{action} {symbol}</b>\n"
                f"  Entry: {entry:.5f}  SL: {sl:.5f}\n"
                f"  {tp_str}\n"
                + "─" * 40
            )
            logger.info(f"Resumen de operación:\n{summary_msg}")

            # Notificar al frontend
            tp_str = (
                " | ".join(f"{tp:.5f}" for tp in parsed.get("tp", [])[:3])
                if parsed.get("tp") else ""
            )
            notify_frontend("signal", {
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": action,
                "symbol": symbol,
                "entry": f"{entry:.5f}" if entry else "market",
                "sl": f"{sl:.5f}" if sl else "N/A",
                "tp": tp_str,
                "status": "pending",
                "_retry": {
                    "action": action, "symbol": symbol,
                    "entry": entry, "sl": sl,
                    "tp": parsed.get("tp", []),
                },
            })

            # 4️⃣ Enviar resumen y manejar confirmación
            if CONFIRM_TRADES:
                from api_server import account_states as _as
                _acc_paused = any(st.get("paused") for st in _as.values())
                if api_state["running"] and not _acc_paused:
                    buttons = [[Button.inline("[SUCCESS] Sí", b"confirm_yes"), Button.inline("❌ No", b"confirm_no")]]
                    sent_msg = await client.send_message(CHANNEL_FORWARD_ENTITY, summary_msg, parse_mode='html', buttons=buttons)
                    PENDING_CONFIRMATIONS[sent_msg.id] = parsed
                    logger.info(f"Mensaje de confirmación enviado (msg_id={sent_msg.id})")
                else:
                    motivo = "PAUSADO" if not api_state["running"] else "límite diario alcanzado"
                    await client.send_message(CHANNEL_FORWARD_ENTITY, summary_msg + f"\n⏸️ Bot {motivo}: no se ejecutará.", parse_mode='html')
                    logger.info(f"Bot {motivo} — resumen enviado sin confirmación")
                    notify_frontend("signal_result", {"status": "pending"})
                    return
            else:
                await client.send_message(CHANNEL_FORWARD_ENTITY, summary_msg, parse_mode='html')
                logger.info(f"Resumen enviado a {FORWARD_CHAT_ID}")

                if api_state["stopped"]:
                    logger.info("Bot STOP — orden NO ejecutada")
                    await client.send_message(CHANNEL_FORWARD_ENTITY, "⏹️ Bot DETENIDO: no se ejecutó.")
                    notify_frontend("signal_result", {"status": "pending"})
                    return

                if not api_state["running"]:
                    logger.info("Bot PAUSADO — señal recibida pero orden NO ejecutada")
                    await client.send_message(CHANNEL_FORWARD_ENTITY, "⏸️ Bot PAUSADO: señal recibida pero no se ejecutó.")
                    notify_frontend("signal_result", {"status": "pending"})
                    return

                logger.info(f"[DEBUG] DRY_RUN={DRY_RUN} workers={len(workers)}")
                if not DRY_RUN:
                    if not workers:
                        await client.send_message(CHANNEL_FORWARD_ENTITY, "⚠️ No hay workers MT5 disponibles")
                        notify_frontend("signal_result", {"status": "error"})
                        return

                    import urllib.request
                    import concurrent.futures

                    parsed_data = {
                        "action": action, "symbol": symbol,
                        "entry": entry, "sl": sl,
                        "tp": parsed.get("tp", []),
                    }

                    def send_to_worker(w):
                        try:
                            data = json.dumps({"parsed": parsed_data}).encode()
                            req = urllib.request.Request(
                                f"http://127.0.0.1:{w['port']}/execute",
                                data=data,
                                headers={"Content-Type": "application/json"},
                            )
                            resp = urllib.request.urlopen(req, timeout=15)
                            return json.loads(resp.read())
                        except Exception as e:
                            return {"success": False, "error": str(e)}

                    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                        futures = {executor.submit(send_to_worker, w): w for w in workers.values()}
                        msgs = []
                        for fut in concurrent.futures.as_completed(futures):
                            w = futures[fut]
                            result = fut.result()
                            if result.get("success"):
                                label = "pend." if result.get("pending") else "OK"
                                msgs.append(f"[SUCCESS] {w['name']}: {label}")
                            else:
                                msgs.append(f"❌ {w['name']}: {result.get('error', 'fallo')}")

                    await client.send_message(CHANNEL_FORWARD_ENTITY, f"Orden {action} {symbol} @ {entry}:\n" + "\n".join(msgs))
                    notify_frontend("signal_result", {"status": "executed"})
                else:
                    logger.info("[MODO SECO] No se ejecutó la orden en MT5")
                    await client.send_message(CHANNEL_FORWARD_ENTITY, "⚠️ MODO SECO: operación simulada (no se ejecutó)")
                    notify_frontend("signal_result", {"status": "executed"})

        except RPCError as e:
            logger.error(f"Error al reenviar mensaje: {e}")
        except Exception as exc:
            logger.exception(f"Excepción inesperada en process_message: {exc}")

    # ---------------------------------------------------------------
    # Handler para mensajes del canal de origen
    # ---------------------------------------------------------------
    @client.on(events.NewMessage(chats=CHANNEL_SRC_ENTITY))
    async def handler(event):
        await process_message(event, is_fetched=False)

    # ----------------------------
    # Handler para botones de confirmación (Sí/No)
    # ----------------------------
    @client.on(events.CallbackQuery(data=b"confirm_yes"))
    async def handle_confirm_yes(event):
        msg_id = event.message.id
        if msg_id not in PENDING_CONFIRMATIONS:
            return
        parsed = PENDING_CONFIRMATIONS[msg_id]
        del PENDING_CONFIRMATIONS[msg_id]

        action = parsed.get("action")
        symbol = parsed.get("symbol")
        entry = parsed.get("entry")

        if not api_state["running"]:
            logger.info("Bot PAUSADO — confirmación recibida pero orden NO ejecutada")
            await client.send_message(event.chat_id, "⏸️ Bot PAUSADO: operación no ejecutada.")
            return

        from api_server import account_states
        acc_paused = any(st.get("paused") for st in account_states.values())
        if acc_paused:
            logger.info("Cuenta PAUSADA por límite diario — orden NO ejecutada")
            await client.send_message(event.chat_id, "⏸️ Cuenta PAUSADA por límite diario: no se ejecutó.")
            return

        if not DRY_RUN:
            if not workers:
                await client.send_message(event.chat_id, "⚠️ No hay workers MT5 disponibles")
                notify_frontend("signal_result", {"status": "error"})
                return

            import urllib.request
            import concurrent.futures
            import json as _json

            parsed_data = {
                "action": action, "symbol": symbol,
                "entry": entry, "sl": parsed.get("sl"),
                "tp": parsed.get("tp", []),
            }

            def _send(w):
                try:
                    data = _json.dumps({"parsed": parsed_data}).encode()
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{w['port']}/execute",
                        data=data, headers={"Content-Type": "application/json"},
                    )
                    resp = urllib.request.urlopen(req, timeout=15)
                    return _json.loads(resp.read())
                except Exception as e:
                    return {"success": False, "error": str(e)}

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(_send, w): w for w in workers.values()}
                msgs = []
                for fut in concurrent.futures.as_completed(futures):
                    w = futures[fut]
                    result = fut.result()
                    if result.get("success"):
                        label = "pend." if result.get("pending") else "OK"
                        msgs.append(f"[SUCCESS] {w['name']}: {label}")
                    else:
                        msgs.append(f"❌ {w['name']}: {result.get('error', 'fallo')}")

            await client.send_message(event.chat_id, f"Orden {action} {symbol} @ {entry}:\n" + "\n".join(msgs))
            notify_frontend("signal_result", {"status": "executed"})
        else:
            logger.info("[MODO SECO] Confirmación simulada")
            await client.send_message(event.chat_id, "⚠️ MODO SECO: confirmación simulada")
            notify_frontend("signal_result", {"status": "executed"})

    @client.on(events.CallbackQuery(data=b"confirm_no"))
    async def handle_confirm_no(event):
        msg_id = event.message.id
        if msg_id not in PENDING_CONFIRMATIONS:
            return
        del PENDING_CONFIRMATIONS[msg_id]
        logger.info(f"❌ Confirmación denegada para msg_id {msg_id}")
        await client.send_message(event.chat_id, "⚠️ Operación cancelada por el usuario")

    # ---------------------------------------------------------------
    # Handler para comandos de control (/help, /status, ...)
    # ---------------------------------------------------------------
    if CONTROL_CHAT_ID and CHANNEL_CONTROL_ENTITY:
        logger.info(f"Handler de comandos registrado para chat {CONTROL_CHAT_ID}")
        @client.on(events.NewMessage(chats=CHANNEL_CONTROL_ENTITY))
        async def control_handler(event):
            text = event.message.text.strip()
            if not text.startswith("/"):
                return
            from commands import COMMANDS
            parts = text.split()
            cmd = parts[0].lower()
            args = " ".join(parts[1:]) if len(parts) > 1 else ""
            handler = COMMANDS.get(cmd)
            if handler:
                logger.info(f"Comando recibido: {cmd} de {event.chat_id} args={args!r}")
                await handler(client, event.chat_id, args)
            else:
                await client.send_message(event.chat_id, f"❌ Comando desconocido: {cmd}\n\nUsa /help para ver los disponibles.")

    # ---------------------------------------------------------------
    # Función de reconexión compartida
    # ---------------------------------------------------------------
    async def reconnect_client():
        """Reconecta el cliente Telethon y re-resuelve entidades."""
        global CHANNEL_SRC_ENTITY, CHANNEL_FORWARD_ENTITY, CHANNEL_CONTROL_ENTITY
        try:
            if client.is_connected():
                await client.disconnect()
            await client.connect()
            await client.start(phone=TELEGRAM_PHONE)
            CHANNEL_SRC_ENTITY = await client.get_input_entity(SIGNAL_CHANNEL)
            CHANNEL_FORWARD_ENTITY = await client.get_input_entity(FORWARD_CHAT_ID)
            if CONTROL_CHAT_ID and CONTROL_CHAT_ID.lstrip("-").isdigit():
                CHANNEL_CONTROL_ENTITY = abs(int(CONTROL_CHAT_ID))
            elif CONTROL_CHAT_ID:
                CHANNEL_CONTROL_ENTITY = await client.get_input_entity(CONTROL_CHAT_ID)
            logger.info("[RECONNECTED] Reconexión exitosa")
            return True
        except Exception as e:
            logger.error(f"Falló la reconexión: {e}")
            return False

    # ---------------------------------------------------------------
    # Tarea de polling periódico para detectar mensajes perdidos
    # ---------------------------------------------------------------
    async def poll_missing_messages():
        """Cada POLLING_INTERVAL segundos revisa el canal en busca de mensajes no procesados.
        Si el cliente está desconectado, espera (la reconexión la maneja el bucle principal).
        """
        global last_processed_id, FIRST_POLL_DONE, CHANNEL_SRC_ENTITY
        interval = POLLING_INTERVAL
        limit = MESSAGE_LIMIT
        logger.info(f"Iniciando polling cada {interval}s, limit {limit}")
        last_all_clear_log = 0
        consecutive_failures = 0

        while True:
            try:
                logger.debug(f"[Polling] Ciclo cada {interval}s (limit={limit})")

                if not client.is_connected():
                    logger.warning("[Polling] Cliente desconectado, esperando reconexión del bucle principal...")
                    consecutive_failures += 1
                    backoff = min(5 * (2 ** (consecutive_failures - 1)), 120)
                    await asyncio.sleep(backoff)
                    continue

                msgs = await client.get_messages(CHANNEL_SRC_ENTITY, limit=limit)

                if msgs:
                    csv_ids = get_all_processed_ids()
                    missing_msgs = [msg for msg in msgs if msg.id not in csv_ids]

                    if not FIRST_POLL_DONE:
                        FIRST_POLL_DONE = True
                        logger.info("Primer ciclo: registrando historial sin procesar.")
                        for m in msgs:
                            await save_message_to_csv(m.id, m.message)
                            PROCESSED_MESSAGES.add(m.id)
                            if m.id > last_processed_id:
                                last_processed_id = m.id
                        save_last_processed_id(last_processed_id)
                    else:
                        if missing_msgs:
                            logger.info(f"[Polling] {len(missing_msgs)} mensajes faltantes. Procesando.")
                            for m in sorted(missing_msgs, key=lambda x: x.id):
                                if m.id not in PROCESSED_MESSAGES:
                                    await process_message(m, is_fetched=True)
                                    PROCESSED_MESSAGES.add(m.id)
                                    if m.id > last_processed_id:
                                        last_processed_id = m.id
                                        save_last_processed_id(last_processed_id)
                        else:
                            now = time.time()
                            if now - last_all_clear_log >= 300:
                                logger.info("Todo en orden, seguimos escuchando...")
                                last_all_clear_log = now

                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                backoff = min(5 * (2 ** (consecutive_failures - 1)), 120)
                logger.error(f"[Polling] Error ({consecutive_failures}): {e}. Reintento en {backoff}s")
                await asyncio.sleep(backoff)
                continue

            await asyncio.sleep(interval)

    # Iniciar polling en background
    asyncio.create_task(poll_missing_messages())

    # ---------------------------------------------------------------
    # Tarea de actualización periódica de estado de cuenta para el frontend
    # ---------------------------------------------------------------
    async def update_account_status():
        from api_server import retry_queue, account_states, test_message_queue
        import urllib.request

        while True:
            try:
                # Procesar reintentos pendientes
                while retry_queue:
                    parsed = retry_queue.pop(0)
                    parsed_data = {
                        "action": parsed.get("action"), "symbol": parsed.get("symbol"),
                        "entry": parsed.get("entry"), "sl": parsed.get("sl"),
                        "tp": parsed.get("tp", []),
                    }
                    for w in workers.values():
                        try:
                            data = json.dumps({"parsed": parsed_data}).encode()
                            req = urllib.request.Request(
                                f"http://127.0.0.1:{w['port']}/execute",
                                data=data,
                                headers={"Content-Type": "application/json"},
                            )
                            resp = urllib.request.urlopen(req, timeout=15)
                            result = json.loads(resp.read())
                            if result.get("success"):
                                label = "pend." if result.get("pending") else "OK"
                                logger.info(f"[RETRY] {w['name']}: {label}")
                                try:
                                    await client.send_message(CHANNEL_FORWARD_ENTITY, f"[RETRY] {w['name']}: {parsed_data['action']} {parsed_data['symbol']} → {label}")
                                except:
                                    pass
                            else:
                                logger.warning(f"[RETRY] {w['name']}: {result.get('error', 'fallo')}")
                                try:
                                    await client.send_message(CHANNEL_FORWARD_ENTITY, f"❌ [RETRY] {w['name']}: {result.get('error', 'fallo')}")
                                except:
                                    pass
                        except Exception as e:
                            logger.warning(f"Retry a {w['name']} fallido: {e}")

                # Procesar test de mensajes
                while test_message_queue:
                    chat_id = test_message_queue.pop(0)
                    try:
                        from telethon.tl.types import PeerChannel, PeerChat
                        target = int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id
                        entity = PeerChannel(target) if isinstance(target, int) and target < 0 else target
                        await client.send_message(entity, "🧪 Mensaje de prueba de TelBot v2.24 — ¡el chat funciona!")
                        logger.info(f"Test forward enviado a {target}")
                    except Exception as e:
                        logger.warning(f"Test forward fallido para {chat_id}: {e}")

                # Sondear estado de cada worker
                accs = []
                all_positions = []
                all_orders = []

                today = datetime.now().strftime("%Y-%m-%d")
                for w in list(workers.values()):
                    w_name = w["name"]
                    if w_name not in account_states or account_states[w_name].get("date") != today:
                        account_states[w_name] = {
                            "daily_pnl": 0.0, "paused": False, "date": today,
                            "profit_limit": 0, "loss_limit": 0,
                        }

                    try:
                        req = urllib.request.Request(f"http://127.0.0.1:{w['port']}/status")
                        resp = urllib.request.urlopen(req, timeout=5)
                        status = json.loads(resp.read())

                        account_states[w_name]["daily_pnl"] = status.get("daily_pnl", 0)
                        account_states[w_name]["paused"] = status.get("paused", False)
                        account_states[w_name]["profit_limit"] = status.get("profit_limit", 0)
                        account_states[w_name]["loss_limit"] = status.get("loss_limit", 0)

                        for p in status.get("positions", []):
                            p["server"] = w_name
                            all_positions.append(p)
                        for o in status.get("pending_orders", []):
                            o["server"] = w_name
                            all_orders.append(o)

                        acc = status.get("account", {})
                        acc["server"] = w_name
                        accs.append(acc)

                        logger.info(f"[STATUS] {w_name}: pos={len(status.get('positions',[]))} ord={len(status.get('pending_orders',[]))} pnl={status.get('daily_pnl',0):.2f}")
                    except Exception as e:
                        logger.warning(f"Error sondeando worker {w_name}: {e}")

                notify_frontend("status", {
                    "account": accs[0] if accs else {},
                    "accounts": accs,
                    "positions": all_positions,
                    "pending_orders": all_orders,
                    "running": api_state["running"],
                })
            except Exception as e:
                logger.warning(f"Error en update_account_status: {e}")
            await asyncio.sleep(5)

    asyncio.create_task(update_account_status())

    logger.info(f"Escuchando canal {SIGNAL_CHANNEL} y reenviando a {FORWARD_CHAT_ID}")
    logger.info("=== INICIO DEL MODULO DE RECONEXIÓN ===")

    # Bucle principal: mantener el cliente vivo
    retry_delay = 5
    connection_attempt = 0

    while True:
        try:
            await client.run_until_disconnected()
            logger.info("Cliente desconectado intencionalmente, reconectando...")
        except Exception as e:
            connection_attempt += 1
            backoff = min(retry_delay * (2 ** (connection_attempt - 1)), 300)
            logger.error(f"[RECONEXION] Intento {connection_attempt}: {e}. Espera {backoff}s")
            await asyncio.sleep(backoff)

        if await reconnect_client():
            connection_attempt = 0


if __name__ == "__main__":
    asyncio.run(main())