"""config_panel.py — Panel web para editar .env desde el navegador."""

import os
import re
import sys
import http.server
import urllib.parse
import json
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
ENV_EXAMPLE = BASE_DIR / ".env.example"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

DESCRIPTIONS = {}
if ENV_EXAMPLE.is_file():
    last_desc = ""
    with open(ENV_EXAMPLE, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("#==") and not stripped.startswith("# -"):
                last_desc = stripped.lstrip("#").strip()
            elif "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                DESCRIPTIONS[key] = last_desc
                last_desc = ""

SECTIONS = [
    ("GitHub", ["GITHUB_REPO", "GITHUB_BRANCH"]),
    ("Telegram", ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"]),
    ("Canales", ["SIGNAL_CHANNEL", "FORWARD_CHAT_ID", "CONTROL_CHAT_ID"]),
    ("MetaTrader 5", ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_TERMINAL_PATH", "MT5_INSTANCE_ID"]),
    ("Riesgo", ["RISK_PERCENT", "MAX_LOT_SIZE", "MIN_LOT_SIZE", "DEFAULT_MAGIC", "ORDER_COMMENT", "RANDOM_OFFSET_TICKS", "ORDER_RETRY_COUNT", "ORDER_RETRY_DELAY", "TP_INDEX", "RR_RATIO"]),
    ("Modo", ["DRY_RUN", "CONFIRM_TRADES"]),
    ("Polling", ["POLLING_INTERVAL", "MESSAGE_LIMIT"]),
]


def read_env():
    values = {}
    if ENV_FILE.is_file():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    key, val = stripped.split("=", 1)
                    values[key.strip()] = val.strip()
    return values


def write_env(updates):
    lines = []
    keys_done = set()
    if ENV_FILE.is_file():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        lines.append(f"{key}={updates[key]}\n")
                        keys_done.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
        for key, val in updates.items():
            if key not in keys_done:
                lines.append(f"{key}={val}\n")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _is_secure(val, key):
    low = val.lower()
    if low in ("", "true", "false", "1", "0", "yes", "no"):
        return True
    if key in ("TELEGRAM_API_ID", "MT5_LOGIN", "MT5_INSTANCE_ID", "RISK_PERCENT",
               "MAX_LOT_SIZE", "MIN_LOT_SIZE", "RANDOM_OFFSET_TICKS", "ORDER_RETRY_COUNT",
               "POLLING_INTERVAL", "MESSAGE_LIMIT"):
        return val.lstrip("-").isdigit()
    if key in ("ORDER_RETRY_DELAY",):
        try:
            float(val)
            return True
        except ValueError:
            return False
    return False


HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TelBot — Configuración</title>
<style>
*{{ box-sizing: border-box; margin: 0; padding: 0; }}
body{{ font-family: -apple-system, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
.container{{ max-width: 800px; margin: auto; }}
h1{{ color: #58a6ff; font-size: 24px; margin-bottom: 20px; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
.section{{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
.section h2{{ color: #58a6ff; font-size: 16px; margin-bottom: 16px; }}
.field{{ margin-bottom: 14px; }}
.field label{{ display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #c9d1d9; }}
.field .desc{{ font-size: 11px; color: #8b949e; margin-bottom: 4px; }}
.field input, .field select{{ width: 100%; padding: 8px 10px; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 13px; }}
.field input:focus{{ border-color: #58a6ff; outline: none; }}
.field .secure{{ color: #3fb950; font-size: 11px; }}
.actions{{ display: flex; gap: 10px; margin-top: 20px; }}
.btn{{ padding: 10px 24px; border: none; border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer; }}
.btn-primary{{ background: #238636; color: #fff; }}
.btn-primary:hover{{ background: #2ea043; }}
.btn-secondary{{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }}
.btn-secondary:hover{{ background: #30363d; }}
.toast{{ display: none; position: fixed; bottom: 20px; right: 20px; background: #238636; color: #fff; padding: 12px 20px; border-radius: 6px; font-size: 14px; }}
.toast.error{{ background: #da3633; }}
</style>
</head>
<body>
<div class="container">
<h1>⚙️ TelBot — Configuración</h1>
<form method="post" action="/save" id="form">
{fields}
<div class="actions">
<button type="submit" class="btn btn-primary">💾 Guardar cambios</button>
<button type="button" class="btn btn-secondary" onclick="location.reload()">↻ Recargar</button>
</div>
</form>
</div>
<div id="toast" class="toast"></div>
<script>
document.getElementById('form').onsubmit = async function(e){{
e.preventDefault();
const form = e.target;
const data = new FormData(form);
const params = new URLSearchParams(data);
const res = await fetch('/save', {{ method: 'POST', body: params }});
if (res.ok) {{
showToast('✅ Configuración guardada');
setTimeout(() => location.reload(), 1500);
}} else {{
showToast('❌ Error al guardar', true);
}}
}};
function showToast(msg, err) {{
const t = document.getElementById('toast');
t.textContent = msg; t.className = 'toast' + (err ? ' error' : '');
t.style.display = 'block'; setTimeout(() => t.style.display = 'none', 3000);
}}
</script>
</body>
</html>"""


def generate_fields(values):
    sections_html = ""
    for title, keys in SECTIONS:
        html = f'<div class="section"><h2>{title}</h2>'
        for key in keys:
            val = values.get(key, "")
            desc = DESCRIPTIONS.get(key, "")
            secure = _is_secure(val, key) if val else False
            if key in ("DRY_RUN", "CONFIRM_TRADES"):
                opts = {"true": "Sí (true)", "false": "No (false)"}
                sel = '<select name="' + key + '">'
                for opt, label in opts.items():
                    selected = ' selected' if val.lower() == opt else ''
                    sel += f'<option value="{opt}"{selected}>{label}</option>'
                sel += "</select>"
                html += f'<div class="field"><label>{key}</label><div class="desc">{desc}</div>{sel}</div>'
            else:
                ptype = 'password' if not secure and any(k in key for k in ("PASSWORD", "TOKEN", "HASH", "API_KEY")) else 'text'
                html += f'<div class="field"><label>{key}</label><div class="desc">{desc}</div>'
                html += f'<input type="{ptype}" name="{key}" value="{val}" spellcheck="false">'
                if secure:
                    html += f'<div class="secure">✓ Valor seguro</div>'
                html += "</div>"
        sections_html += html + "</div>"
    return sections_html


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            values = read_env()
            body = HTML.format(fields=generate_fields(values))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/save":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                params = urllib.parse.parse_qs(body)
                updates = {k: v[0] for k, v in params.items()}
                write_env(updates)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": false, "error": str(e)}).encode())
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = http.server.HTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Panel de configuración abierto en: {url}")
    print(f"Si el puerto {PORT} está ocupado, usa: python config_panel.py PUERTO")
    webbrowser.open(url)
    print("Presiona Ctrl+C para detener el panel.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPanel detenido.")
