import subprocess
import sys
from pathlib import Path

from backend.schemas import ColorMedicamento

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_SCRIPT = PROJECT_ROOT / "scripts" / "inference.py"


class InferenceError(Exception):
    def __init__(self, message: str, stderr: str | None = None):
        super().__init__(message)
        self.stderr = stderr


class InferenceTimeout(InferenceError):
    pass


def run_inference(color: ColorMedicamento, timeout: int = 120) -> str:
    if not INFERENCE_SCRIPT.is_file():
        raise InferenceError(f"No se encontró el script: {INFERENCE_SCRIPT}")

    try:
        result = subprocess.run(
            [sys.executable, str(INFERENCE_SCRIPT), "--color", color],
            check=False,
            timeout=timeout,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired as e:
        raise InferenceTimeout(f"Timeout en inferencia para color {color}") from e
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise InferenceError(
            f"Inferencia falló para color {color} (código {result.returncode})",
            stderr=err or None,
        )
    return (result.stdout or "").strip()
