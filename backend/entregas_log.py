import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.schemas import ColorMedicamento, RegistroEntrega

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTREGAS_PATH = PROJECT_ROOT / "data" / "entregas.jsonl"

_lock = threading.Lock()


def registrar(color: ColorMedicamento, medicamento: str, bandeja: str, receta_id: str | None) -> None:
    evento = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "color": color,
        "medicamento": medicamento,
        "bandeja": bandeja,
        "receta_id": receta_id,
    }
    with _lock:
        ENTREGAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ENTREGAS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def listar(limit: int = 50) -> list[RegistroEntrega]:
    with _lock:
        if not ENTREGAS_PATH.exists():
            return []
        lineas = ENTREGAS_PATH.read_text(encoding="utf-8").splitlines()
    registros = []
    for linea in lineas:
        try:
            registros.append(RegistroEntrega.model_validate_json(linea))
        except ValueError:
            continue
    return list(reversed(registros))[:limit]
