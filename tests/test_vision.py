import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vision_cubo  # noqa: E402

CFG = {"roi": [200, 150, 120, 100], "min_ratio": 0.04}
ROJO_BGR = (30, 30, 200)
AMARILLO_BGR = (40, 220, 230)
NARANJA_BGR = (40, 120, 230)


def _mesa(fondo=(90, 90, 90)):
    return np.full((480, 640, 3), fondo, dtype=np.uint8)


def _cubo(img, x, y, bgr, lado=40):
    img[y : y + lado, x : x + lado] = bgr
    return img


def test_detecta_cubo_rojo_en_la_zona():
    img = _cubo(_mesa(), 240, 180, ROJO_BGR)
    ratio = vision_cubo.proporcion(img, "rojo", CFG)
    assert vision_cubo.hay_cubo(ratio, 0.0, CFG)


def test_ignora_cubo_fuera_de_la_zona():
    img = _cubo(_mesa(), 20, 20, ROJO_BGR)
    assert vision_cubo.proporcion(img, "rojo", CFG) == 0


def test_no_confunde_colores():
    img = _cubo(_mesa(), 240, 180, AMARILLO_BGR)
    assert not vision_cubo.hay_cubo(vision_cubo.proporcion(img, "rojo", CFG), 0.0, CFG)
    assert vision_cubo.hay_cubo(vision_cubo.proporcion(img, "amarillo", CFG), 0.0, CFG)


def test_linea_base_descuenta_el_fondo():
    vacia = _mesa(NARANJA_BGR)
    cfg = {**CFG, "colors": {"rojo": [[[0, 120, 70], [20, 255, 255]]]}}
    base = vision_cubo.proporcion(vacia, "rojo", cfg)
    assert base > 0.9
    assert not vision_cubo.hay_cubo(base, base, cfg)


def test_rango_calibrado_del_rojo_cruza_el_cero():
    rangos = vision_cubo._rango_desde_muestra(3, 200, 200)
    assert len(rangos) == 2
    assert rangos[1][0][0] == 173 and rangos[1][1][0] == 180
