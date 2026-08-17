"""commands.py — Comandos de control para TelBot (/help, /status, /closeall, ...)"""

import logging

from config import DRY_RUN

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "📋 *Comandos disponibles:*\n\n"
    "/help — Muestra esta ayuda\n"
    "/ping — Comprueba que el bot responde\n"
    "/status — Estado de la cuenta, balance, posiciones y órdenes\n"
    "/positions — Lista detallada de posiciones abiertas\n"
    "/orders — Lista detallada de órdenes pendientes\n"
    "/closeall — Cierra todas las posiciones abiertas\n"
    "/close SÍMBOLO — Cierra una posición concreta (ej: /close XAUUSD)\n"
    "/deleteall — Elimina todas las órdenes pendientes\n"
    "/be — Mueve el SL de todas las posiciones a breakeven\n"
    "/setsl SÍMBOLO PRECIO — Cambia el SL de una posición (ej: /setsl XAUUSD 4700)\n"
    "/settp SÍMBOLO PRECIO — Cambia el TP de una posición (ej: /settp XAUUSD 4800)"
)


async def cmd_help(client, chat_id: int, args: str = ""):
    await client.send_message(chat_id, HELP_TEXT, parse_mode="markdown")
    logger.info(f"Comando /help enviado a {chat_id}")


async def cmd_ping(client, chat_id: int, args: str = ""):
    await client.send_message(chat_id, "🏓 Pong! El bot responde correctamente.")
    logger.info(f"Comando /ping para {chat_id}")


async def cmd_status(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco activo* — no hay conexión a MT5.\n\n`/status` no está disponible en este modo.", parse_mode="markdown")
        return

    try:
        from mt5_connector import get_account_status
        status = get_account_status()
    except Exception as e:
        logger.exception(f"Error en /status: {e}")
        await client.send_message(chat_id, f"❌ Error al obtener estado: {e}")
        return

    if "error" in status:
        await client.send_message(chat_id, f"❌ {status['error']}")
        return

    msg = (
        f"📊 *Estado de la cuenta*\n\n"
        f"👤 Login: `{status['login']}`\n"
        f"🏦 Servidor: `{status['server']}`\n"
        f"💰 Balance: `{status['balance']:.2f} {status['currency']}`\n"
        f"📈 Equity: `{status['equity']:.2f} {status['currency']}`\n"
        f"📉 Margen: `{status['margin']:.2f} {status['currency']}`\n"
        f"🆓 Margen libre: `{status['margin_free']:.2f} {status['currency']}`\n"
        f"📊 P&L flotante: `{status['profit']:+.2f} {status['currency']}`\n\n"
        f"📌 Posiciones abiertas: {status['positions']}\n"
        f"⏳ Órdenes pendientes: {status['pending_orders']}"
    )
    await client.send_message(chat_id, msg, parse_mode="markdown")
    logger.info(f"Comando /status ejecutado para {chat_id}")


async def cmd_positions(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no hay conexión a MT5.", parse_mode="markdown")
        return

    try:
        from mt5_connector import get_open_positions
        positions = get_open_positions()
    except Exception as e:
        logger.exception(f"Error en /positions: {e}")
        await client.send_message(chat_id, f"❌ Error al obtener posiciones: {e}")
        return

    if not positions:
        await client.send_message(chat_id, "No hay posiciones abiertas.")
        return

    total_profit = 0
    lines = ["📌 *Posiciones abiertas:*\n"]
    for i, p in enumerate(positions, 1):
        profit = p["profit"]
        total_profit += profit
        profit_str = f"`{profit:+.2f}`" if profit >= 0 else f"`{profit:.2f}`"
        lines.append(
            f"{i}. `{p['symbol']}` {p['type']} vol={p['volume']}\n"
            f"   Entrada: `{p['entry']}`  SL: `{p['sl'] or '—'}`  TP: `{p['tp'] or '—'}`\n"
            f"   Precio: `{p['current_price']}`  P&L: {profit_str}\n"
        )

    lines.append(f"\n📊 P&L total: `{total_profit:+.2f}`")
    msg = "\n".join(lines)
    await client.send_message(chat_id, msg, parse_mode="markdown")
    logger.info(f"Comando /positions: {len(positions)} posición(es)")


async def cmd_orders(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no hay conexión a MT5.", parse_mode="markdown")
        return

    try:
        from mt5_connector import get_pending_orders
        orders = get_pending_orders()
    except Exception as e:
        logger.exception(f"Error en /orders: {e}")
        await client.send_message(chat_id, f"❌ Error al obtener órdenes: {e}")
        return

    if not orders:
        await client.send_message(chat_id, "No hay órdenes pendientes.")
        return

    lines = ["⏳ *Órdenes pendientes:*\n"]
    for i, o in enumerate(orders, 1):
        lines.append(
            f"{i}. `{o['symbol']}` {o['type']} vol={o['volume']}\n"
            f"   Precio: `{o['price']}`  SL: `{o['sl'] or '—'}`  TP: `{o['tp'] or '—'}`\n"
        )

    msg = "\n".join(lines)
    await client.send_message(chat_id, msg, parse_mode="markdown")
    logger.info(f"Comando /orders: {len(orders)} orden(es)")


async def cmd_closeall(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no se ejecutaron órdenes reales.", parse_mode="markdown")
        return

    try:
        from mt5_connector import close_all_positions
        results = close_all_positions()
    except Exception as e:
        logger.exception(f"Error en /closeall: {e}")
        await client.send_message(chat_id, f"❌ Error al cerrar posiciones: {e}")
        return

    success_count = sum(1 for r in results if r.get("success"))
    fail_count = sum(1 for r in results if not r.get("success"))

    if not results:
        await client.send_message(chat_id, "No hay posiciones abiertas.")
        return

    if "message" in results[0] and not results[0].get("success"):
        await client.send_message(chat_id, results[0]["message"])
        return

    msg = f"✅ Cerradas {success_count} posición(es)"
    if fail_count:
        msg += f"\n⚠️ {fail_count} fallo(s)"
    await client.send_message(chat_id, msg)
    logger.info(f"Comando /closeall: {success_count} cerradas, {fail_count} fallos")


async def cmd_close(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no se ejecutaron órdenes reales.", parse_mode="markdown")
        return

    symbol = args.strip().upper()
    if not symbol:
        await client.send_message(chat_id, "❌ Uso: `/close SÍMBOLO`\nEjemplo: `/close XAUUSD`", parse_mode="markdown")
        return

    try:
        from mt5_connector import close_position_by_symbol
        result = close_position_by_symbol(symbol)
    except Exception as e:
        logger.exception(f"Error en /close {symbol}: {e}")
        await client.send_message(chat_id, f"❌ Error al cerrar {symbol}: {e}")
        return

    if result.get("success"):
        await client.send_message(chat_id, f"✅ Posición cerrada: `{symbol}`", parse_mode="markdown")
        logger.info(f"Comando /close {symbol}: OK")
    else:
        await client.send_message(chat_id, f"❌ {result.get('message', result.get('error', 'Error desconocido'))}")
        logger.info(f"Comando /close {symbol}: fallo — {result}")


async def cmd_deleteall(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no se ejecutaron órdenes reales.", parse_mode="markdown")
        return

    try:
        from mt5_connector import delete_all_pending_orders
        results = delete_all_pending_orders()
    except Exception as e:
        logger.exception(f"Error en /deleteall: {e}")
        await client.send_message(chat_id, f"❌ Error al eliminar órdenes: {e}")
        return

    success_count = sum(1 for r in results if r.get("success"))
    fail_count = sum(1 for r in results if not r.get("success"))

    if not results:
        await client.send_message(chat_id, "No hay órdenes pendientes.")
        return

    if "message" in results[0] and not results[0].get("success"):
        await client.send_message(chat_id, results[0]["message"])
        return

    msg = f"✅ Eliminadas {success_count} orden(es) pendiente(s)"
    if fail_count:
        msg += f"\n⚠️ {fail_count} fallo(s)"
    await client.send_message(chat_id, msg)
    logger.info(f"Comando /deleteall: {success_count} eliminadas, {fail_count} fallos")


async def cmd_be(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no se ejecutaron órdenes reales.", parse_mode="markdown")
        return

    try:
        from mt5_connector import set_breakeven_all
        results = set_breakeven_all()
    except Exception as e:
        logger.exception(f"Error en /be: {e}")
        await client.send_message(chat_id, f"❌ Error al mover SL a breakeven: {e}")
        return

    success_count = sum(1 for r in results if r.get("success"))
    fail_count = sum(1 for r in results if not r.get("success"))

    if not results:
        await client.send_message(chat_id, "No hay posiciones abiertas.")
        return

    if "message" in results[0] and not results[0].get("success"):
        await client.send_message(chat_id, results[0]["message"])
        return

    msg = f"✅ SL movido a breakeven en {success_count} posición(es)"
    if fail_count:
        msg += f"\n⚠️ {fail_count} fallo(s)"
    await client.send_message(chat_id, msg)
    logger.info(f"Comando /be: {success_count} ok, {fail_count} fallos")


async def cmd_setsl(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no se ejecutaron órdenes reales.", parse_mode="markdown")
        return

    parts = args.strip().split()
    if len(parts) < 2:
        await client.send_message(chat_id, "❌ Uso: `/setsl SÍMBOLO PRECIO`\nEjemplo: `/setsl XAUUSD 4700`", parse_mode="markdown")
        return

    symbol = parts[0].upper()
    try:
        sl_price = float(parts[1])
    except ValueError:
        await client.send_message(chat_id, f"❌ Precio inválido: `{parts[1]}`", parse_mode="markdown")
        return

    try:
        from mt5_connector import modify_position_sl
        result = modify_position_sl(symbol, sl_price)
    except Exception as e:
        logger.exception(f"Error en /setsl {symbol}: {e}")
        await client.send_message(chat_id, f"❌ Error al modificar SL de {symbol}: {e}")
        return

    if result.get("success"):
        await client.send_message(chat_id, f"✅ SL de `{symbol}` movido a `{sl_price}`", parse_mode="markdown")
        logger.info(f"Comando /setsl {symbol} {sl_price}: OK")
    else:
        await client.send_message(chat_id, f"❌ {result.get('message', result.get('error', 'Error desconocido'))}")
        logger.info(f"Comando /setsl {symbol}: fallo — {result}")


async def cmd_settp(client, chat_id: int, args: str = ""):
    if DRY_RUN:
        await client.send_message(chat_id, "⚠️ *Modo seco* — no se ejecutaron órdenes reales.", parse_mode="markdown")
        return

    parts = args.strip().split()
    if len(parts) < 2:
        await client.send_message(chat_id, "❌ Uso: `/settp SÍMBOLO PRECIO`\nEjemplo: `/settp XAUUSD 4800`", parse_mode="markdown")
        return

    symbol = parts[0].upper()
    try:
        tp_price = float(parts[1])
    except ValueError:
        await client.send_message(chat_id, f"❌ Precio inválido: `{parts[1]}`", parse_mode="markdown")
        return

    try:
        from mt5_connector import modify_position_tp
        result = modify_position_tp(symbol, tp_price)
    except Exception as e:
        logger.exception(f"Error en /settp {symbol}: {e}")
        await client.send_message(chat_id, f"❌ Error al modificar TP de {symbol}: {e}")
        return

    if result.get("success"):
        await client.send_message(chat_id, f"✅ TP de `{symbol}` movido a `{tp_price}`", parse_mode="markdown")
        logger.info(f"Comando /settp {symbol} {tp_price}: OK")
    else:
        await client.send_message(chat_id, f"❌ {result.get('message', result.get('error', 'Error desconocido'))}")
        logger.info(f"Comando /settp {symbol}: fallo — {result}")


COMMANDS = {
    "/help": cmd_help,
    "/ping": cmd_ping,
    "/status": cmd_status,
    "/positions": cmd_positions,
    "/orders": cmd_orders,
    "/closeall": cmd_closeall,
    "/close": cmd_close,
    "/deleteall": cmd_deleteall,
    "/be": cmd_be,
    "/setsl": cmd_setsl,
    "/settp": cmd_settp,
}
