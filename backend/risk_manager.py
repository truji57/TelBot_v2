"""risk_manager.py
Módulo que calcula el tamaño de lote y determina el tipo de orden (limit/stop)
según los parámetros de la señal y la configuración de riesgo.

Fórmula de cálculo de lotes (del manual del proyecto):
    riesgo_usd = balance * (RISK_PERCENT / 100)
    sl_ticks    = |entry - sl| / tick_size
    loss_per_lot = sl_ticks * tick_value
    lots        = riesgo_usd / loss_per_lot
    lots        = floor(lots / lot_step) * lot_step   ← conservador
"""

import math
import logging
import MetaTrader5 as mt5
from config import RISK_PERCENT, MAX_LOT_SIZE, MIN_LOT_SIZE, DEFAULT_MAGIC

logger = logging.getLogger(__name__)

EPS = 1e-10  # constante pequeña para comparaciones float


def calcular_lotes(symbol: str, balance: float, entry_price: float, sl_price: float) -> float:
    """
    Calcula el tamaño de lote basándose en el porcentaje de riesgo.

    Parámetros:
        symbol:      símbolo MT5 (ej: 'XAUUSD')
        balance:     balance de la cuenta en divisa de la cuenta
        entry_price: precio de entrada
        sl_price:    precio de stop-loss

    Retorna:
        Tamaño de lote redondeado al step permitido.
    """
    if not sl_price or sl_price == 0:
        raise ValueError("SL inválido")

    riesgo_usd = balance * (RISK_PERCENT / 100.0)

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        raise RuntimeError(f"No se encontró info del símbolo: {symbol}")

    sl_dist = abs(entry_price - sl_price)
    if sl_dist <= EPS:
        raise ValueError("SL demasiado cerca del entry")

    tick_size = symbol_info.trade_tick_size
    tick_value = symbol_info.trade_tick_value

    # Corrección especial para brokers que reportan contract_size erróneamente
    # En MetaTrader 5, algunos brokers reportan contract_size incorrecto para XAUUSD
    # El valor correcto es 100 (100 onzas), pero algunos brokers reportan 100000
    contract_size = getattr(symbol_info, "trade_contract_size", None)
    if contract_size is not None:
        # Para XAUUSD, forzamos el contract_size correcto si el reportado es muy alto
        if symbol == "XAUUSD" and contract_size >= 1000:
            logger.warning(f"Contract_size incorrecto para {symbol} ({contract_size}), usando valor estándar 100")
            contract_size = 100.0

        expected_tick_value = contract_size * tick_size
        # Si el tick_value reportado es menos del 30% del esperado, usamos el cálculo esperado
        if tick_value is None or tick_value <= 0 or (expected_tick_value > 0 and tick_value < expected_tick_value * 0.3):
            logger.warning(f"tick_value para {symbol} parece bajo ({tick_value}); usando cálculo basado en contract_size={contract_size}: {expected_tick_value}")
            tick_value = expected_tick_value

    if tick_size is None or tick_size == 0 or tick_value is None:
        raise RuntimeError(f"Datos de tick inválidos para {symbol}")

    sl_ticks = sl_dist / tick_size
    loss_per_lot = sl_ticks * tick_value

    if loss_per_lot <= 0:
        raise RuntimeError(f"loss_per_lot <= 0 para {symbol}")

    lots = riesgo_usd / loss_per_lot

    # Definir paso de lote (volume_step) y redondear conservadoramente
    lot_step = symbol_info.volume_step or 0.01
    # Redondear hacia abajo sin factor de seguridad (para usar todo el riesgo permitido)
    raw_lots = math.floor(lots / lot_step) * lot_step
    lots_rounded = max(
        symbol_info.volume_min or MIN_LOT_SIZE,
        raw_lots
    )

    # Respetar también el máximo
    lots_rounded = min(lots_rounded, MAX_LOT_SIZE)

    # Depuración detallada
    logger.info(
        f"[DEBUG] risk_usd={riesgo_usd:.2f} | loss_per_lot={loss_per_lot:.4f} | "
        f"lots (raw)={lots:.4f} | lots_rounded={lots_rounded:.4f} | "
        f"volume_step={lot_step:.4f} | volume_min={symbol_info.volume_min or MIN_LOT_SIZE:.4f} | "
        f"contract_size={contract_size} | tick_size={tick_size} | tick_value={tick_value}"
    )

    # Evitar lotes menores al mínimo permitido
    if lots_rounded < MIN_LOT_SIZE:
        logger.error(
            f"Lot calculado ({lots_rounded:.4f}) está por debajo del volume_min "
            f"({MIN_LOT_SIZE:.4f}). Considera bajar RISK_PERCENT."
        )
        raise RuntimeError("Lot demasiado pequeño para el broker; considera usar un RISK_PERCENT menor.")

    result = round(lots_rounded, 2)

    logger.info(
        f"Lote calculado → {result} | balance={balance:.2f} | "
        f"riesgo_usd={riesgo_usd:.2f} | sl_dist={sl_dist:.5f} | "
        f"tick_size={tick_size} | tick_value={tick_value} | "
        f"sl_ticks={sl_ticks:.2f} | loss_per_lot={loss_per_lot:.4f}"
    )
    return result


def determine_order_type(action: str, entry: float | None, symbol: str) -> str:
    """
    Determina si la orden debe ser LIMIT o STOP comparando el precio de entrada
    con el precio actual del mercado (bid/ask desde MT5).

    Regla:
      BUY  LIMIT → entry < precio actual  (comprar más barato)
      BUY  STOP  → entry > precio actual  (comprar más caro, breakout)
      SELL LIMIT → entry > precio actual  (vender más caro)
      SELL STOP  → entry < precio actual  (vender más barato, breakout)
    """
    action = action.upper()

    if entry is None:
        logger.info("Sin precio de entrada → MARKET")
        return "market"

    current_price = _get_current_price(symbol)

    if current_price is not None:
        if action == "BUY":
            if entry < current_price:
                order_type = "limit"
            elif entry > current_price:
                order_type = "stop"
            else:
                order_type = "market"
        elif action == "SELL":
            if entry > current_price:
                order_type = "limit"
            elif entry < current_price:
                order_type = "stop"
            else:
                order_type = "market"
        else:
            order_type = "limit"
        logger.info(f"Tipo de orden para {action} {symbol}: {order_type} "
                     f"(entry={entry}, current={current_price})")
        return order_type

    logger.info(f"Sin precio actual para {symbol} → se asume LIMIT (entry={entry})")
    return "limit"


def _get_current_price(symbol: str) -> float | None:
    """Obtiene el precio actual (mid-point) desde MT5."""
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            prices = [p for p in (tick.bid, tick.ask) if p and p > 0]
            if len(prices) >= 2:
                return sum(prices) / 2.0
            return prices[0] if prices else None
    except Exception:
        pass
    return None


def build_trade_summary(parsed: dict, lot: float, order_type: str) -> str:
    """
    Construye un mensaje de resumen legible para enviar al usuario
    antes de ejecutar la orden.
    """
    action = parsed.get("action", "N/A")
    symbol = parsed.get("symbol", "N/A")
    entry = parsed.get("entry")
    sl = parsed.get("sl")
    tp = parsed.get("tp", [])
    notes = parsed.get("notes", "")

    entry_str = f"{entry:.5f}" if entry is not None else "a mercado"
    sl_str = f"{sl:.5f}" if sl is not None else "N/A"

    if tp:
        tp_parts = []
        for i, t in enumerate(tp, 1):
            if isinstance(t, (int, float)):
                tp_parts.append(f"TP{i}={t:.5f}")
        tp_str = " | ".join(tp_parts)
    else:
        tp_str = "N/A"

    order_type_label = order_type.upper()

    lines = [
        "📋 <b>RESUMEN DE OPERACIÓN</b>",
        f"  Señal: <b>{action} {symbol}</b>",
        f"  Tipo:  <b>{order_type_label}</b> @ {entry_str}",
        f"  SL:    {sl_str}",
        f"  {tp_str}",
        f"  Lots:  <b>{lot:.2f}</b>",
    ]

    if notes:
        lines.append(f"  Notas: {notes}")

    lines.append("─" * 40)

    return "\n".join(lines)