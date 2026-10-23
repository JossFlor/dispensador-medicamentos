import json
import os
import tempfile
import threading
from pathlib import Path

from pydantic import ValidationError

from backend.schemas import COLORES, ColorMedicamento, Inventario

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTARIO_PATH = PROJECT_ROOT / "data" / "inventario.json"
DEFAULT_STOCK = 3

_lock = threading.Lock()


class InventarioCorrupto(RuntimeError):
    pass


def _default_inventario_dict() -> dict[str, int]:
    return {color: DEFAULT_STOCK for color in COLORES}


def ensure_inventario_file() -> None:
    INVENTARIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not INVENTARIO_PATH.exists():
        _write_raw(_default_inventario_dict())


def _read_raw() -> dict[str, int]:
    ensure_inventario_file()
    try:
        with INVENTARIO_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        for color in COLORES:
            data.setdefault(color, DEFAULT_STOCK)
        return Inventario(**{color: data[color] for color in COLORES}).model_dump()
    except (json.JSONDecodeError, ValidationError, AttributeError, TypeError) as e:
        raise InventarioCorrupto(f"{INVENTARIO_PATH.name} no es válido: {e}") from e


def _write_raw(data: dict[str, int]) -> None:
    INVENTARIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = {color: data[color] for color in COLORES}
    # Write to a temp file and rename so a crash mid-write never leaves a truncated JSON.
    fd, tmp_path = tempfile.mkstemp(dir=INVENTARIO_PATH.parent, prefix=".inventario-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ordered, f, indent=2)
            f.write("\n")
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, INVENTARIO_PATH)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def get_inventario() -> Inventario:
    with _lock:
        return Inventario(**_read_raw())


def validate_stock(color: ColorMedicamento) -> None:
    with _lock:
        data = _read_raw()
        if data[color] <= 0:
            raise ValueError(f"Sin stock de {color}")


def reponer() -> Inventario:
    with _lock:
        data = _default_inventario_dict()
        _write_raw(data)
        return Inventario(**data)


def decrement_after_delivery(color: ColorMedicamento) -> Inventario:
    with _lock:
        data = _read_raw()
        if data[color] <= 0:
            raise ValueError(f"Sin stock de {color}")
        data[color] -= 1
        _write_raw(data)
        return Inventario(**data)
