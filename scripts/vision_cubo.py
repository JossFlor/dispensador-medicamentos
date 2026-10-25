#!/usr/bin/env python3
"""Valida con la Webcam fija que el cubo quedó en la zona de entrega (ROI + máscara HSV)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VISION_CONFIG = PROJECT_ROOT / "data" / "vision.json"
VISION_CONFIG_MAC = PROJECT_ROOT / "data" / "vision.mac.json"

COLORES = ("rojo", "amarillo", "verde", "azul")
TECLAS_COLOR = {ord("1"): "rojo", ord("2"): "amarillo", ord("3"): "verde", ord("4"): "azul"}
RANGOS_POR_DEFECTO: dict[str, list[list[list[int]]]] = {
    # El rojo cruza el 0 del tono en OpenCV (0-180): necesita dos rangos.
    "rojo": [[[0, 120, 70], [10, 255, 255]], [[170, 120, 70], [180, 255, 255]]],
    "amarillo": [[[20, 100, 100], [35, 255, 255]]],
    "verde": [[[40, 70, 50], [85, 255, 255]]],
    "azul": [[[95, 120, 50], [130, 255, 255]]],
}


def config_vision() -> Path:
    chosen = os.environ.get("VISION_CONFIG")
    if chosen:
        return Path(chosen)
    if sys.platform == "darwin" and VISION_CONFIG_MAC.is_file():
        return VISION_CONFIG_MAC
    return VISION_CONFIG


def leer_config(path: Path | None = None) -> dict[str, Any]:
    path = path or config_vision()
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def activa(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("enabled", True) and cfg.get("roi"))


def fuente(cfg: dict[str, Any]) -> int:
    """Con cámara compartida (v4l2loopback) todo se lee de la copia; si no, de la Webcam física."""
    live = cfg.get("live_index")
    return int(live if live is not None else cfg.get("camera_index", 0))


def rangos(cfg: dict[str, Any], color: str) -> list[list[list[int]]]:
    return (cfg.get("colors") or {}).get(color) or RANGOS_POR_DEFECTO[color]


def proporcion(frame, color: str, cfg: dict[str, Any]) -> float:
    """Fracción de la ROI que tiene el color del cubo."""
    import cv2
    import numpy as np

    x, y, w, h = (int(v) for v in cfg["roi"])
    zona = frame[y : y + h, x : x + w]
    if zona.size == 0:
        return 0.0
    hsv = cv2.cvtColor(zona, cv2.COLOR_BGR2HSV)
    mascara = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lo, hi in rangos(cfg, color):
        mascara |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return cv2.countNonZero(mascara) / float(zona.shape[0] * zona.shape[1])


def hay_cubo(ratio: float, base: float, cfg: dict[str, Any]) -> bool:
    return ratio - base >= float(cfg.get("min_ratio", 0.04))


def abrir_camara(index: int, cfg: dict[str, Any], espera_s: float = 3.0):
    import cv2

    limite = time.time() + espera_s
    while True:
        cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg.get("width", 640)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg.get("height", 480)))
        if cap.isOpened() and cap.read()[0]:
            return cap
        cap.release()
        if time.time() > limite:
            raise RuntimeError(f"No se pudo abrir la cámara {index} para validar el cubo")
        time.sleep(0.3)


def _muestras(cap, n: int) -> list:
    for _ in range(5):
        cap.read()
    frames = []
    for _ in range(n):
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    return frames


def linea_base(cfg: dict[str, Any], color: str) -> float:
    """Color que ya hay en la zona antes de empezar (bandeja vacía, fondo naranja, etc.)."""
    cap = abrir_camara(fuente(cfg), cfg)
    try:
        ratios = sorted(proporcion(f, color, cfg) for f in _muestras(cap, 7))
    finally:
        cap.release()
    return ratios[len(ratios) // 2] if ratios else 0.0


def estado_zona(color: str) -> dict[str, Any]:
    """Dice si el color sigue en la zona de entrega. Sin calibrar, no abre la cámara."""
    cfg = leer_config()
    if not activa(cfg):
        return {"activa": False, "ocupada": None, "ratio": None}
    try:
        cap = abrir_camara(fuente(cfg), cfg, espera_s=1.5)
    except RuntimeError:
        return {"activa": True, "ocupada": None, "ratio": None}
    try:
        frames = _muestras(cap, 3)
    finally:
        cap.release()
    if not frames:
        return {"activa": True, "ocupada": None, "ratio": None}
    ratios = sorted(proporcion(f, color, cfg) for f in frames)
    ratio = ratios[len(ratios) // 2]
    return {"activa": True, "ocupada": hay_cubo(ratio, 0.0, cfg), "ratio": round(ratio, 4)}


def verificar(cfg: dict[str, Any], color: str, base: float, espera_s: float = 6.0) -> bool:
    """Revisión final: la mayoría de fotogramas deben ver el cubo."""
    cap = abrir_camara(fuente(cfg), cfg, espera_s=espera_s)
    try:
        frames = _muestras(cap, 10)
    finally:
        cap.release()
    positivos = sum(hay_cubo(proporcion(f, color, cfg), base, cfg) for f in frames)
    return bool(frames) and positivos >= 0.7 * len(frames)


class Vigilante(threading.Thread):
    """Mira la copia en vivo de la Webcam y avisa cuando el cubo lleva `hold_s` quieto en la zona."""

    def __init__(self, cfg: dict[str, Any], color: str, base: float):
        super().__init__(daemon=True)
        self.cfg, self.color, self.base = cfg, color, base
        self.detectado = threading.Event()
        self.parar = threading.Event()
        self.error: str | None = None

    def run(self) -> None:
        try:
            cap = abrir_camara(int(self.cfg["live_index"]), self.cfg)
        except RuntimeError as e:
            self.error = str(e)
            return
        sostener = float(self.cfg.get("hold_s", 1.0))
        desde: float | None = None
        try:
            while not self.parar.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                if hay_cubo(proporcion(frame, self.color, self.cfg), self.base, self.cfg):
                    desde = desde or time.time()
                    if time.time() - desde >= sostener:
                        self.detectado.set()
                        return
                else:
                    desde = None
        finally:
            cap.release()


def _rango_desde_muestra(h: int, s: int, v: int, tol_h: int = 10) -> list[list[list[int]]]:
    s_min, v_min = max(s - 70, 50), max(v - 80, 40)
    lo, hi = h - tol_h, h + tol_h
    if lo < 0:
        return [[[0, s_min, v_min], [hi, 255, 255]], [[180 + lo, s_min, v_min], [180, 255, 255]]]
    if hi > 180:
        return [[[lo, s_min, v_min], [180, 255, 255]], [[0, s_min, v_min], [hi - 180, 255, 255]]]
    return [[[lo, s_min, v_min], [hi, 255, 255]]]


def calibrar(path: Path, camara: int | None) -> int:
    import cv2
    import numpy as np

    cfg = leer_config(path)
    cfg.setdefault("enabled", True)
    cfg.setdefault("camera_index", 2)
    cfg.setdefault("live_index", None)
    cfg.setdefault("width", 640)
    cfg.setdefault("height", 480)
    cfg.setdefault("min_ratio", 0.04)
    cfg.setdefault("hold_s", 1.0)
    cfg.setdefault("colors", {})
    index = camara if camara is not None else fuente(cfg)
    cap = abrir_camara(index, cfg)
    punto: list[tuple[int, int]] = []

    def click(evento, x, y, *_):
        if evento == cv2.EVENT_LBUTTONDOWN:
            punto[:] = [(x, y)]

    ventana = "Calibrar zona de entrega"
    cv2.namedWindow(ventana)
    cv2.setMouseCallback(ventana, click)
    print(
        "z: marcar zona de entrega | clic sobre un cubo + 1/2/3/4: guardar rojo/amarillo/verde/azul\n"
        "+/-: umbral | g: guardar | q: salir"
    )
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            vista = frame.copy()
            if cfg.get("roi"):
                x, y, w, h = cfg["roi"]
                cv2.rectangle(vista, (x, y), (x + w, y + h), (0, 255, 0), 2)
                for i, color in enumerate(COLORES):
                    r = proporcion(frame, color, cfg)
                    texto = f"{color}: {r:.1%}{'  <- CUBO' if r >= cfg['min_ratio'] else ''}"
                    cv2.putText(vista, texto, (10, 25 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(vista, f"umbral {cfg['min_ratio']:.1%}", (10, vista.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            if punto:
                cv2.circle(vista, punto[0], 6, (255, 0, 255), 2)
            cv2.imshow(ventana, vista)
            tecla = cv2.waitKey(30) & 0xFF
            if tecla == ord("q"):
                return 0
            if tecla == ord("z"):
                x, y, w, h = cv2.selectROI(ventana, frame, showCrosshair=False)
                if w and h:
                    cfg["roi"] = [int(x), int(y), int(w), int(h)]
            elif tecla in (ord("+"), ord("=")):
                cfg["min_ratio"] = round(cfg["min_ratio"] + 0.01, 3)
            elif tecla == ord("-"):
                cfg["min_ratio"] = max(0.005, round(cfg["min_ratio"] - 0.01, 3))
            elif tecla in TECLAS_COLOR and punto:
                px, py = punto[0]
                parche = frame[max(py - 4, 0) : py + 5, max(px - 4, 0) : px + 5]
                hsv = cv2.cvtColor(parche, cv2.COLOR_BGR2HSV).reshape(-1, 3)
                h, s, v = (int(c) for c in np.median(hsv, axis=0))
                color = TECLAS_COLOR[tecla]
                cfg["colors"][color] = _rango_desde_muestra(h, s, v)
                print(f"{color}: HSV {h},{s},{v} → {cfg['colors'][color]}")
            elif tecla == ord("g"):
                path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                print(f"Guardado en {path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validación visual del cubo en la zona de entrega.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cal = sub.add_parser("calibrar", help="Marcar zona, colores y umbral con la cámara en vivo")
    cal.add_argument("--camara", type=int, help="Índice de cámara (por defecto el del JSON)")
    ver = sub.add_parser("verificar", help="Comprobar ahora si hay un cubo en la zona")
    ver.add_argument("--color", required=True, choices=COLORES)
    args = parser.parse_args()

    path = config_vision()
    if args.cmd == "calibrar":
        return calibrar(path, args.camara)

    cfg = leer_config(path)
    if not activa(cfg):
        print(f"Falta calibrar la zona en {path}", file=sys.stderr)
        return 1
    cap = abrir_camara(fuente(cfg), cfg)
    try:
        frames = _muestras(cap, 5)
    finally:
        cap.release()
    ratio = sorted(proporcion(f, args.color, cfg) for f in frames)[len(frames) // 2]
    detectado = hay_cubo(ratio, 0.0, cfg)
    print(f"{args.color}: {ratio:.1%} de la zona (umbral {cfg.get('min_ratio', 0.04):.1%}) → "
          f"{'cubo detectado' if detectado else 'sin cubo'}")
    return 0 if detectado else 3


if __name__ == "__main__":
    sys.exit(main())
