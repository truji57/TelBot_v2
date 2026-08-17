"""updater.py — Comprueba y aplica actualizaciones desde GitHub."""

import os
import sys
import json
import zipfile
import shutil
import io
import tempfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _latest_remote_commit(repo, branch):
    """Obtiene el SHA del último commit via API HTTP de GitHub (rápido)."""
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    req = urllib.request.Request(url, headers={"User-Agent": "TelBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            return data.get("sha", "")
    except:
        return ""

def _git(*args, timeout=10):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=BASE_DIR, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except:
        return ""

def _download_fallback(repo, branch):
    """Descarga el repo completo como ZIP vía API de GitHub (fallback cuando git falla)."""
    url = f"https://api.github.com/repos/{repo}/zipball/{branch}"
    req = urllib.request.Request(url, headers={"User-Agent": "TelBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            zip_data = r.read()
    except:
        return False

    tmp = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            zf.extractall(tmp)
        items = sorted(tmp.iterdir())
        if not items:
            return False
        src = items[0]
        skip_names = {".env", "logs", "__pycache__", "processed_messages.csv",
                      "last_processed_id.txt", ".update_cache", ".git",
                      "CLAUDE.md", "PENDIENTES.md", "instalar.bat", "instalar2.bat",
                      "run_bot.bat", "install_requirements.bat"}
        for item in src.iterdir():
            if item.name in skip_names:
                continue
            dest = BASE_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    check_only = "--check" in sys.argv
    repo = os.getenv("GITHUB_REPO", "")
    branch = os.getenv("GITHUB_BRANCH", "master")

    try:
        import config
        if hasattr(config, "GITHUB_REPO") and config.GITHUB_REPO:
            repo = config.GITHUB_REPO
        if hasattr(config, "GITHUB_BRANCH") and config.GITHUB_BRANCH:
            branch = config.GITHUB_BRANCH
    except ImportError:
        pass

    if not repo:
        return True

    local = _git("rev-parse", "HEAD")
    if not local:
        return True

    # Detectar rama activa
    detected = _git("rev-parse", "--abbrev-ref", "HEAD")
    if detected:
        branch = detected

    # Comprobación vía API HTTP
    remote = _latest_remote_commit(repo, branch)
    if not remote:
        if check_only:
            sys.exit(0)
        return True

    if remote == local:
        return True

    # Modo --check: solo avisar, no actualizar
    if check_only:
        print(f"[updater] Nueva versión disponible ({branch}).")
        sys.exit(1)

    # Hay cambios — hacer fetch + pull
    import urllib.parse
    owner, repo_name = repo.split("/")

    print(f"[updater] Nueva versión disponible. Descargando...")

    r = subprocess.run(["git", "fetch", "origin"], capture_output=True, text=True, cwd=BASE_DIR, timeout=60)
    if r.returncode != 0:
        print(f"[updater] Error al descargar: {r.stderr.strip()}")
        print("[updater] Intentando descarga alternativa vía API...")
        if _download_fallback(repo, branch):
            print("[updater] ¡Actualizado vía API!")
            return True
        print("[updater] La descarga alternativa también falló.")
        return False

    has_changes = bool(_git("status", "--porcelain"))
    stashed = False
    if has_changes:
        r = subprocess.run(["git", "stash"], capture_output=True, text=True, cwd=BASE_DIR)
        stashed = r.returncode == 0

    r = subprocess.run(["git", "pull", "--ff-only"], capture_output=True, text=True, cwd=BASE_DIR, timeout=60)
    if r.returncode != 0:
        print(f"[updater] Error al actualizar: {r.stderr.strip()}")
        return False

    print("[updater] ¡Actualizado!")

    if stashed:
        subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, cwd=BASE_DIR)

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
