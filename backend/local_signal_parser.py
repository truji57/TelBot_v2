"""local_signal_parser.py
Parseador sencillo de señales de trading a partir de texto plano.

Formatos soportados:

1️⃣ Estructurado (con etiquetas):
   🟢 BUY XAUUSD
     Entrada: 4708.24
     TP1: 4724.03
     TP2: 4739.60
     SL: 4695.58

2️⃣ Libre (rango de precios + TP en líneas separadas):
   SELL XAUUSD 4696-4700

   SL 4704

   TP 4693
   TP 4691
   TP 4685

Para formato libre con rango:
  - SELL → toma el valor más PEQUEÑO del rango como entry (vende más arriba)
  - BUY  → toma el valor más GRANDE del rango como entry (compra más arriba)
"""

import re
import logging

logger = logging.getLogger(__name__)


def _parse_range(range_str: str, action: str) -> float | None:
    """
    Parsea un rango como "4696-4700" y devuelve un solo valor según la acción.
    - SELL → menor valor (entry de venta)
    - BUY  → mayor valor (entry de compra)
    Si no es un rango, devuelve el número directamente.
    """
    if '-' in range_str:
        parts = range_str.split('-')
        try:
            nums = [float(p.strip()) for p in parts if p.strip()]
        except ValueError:
            return None
        if len(nums) >= 2:
            if action == "SELL":
                return min(nums)      # vender en el menor (más arriba para shorts)
            else:
                return max(nums)      # comprar en el mayor (más arriba para longs)
        elif nums:
            return nums[0]
    else:
        try:
            return float(range_str.strip())
        except ValueError:
            return None
    return None


def _extract_action_symbol(line: str):
    """Extrae acción (BUY/SELL) y símbolo de una línea.
    Ej: "SELL XAUUSD 4696-4700" → ("SELL", "XAUUSD")
    """
    m = re.match(r"^🟢?\s*(BUY|SELL)\s+([A-Z0-9]+)", line.strip(), re.I)
    if m:
        return m.group(1).upper(), m.group(2).upper()
    return None, None


def _parse_structured(text: str) -> dict | None:
    """Parsea el formato estructurado con etiquetas.
    Este parser reconoce tanto las etiquetas en inglés (Entry) como en español (Entrada).
    Además, la entrada puede ser un número simple o un rango "min-max"; en caso de rango
    se aplicará la lógica de _parse_range (menor para SELL, mayor para BUY).
    """
    """Parsea el formato con etiquetas Entrada:, TP1:, SL: etc."""
    lines = text.splitlines()
    data = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Acción + símbolo
        action, symbol = _extract_action_symbol(line)
        if action:
            data["action"] = action
            data["symbol"] = symbol
            continue
        # Entrada (soporta tanto "Entry" como "Entrada" y rangos)
        m = re.match(r"^(Entrada|Entry)\s*[:—-]\s*([0-9.]+(?:-[0-9.]+)?)", line, re.I)
        if m:
            entry_str = m.group(2)
            data["entry"] = _parse_range(entry_str, data.get("action", ""))
            continue
        # SL
        m = re.match(r"^SL\s*:?\s*([0-9.]+)", line, re.I)
        if m:
            data["sl"] = float(m.group(1))
            continue
        # TP (puede ser TP1, TP2, TP3, o solo TP con número)
        m = re.match(r"^TP(\d*)\s*:?\s*([0-9.]+)", line, re.I)
        if m:
            data.setdefault("tp", []).append(float(m.group(2)))
            continue

    if {"action", "symbol", "sl"}.issubset(data) and data.get("tp"):
        return {
            "is_signal": True,
            "action": data["action"],
            "symbol": data["symbol"],
            "entry": data.get("entry"),
            "sl": data["sl"],
            "tp": data["tp"][:3],
            "lot_size": None,
            "notes": "",
        }
    return None


def _parse_free(text: str) -> dict | None:
    """
    Parsea el formato libre:
        SELL XAUUSD 4696-4700

        SL 4704

        TP 4693
        TP 4691
        TP 4685
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    action = None
    symbol = None
    entry = None
    sl = None
    tp = []

    for line in lines:
        # Detectar acción + símbolo + posible rango de entry
        # Ej: "SELL XAUUSD 4696-4700" o "BUY XAUUSD 4708.24"
        m = re.match(r"^(BUY|SELL)\s+([A-Z0-9]+)\s*(.*)", line, re.I)
        if m:
            action = m.group(1).upper()
            symbol = m.group(2).upper()
            remainder = m.group(3).strip()
            if remainder:
                entry = _parse_range(remainder, action)
            continue

        # Detectar SL (con o sin dos puntos)
        # Ej: "SL 4704" o "SL: 4704"
        m = re.match(r"^SL\s*:?\s*([0-9.]+)", line, re.I)
        if m:
            sl = float(m.group(1))
            continue

        # Detectar TP (puede haber varios)
        # Ej: "TP 4693" o "TP1: 4693"
        m = re.match(r"^TP(\d*)\s*:?\s*([0-9.]+)", line, re.I)
        if m:
            tp.append(float(m.group(2)))
            continue

    if action and symbol and sl is not None and tp:
        return {
            "is_signal": True,
            "action": action,
            "symbol": symbol,
            "entry": entry,
            "sl": sl,
            "tp": tp[:3],
            "lot_size": None,
            "notes": "",
        }
    return None


def _parse_summary(text: str) -> dict | None:
    """
    Parsea el formato de resumen:
    📋 RESUMEN DE OPERACIÓN
      Señal: SELL BTCUSD
      Tipo:  STOP @ 78300.00000
      SL:    78482.00000
      TP1=78124.00000 | TP2=77943.00000 | TP3=77766.00000
      Lots:  0.40
    """
    lines = text.strip().split('\n')
    data = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Señal: SELL BTCUSD
        if line.startswith("Señal:"):
            parts = line.split(":")[1].strip().split()
            if len(parts) >= 2:
                data["action"] = parts[0].upper()
                data["symbol"] = parts[1].upper()
            continue

        # Tipo: STOP @ 78300.00000
        if line.startswith("Tipo:"):
            parts = line.split("@")
            if len(parts) >= 2:
                entry_str = parts[1].strip()
                if entry_str != "0":  # Ignorar si es "0" (market)
                    data["entry"] = float(entry_str)
            continue

        # SL: 78482.00000
        if line.startswith("SL:"):
            sl_str = line.split(":")[1].strip()
            data["sl"] = float(sl_str)
            continue

        # TP1=78124.00000 | TP2=77943.00000 | TP3=77766.00000
        if "=" in line and line.strip().startswith("TP"):
            parts = line.split("|")
            for part in parts:
                part = part.strip()
                if "=" in part:
                    tp_label, tp_value = part.split("=")
                    if tp_value.replace('.', '', 1).isdigit():
                        data.setdefault("tp", []).append(float(tp_value))
            continue

        # Lots: 0.40
        if line.startswith("Lots:"):
            lot_str = line.split(":")[1].strip()
            data["lot_size"] = float(lot_str)
            continue

    # Validar campos mínimos
    if {"action", "symbol", "sl"}.issubset(data) and data.get("tp"):
        return {
            "is_signal": True,
            "action": data["action"],
            "symbol": data["symbol"],
            "entry": data.get("entry"),
            "sl": data["sl"],
            "tp": data["tp"][:3],  # Máximo 3 TPs
            "lot_size": data.get("lot_size"),
            "notes": "",
        }
    return None


def parse_signal(message: str) -> dict:
    """
    Parsea *message* intentando primero el formato estructurado,
    luego el formato libre.

    Si ninguno coincide, devuelve {"is_signal": False}.
    """
    # Limpiar emojis innecesarios
    clean = message.replace("🟢", "").replace("🔴", "").strip()

    # 1️⃣ Intentar formato estructurado (Entrada:, TP1:, SL:)
    result = _parse_structured(clean)
    if result and result.get('entry') is not None:
        logger.info("Señal parseada con formato ESTRUCTURADO.")
        return result
    # Si el estructurado no tenía entry, intentar formato libre
    result = _parse_free(clean)
    if result:
        logger.info("Señal parseada con formato LIBRE.")
        logger.info(f"  entry={result['entry']}, sl={result['sl']}, tp={result['tp']}")
        return result

    # Si el libre no tuvo éxito, intentar formato de resumen
    result = _parse_summary(clean)
    if result:
        logger.info("Señal parseada con formato RESUMEN.")
        return result

    # Ninguno coincidió
    logger.warning("Formato de señal no reconocido.")
    return {"is_signal": False}