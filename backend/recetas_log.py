import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.schemas import ColorMedicamento, RegistroReceta, ValidacionReceta

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECETAS_PATH = PROJECT_ROOT / "data" / "recetas.jsonl"
VIGENCIA = timedelta(minutes=15)

_lock = threading.Lock()


class RecetaNoValida(ValueError):
    pass


def _append(evento: dict) -> None:
    with _lock:
        RECETAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RECETAS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def _leer() -> list[dict]:
    with _lock:
        if not RECETAS_PATH.exists():
            return []
        lineas = RECETAS_PATH.read_text(encoding="utf-8").splitlines()
    eventos = []
    for linea in lineas:
        try:
            eventos.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return eventos


def registrar_validacion(validacion: ValidacionReceta) -> None:
    _append({"tipo": "validacion", **validacion.model_dump(mode="json")})


def registrar_dispensacion(receta_id: str) -> None:
    _append(
        {"tipo": "dispensacion", "receta_id": receta_id, "timestamp": datetime.now(timezone.utc).isoformat()}
    )


def _registros() -> list[RegistroReceta]:
    eventos = _leer()
    dispensadas = {e["receta_id"]: e["timestamp"] for e in eventos if e.get("tipo") == "dispensacion"}
    registros = []
    for e in eventos:
        if e.get("tipo") != "validacion":
            continue
        datos = {k: v for k, v in e.items() if k != "tipo"}
        try:
            registros.append(RegistroReceta(**datos, dispensada_en=dispensadas.get(datos.get("id"))))
        except ValueError:
            continue
    return registros


def listar(limit: int = 50) -> list[RegistroReceta]:
    return list(reversed(_registros()))[:limit]


def comprobar_para_dispensar(receta_id: str, color: ColorMedicamento) -> RegistroReceta:
    receta = next((r for r in _registros() if r.id == receta_id), None)
    if receta is None:
        raise RecetaNoValida("La receta indicada no existe.")
    if not receta.autorizado:
        raise RecetaNoValida("La receta indicada no fue autorizada.")
    if receta.color != color:
        raise RecetaNoValida(f"La receta autoriza {receta.medicamento}, no el medicamento solicitado.")
    if receta.dispensada_en is not None:
        raise RecetaNoValida("La receta ya se utilizó para otra dispensación.")
    if datetime.now(timezone.utc) - receta.timestamp > VIGENCIA:
        raise RecetaNoValida("La validación de la receta caducó. Vuelva a escanearla.")
    return receta
