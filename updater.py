#!/usr/bin/env python
"""updater.py — Actualiza TelBot V2 desde GitHub (git pull + dependencias)."""

import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO = os.getenv("TELBOT_REPO", "truji57/TelBot_v2")
BRANCH = os.getenv("TELBOT_BRANCH", "main")


def _run(cmd, **kw):
    kw.setdefault("cwd", BASE_DIR)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr.strip()}")
    return r


def main():
    print(f"TelBot V2 Updater — {REPO} ({BRANCH})")
    print("=" * 40)

    # 1. Check internet
    print("[1/4] Verificando conexion...")
    r = _run(["git", "fetch", "origin"], timeout=30)
    if r.returncode != 0:
        print("  No se pudo conectar con GitHub.")
        return False

    # 2. Check for updates
    print("[2/4] Buscando actualizaciones...")
    local = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote = _run(["git", "rev-parse", f"origin/{BRANCH}"]).stdout.strip()

    if not local or not remote:
        print("  No se pudo detectar la version.")
        return False

    if local == remote:
        print("  Ya esta actualizado.")
        return True

    # 3. Pull
    print("[3/4] Descargando actualizacion...")
    has_changes = bool(_run(["git", "status", "--porcelain"]).stdout.strip())
    stashed = False
    if has_changes:
        r = _run(["git", "stash", "--include-untracked"], timeout=30)
        stashed = r.returncode == 0
        if stashed:
            print("  Cambios locales guardados temporalmente.")

    r = _run(["git", "pull", "--ff-only", "origin", BRANCH], timeout=60)
    if r.returncode != 0:
        print("  No se pudo actualizar. Prueba con git pull manual.")
        if stashed:
            _run(["git", "stash", "pop"])
        return False

    if stashed:
        _run(["git", "stash", "pop"])

    # 4. Install dependencies if needed
    print("[4/4] Instalando dependencias...")

    req_file = BASE_DIR / "requirements.txt"
    if req_file.exists():
        _run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"])

    pkg_json = BASE_DIR / "frontend" / "package.json"
    if pkg_json.exists() and (BASE_DIR / "frontend" / "node_modules").exists():
        _run(["npm", "install"], cwd=BASE_DIR / "frontend", timeout=120,
             shell=True)

    print("=" * 40)
    print("Actualizacion completada.")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
