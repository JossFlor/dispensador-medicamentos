#!/usr/bin/env python3
"""Dispensación por color: stub local o inferencia LeLab (LeRobot)."""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

VALID_COLORS = ("rojo", "amarillo", "verde", "azul")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LELAB_CONFIG = PROJECT_ROOT / "data" / "lelab_inference.json"
LELAB_CONFIG_MAC = PROJECT_ROOT / "data" / "lelab_inference.mac.json"
DEFAULT_LELAB_URL = "http://127.0.0.1:8000"


def config_lelab() -> Path:
    """Linux keeps data/lelab_inference.json. The Mac uses its own file so the USB port does not collide."""
    chosen = os.environ.get("LELAB_CONFIG")
    if chosen:
        return Path(chosen)
    if sys.platform == "darwin" and LELAB_CONFIG_MAC.is_file():
        return LELAB_CONFIG_MAC
    return LELAB_CONFIG


def _http_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        try:
            parsed = json.loads(detail)
            detail = parsed.get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"LeLab {path} → HTTP {e.code}: {detail}") from e


def _orden_gerente(inicio: float) -> str | None:
    path = PROJECT_ROOT / "data" / "robot_control.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if float(data.get("ts") or 0) < inicio:
        return None
    path.unlink(missing_ok=True)
    accion = data.get("accion")
    return accion if accion in ("freno", "cubo") else None


def _policy_ref(config: dict[str, Any], color: str) -> str:
    policies = config.get("policies_by_color") or {}
    ref = policies.get(color) or ""
    if not ref:
        raise RuntimeError(f"No hay modelo de LeLab configurado para el color {color}")
    return ref


def _lelab_payload(config: dict[str, Any], color: str) -> dict[str, Any]:
    tasks = config.get("tasks_by_color") or {}
    task = tasks.get(color, config.get("task", ""))
    return {
        "follower_port": config["follower_port"],
        "follower_config": config["follower_config"],
        "policy_ref": _policy_ref(config, color),
        "task": task,
        "cameras": config["cameras"],
        "duration_s": int(config.get("duration_s", 60)),
    }


class _Vision:
    """Validación con la Webcam fija. Si no está calibrada o falta OpenCV, no interviene."""

    def __init__(self, color: str):
        self.color = color
        self.cfg: dict[str, Any] = {}
        self.base = 0.0
        self.vigilante = None
        try:
            import vision_cubo
        except ImportError as e:
            print(f"Validación visual desactivada (falta OpenCV: {e})", file=sys.stderr)
            return
        cfg = vision_cubo.leer_config()
        if not vision_cubo.activa(cfg):
            return
        try:
            self.base = vision_cubo.linea_base(cfg, color)
        except RuntimeError as e:
            print(f"Validación visual desactivada: {e}", file=sys.stderr)
            return
        self.cfg = cfg
        self._vc = vision_cubo
        print(f"Validación visual activa (zona con {self.base:.1%} de {color} antes de empezar)", flush=True)

    @property
    def activa(self) -> bool:
        return bool(self.cfg)

    def vigilar(self) -> None:
        if self.activa and self.cfg.get("live_index") is not None:
            self.vigilante = self._vc.Vigilante(self.cfg, self.color, self.base)
            self.vigilante.start()

    def detectado_en_vivo(self) -> bool:
        return bool(self.vigilante and self.vigilante.detectado.is_set())

    def detener(self) -> None:
        if self.vigilante:
            self.vigilante.parar.set()
            self.vigilante.join(timeout=3)
            if self.vigilante.error:
                print(f"Vigilancia en vivo sin cámara: {self.vigilante.error}", file=sys.stderr)
            self.vigilante = None

    def verificar_final(self) -> bool:
        self.detener()
        try:
            return self._vc.verificar(self.cfg, self.color, self.base)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return False


def _detener_lelab(base_url: str) -> None:
    try:
        _http_json(base_url, "/stop-inference", method="POST", body={}, timeout=15)
    except RuntimeError:
        pass


def run_lelab(color: str, base_url: str, config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    payload = _lelab_payload(config, color)
    print(f"LeLab {color}: {payload['policy_ref']}", flush=True)
    vision = _Vision(color)
    try:
        return _rollout(color, base_url, payload, vision)
    finally:
        vision.detener()


def _rollout(color: str, base_url: str, payload: dict[str, Any], vision: _Vision) -> int:
    poll_deadline = time.time() + payload["duration_s"] + 90

    _http_json(base_url, "/start-inference", method="POST", body=payload, timeout=120)
    inicio = time.time()
    vision.vigilar()

    while time.time() < poll_deadline:
        orden = _orden_gerente(inicio)
        if orden == "freno":
            _detener_lelab(base_url)
            print("Freno accionado: movimiento detenido", file=sys.stderr)
            return 2
        if orden == "cubo":
            _detener_lelab(base_url)
            print(f"Entregando cubo {color}")
            return 0
        if vision.detectado_en_vivo():
            _detener_lelab(base_url)
            print(f"Cubo {color} detectado en la zona de entrega")
            print(f"Entregando cubo {color}")
            return 0
        status = _http_json(base_url, "/inference-status", timeout=30)
        if not status.get("inference_active"):
            if status.get("exited") or status.get("exit_code") is not None:
                code = status.get("exit_code")
                if code == 0:
                    if vision.activa and not vision.verificar_final():
                        print(f"Cubo {color} no detectado en la zona de entrega", file=sys.stderr)
                        return 3
                    print(f"Entregando cubo {color}")
                    return 0
                print(
                    f"Inferencia LeLab terminó con código {code}",
                    file=sys.stderr,
                )
                return 1 if code is None else int(code) or 1
            # Aún no arrancó el subproceso; esperar un poco más.
        time.sleep(0.5)

    print("Timeout esperando a que LeLab termine la inferencia", file=sys.stderr)
    _detener_lelab(base_url)
    return 1


def run_stub(color: str, fail: bool) -> int:
    time.sleep(random.uniform(2.0, 4.0))
    if fail:
        print(f"Error: no se pudo entregar cubo {color}", file=sys.stderr)
        return 1
    print(f"Entregando cubo {color}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Entrega de medicamento por color (stub o LeLab).")
    parser.add_argument("--color", required=True, choices=VALID_COLORS)
    parser.add_argument("--fail", action="store_true", help="Simular fallo (solo stub)")
    parser.add_argument("--lelab", action="store_true", help="Usar API de LeLab")
    parser.add_argument("--stub", action="store_true", help="Simulación sin robot")
    args = parser.parse_args()

    use_lelab = args.lelab or (
        not args.stub
        and os.environ.get("USE_LELAB", "").strip().lower() in ("1", "true", "yes")
    )

    if use_lelab:
        config_path = config_lelab()
        if not config_path.is_file():
            print(f"No se encontró configuración LeLab: {config_path}", file=sys.stderr)
            return 1
        base_url = os.environ.get("LELAB_URL", DEFAULT_LELAB_URL)
        try:
            return run_lelab(args.color, base_url, config_path)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        except urllib.error.URLError as e:
            print(
                f"No se pudo conectar a LeLab en {base_url}. ¿Está `lelab` en marcha? {e}",
                file=sys.stderr,
            )
            return 1

    return run_stub(args.color, args.fail)


if __name__ == "__main__":
    sys.exit(main())
