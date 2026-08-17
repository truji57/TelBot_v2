# TelBot v2 — Bot de Trading con GUI

Versión renovada de TelBot con frontend web para gestionar todo desde el navegador.

```
TelBot v1  (terminal)          TelBot v2  (GUI)
┌─────────────────┐           ┌──────────────────────────────────┐
│ telegram_listener│           │ backend/telegram_listener.py     │
│       +          │           │         +                        │
│   config.py      │    →      │ backend/api_server.py (WS+HTTP)  │
│   mt5_connector  │           │         ↕                        │
│   risk_manager   │           │ frontend/ (React+Vite+TS)        │
│   ...            │           └──────────────────────────────────┘
│                  │
│ (sin interfaz)   │
└─────────────────┘
```

---

## Estructura del proyecto

```
Telbot_v2/
├── backend/                    ← Lógica del bot (Python)
│   ├── telegram_listener.py    ← Entry point + orquestador
│   ├── api_server.py           ← Servidor HTTP/WebSocket (NUEVO)
│   ├── config.py               ← Carga .env
│   ├── commands.py             ← Comandos /help, /status...
│   ├── local_signal_parser.py  ← Parser de señales
│   ├── mt5_connector.py        ← Conexión y envío a MT5
│   ├── risk_manager.py         ← Cálculo de lotes y riesgo
│   ├── updater.py              ← Auto-update
│   ├── config_panel.py         ← Panel .env legacy
│   └── symbols_map.yaml        ← Mapeo símbolos por broker
│
├── frontend/                   ← GUI web (React + Vite + TypeScript)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx            ← Entry point React
│       ├── App.tsx             ← Router (Dashboard / Settings)
│       ├── index.css           ← Tailwind + estilos base
│       ├── pages/
│       │   ├── Dashboard.tsx   ← Panel principal (RUN/PAUSA, señales, cuenta)
│       │   └── Settings.tsx    ← Configuración del .env
│       ├── components/         ← Componentes reutilizables (vacío, por crear)
│       └── hooks/              ← Hooks personalizados (vacío, por crear)
│
├── data/                       ← Datos runtime
│   ├── processed_messages.csv
│   └── last_processed_id.txt
├── logs/                       ← Logs
├── .env                        ← Configuración (NO subir)
├── .env.example                ← Plantilla
├── .gitignore
├── requirements.txt            ← Dependencias Python
├── start.bat                   ← Arranca Backend + Frontend
└── README.md                   ← Este archivo
```

---

## Stack tecnológico

| Capa     | Tecnología                     |
|----------|--------------------------------|
| Backend  | Python 3.10+, Telethon, MetaTrader5 |
| API      | HTTP built-in + polling interno (sin frameworks extra) |
| Frontend | React 18, TypeScript, Vite, TailwindCSS |
| Comunicación | REST (polling cada 2s) |

---

## Cómo arrancar

```bash
# Instalar dependencias frontend (primera vez)
cd frontend
npm install

# Arrancar todo
start.bat
```

- **API**: `http://localhost:8766`
- **GUI**: `http://localhost:5175`

---

## API endpoints

| Método | Ruta          | Descripción                      |
|--------|---------------|----------------------------------|
| GET    | `/api/status` | Estado del bot, cuenta y señales |
| POST   | `/api/start`  | Reanudar ejecución del bot       |
| POST   | `/api/stop`   | Pausar ejecución del bot         |
| GET    | `/api/config` | Leer configuración `.env`        |
| POST   | `/api/config` | Guardar configuración `.env`     |

---

## Funcionalidades

### ✅ Heredadas de v1 (completas)
- Escucha de canal Telegram en tiempo real
- Parser local de señales (3 formatos)
- Ejecución en MT5 (market, limit, stop)
- Gestión de riesgo (lotes, SL, TP)
- Comandos de control (`/help`, `/closeall`, `/be`, etc.)
- Random offset anti-group-trading
- Reintentos en errores transitorios (10015)
- RR_RATIO personalizado
- Panel `.env` legacy (config_panel.py)
- Auto-update manual (updater.py)

### 🚧 En desarrollo (v2 GUI)
- Panel Dashboard con señales en tiempo real
- Botones RUN / PAUSA
- Configuración `.env` desde el navegador
- Estado de cuenta MT5 en vivo
- Múltiples cuentas MT5

---

## Arquitectura interna

```
Canal Telegram (señales)
        ↓  [Telethon — escucha en tiempo real + polling]
telegram_listener.py  →  local_signal_parser.py
                     →  risk_manager.py
                                ↓
                        mt5_connector.py (MetaTrader 5)
                                ↓
                         api_server.notify_frontend()
                                 ↓
                         Frontend React (REST polling)
```

El backend expone un servidor HTTP en el puerto 8766. El frontend React se conecta vía REST con polling cada 2 segundos para obtener estado en tiempo real.

---

## Variables de entorno (.env)

Igual que TelBot v1 — ver `.env.example`. Novedades en v2 pendientes:

```
# Multi-cuenta MT5 (futuro)
MT5_ACCOUNTS=cuenta1,cuenta2
MT5_LOGIN_1=...
MT5_SERVER_1=...

# Límites diarios (futuro)
DAILY_PROFIT_LIMIT=0
DAILY_LOSS_LIMIT=0
```

---

## PENDIENTES v2

- [ ] Múltiples cuentas MT5 simultáneas
- [ ] Comando `/deactivate` para pausar ejecución
- [ ] Límites de profit/loss diario
- [ ] Historial de señales persistente
- [ ] Notificaciones push al frontend
- [ ] Gráficos de rendimiento
- [ ] WebSocket nativo en backend
