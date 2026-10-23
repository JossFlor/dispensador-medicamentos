import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend import inventory, main
from backend.inference_runner import InferenceError, InferenceTimeout, run_inference
from backend.inventory import DEFAULT_STOCK
from backend.schemas import COLORES


@pytest.fixture
def inv_path(tmp_path, monkeypatch):
    path = tmp_path / "inventario.json"
    monkeypatch.setattr(inventory, "INVENTARIO_PATH", path)
    return path


@pytest.fixture
def robot(monkeypatch):
    calls = []

    def fake_run_inference(color):
        calls.append(color)
        return f"Entregando cubo {color}"

    monkeypatch.setattr(main, "run_inference", fake_run_inference)
    return calls


@pytest.fixture
def client(inv_path):
    with TestClient(main.app) as c:
        yield c


def write_inv(path, **stock):
    data = {color: DEFAULT_STOCK for color in COLORES}
    data.update(stock)
    path.write_text(json.dumps(data))


def read_inv(path):
    return json.loads(path.read_text())


def test_crea_inventario_por_defecto(client, inv_path):
    res = client.get("/inventario")
    assert res.status_code == 200
    assert res.json() == {color: DEFAULT_STOCK for color in COLORES}
    assert inv_path.exists()


def test_solicitar_descuenta_y_persiste(client, inv_path, robot):
    write_inv(inv_path, azul=3)
    res = client.post("/solicitar", json={"color": "azul"})
    assert res.status_code == 200
    assert res.json() == {
        "status": "entregado",
        "color": "azul",
        "inventario": {**{color: DEFAULT_STOCK for color in COLORES}, "azul": 2},
    }
    assert read_inv(inv_path)["azul"] == 2
    assert robot == ["azul"]


def test_color_invalido(client, robot):
    res = client.post("/solicitar", json={"color": "morado"})
    assert res.status_code == 422
    assert robot == []


def test_sin_stock_no_mueve_el_robot(client, inv_path, robot):
    write_inv(inv_path, verde=0)
    res = client.post("/solicitar", json={"color": "verde"})
    assert res.status_code == 409
    assert res.json()["detail"] == "Sin stock de verde"
    assert robot == []


@pytest.mark.parametrize(
    ("error", "status"),
    [(InferenceError("falló", stderr="brazo bloqueado"), 502), (InferenceTimeout("Timeout"), 504)],
)
def test_fallo_del_robot_no_descuenta(client, inv_path, monkeypatch, error, status):
    write_inv(inv_path)

    def failing(color):
        raise error

    monkeypatch.setattr(main, "run_inference", failing)
    res = client.post("/solicitar", json={"color": "rojo"})
    assert res.status_code == status
    assert read_inv(inv_path)["rojo"] == DEFAULT_STOCK


def test_lock_liberado_tras_fallo(client, inv_path, monkeypatch, robot):
    write_inv(inv_path)

    def failing(color):
        raise InferenceError("falló")

    monkeypatch.setattr(main, "run_inference", failing)
    assert client.post("/solicitar", json={"color": "rojo"}).status_code == 502
    assert not main._dispensador_lock.locked()


def _run_concurrently(client, monkeypatch, colors):
    """Two orders hit the API while the robot is still busy with the first one."""
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_robot(color):
        calls.append(color)
        started.set()
        release.wait(timeout=5)
        return "ok"

    monkeypatch.setattr(main, "run_inference", slow_robot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/solicitar", json={"color": colors[0]})
        assert started.wait(timeout=5)
        second = client.post("/solicitar", json={"color": colors[1]})
        release.set()
        return first.result(), second, calls


def test_un_solo_movimiento_del_robot_a_la_vez(client, inv_path, monkeypatch):
    write_inv(inv_path)
    first, second, calls = _run_concurrently(client, monkeypatch, ["rojo", "azul"])
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "El dispensador está ocupado con otra orden"
    assert calls == ["rojo"]
    assert read_inv(inv_path) == {
        "rojo": DEFAULT_STOCK - 1,
        "amarillo": DEFAULT_STOCK,
        "verde": DEFAULT_STOCK,
        "azul": DEFAULT_STOCK,
    }


def test_ultima_unidad_no_se_dispensa_dos_veces(client, inv_path, monkeypatch):
    write_inv(inv_path, rojo=1)
    first, second, calls = _run_concurrently(client, monkeypatch, ["rojo", "rojo"])
    assert first.status_code == 200
    assert second.status_code == 409
    assert calls == ["rojo"]
    assert read_inv(inv_path)["rojo"] == 0


@pytest.mark.parametrize("contenido", ["{no es json", '{"rojo": -1}', '["rojo"]', '{"rojo": "muchos"}'])
def test_inventario_corrupto_da_error_claro(client, inv_path, robot, contenido):
    inv_path.write_text(contenido)
    res = client.get("/inventario")
    assert res.status_code == 500
    assert "inventario.json no es válido" in res.json()["detail"]
    assert client.post("/solicitar", json={"color": "rojo"}).status_code == 500
    assert robot == []
    assert not main._dispensador_lock.locked()


def test_escritura_atomica_sin_temporales(client, inv_path, robot):
    write_inv(inv_path)
    for _ in range(3):
        client.post("/solicitar", json={"color": "amarillo"})
    assert read_inv(inv_path)["amarillo"] == 0
    assert [p.name for p in inv_path.parent.iterdir()] == ["inventario.json"]


def test_inventario_legible_por_todos(client, inv_path, robot):
    write_inv(inv_path)
    client.post("/solicitar", json={"color": "rojo"})
    assert inv_path.stat().st_mode & 0o777 == 0o644


def test_reponer_restablece_todas_las_bandejas(client, inv_path):
    write_inv(inv_path, rojo=0, amarillo=1)
    res = client.post("/reponer")
    assert res.status_code == 200
    assert res.json() == {color: DEFAULT_STOCK for color in COLORES}
    assert read_inv(inv_path) == {color: DEFAULT_STOCK for color in COLORES}


def test_reponer_recupera_inventario_corrupto(client, inv_path):
    inv_path.write_text("{no es json")
    assert client.post("/reponer").status_code == 200
    assert client.get("/inventario").json() == {color: DEFAULT_STOCK for color in COLORES}


def test_reponer_rechazado_mientras_dispensa(client, inv_path):
    write_inv(inv_path, rojo=1)
    main._dispensador_lock.acquire()
    try:
        res = client.post("/reponer")
    finally:
        main._dispensador_lock.release()
    assert res.status_code == 409
    assert read_inv(inv_path)["rojo"] == 1


def test_frontend_servido(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Dispensación de medicamentos" in res.text


def test_script_de_inferencia_real():
    assert run_inference("azul") == "Entregando cubo azul"
