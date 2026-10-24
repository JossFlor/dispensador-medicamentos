import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PATH = PROJECT_ROOT / "data" / "robot_control.json"
_lock = threading.Lock()


def publicar(accion: str) -> None:
    payload = {"accion": accion, "ts": time.time()}
    CONTROL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporal = CONTROL_PATH.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporal, CONTROL_PATH)


def leer() -> dict | None:
    with _lock:
        if not CONTROL_PATH.is_file():
            return None
        try:
            return json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


def consumir() -> str | None:
    with _lock:
        if not CONTROL_PATH.is_file():
            return None
        try:
            data = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        CONTROL_PATH.unlink(missing_ok=True)
        accion = data.get("accion")
        return accion if isinstance(accion, str) else None


def detener_lelab() -> str:
    """Cuts the policy process on LeLab. The arm stays where that process releases it."""
    base = os.environ.get("LELAB_URL", "http://127.0.0.1:8000").rstrip("/")
    req = urllib.request.Request(f"{base}/stop-inference", data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode() or "{}")
            return body.get("message") or "Inferencia detenida"
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        try:
            detail = json.loads(detail).get("detail", detail)
        except json.JSONDecodeError:
            pass
        if e.code == 409:
            return "No había un movimiento en curso"
        return f"LeLab no pudo detenerse: {detail}"
    except urllib.error.URLError as e:
        return f"No se alcanzó LeLab: {e.reason}"
