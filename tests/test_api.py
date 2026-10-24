import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend import inventory, main, ocr_receta, recetas_log, robot_control
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
def recetas_path(tmp_path, monkeypatch):
    path = tmp_path / "recetas.jsonl"
    monkeypatch.setattr(recetas_log, "RECETAS_PATH", path)
    return path


@pytest.fixture
def client(inv_path, recetas_path):
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def ocr(monkeypatch):
    """Replaces Tesseract with a fixed text so tests do not depend on the OCR binary."""
    texto = {"valor": ""}
    monkeypatch.setattr(ocr_receta, "extraer_texto", lambda datos: texto["valor"])
    return texto


def validar(client, color=None):
    data = {"color": color} if color else {}
    return client.post("/validar-receta", files={"imagen": ("receta.png", b"png", "image/png")}, data=data)


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
        "status": "completado",
        "color": "azul",
        "inventario": {**{color: DEFAULT_STOCK for color in COLORES}, "azul": 2},
        "receta_id": None,
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


def test_reponer_solo_bandejas_seleccionadas(client, inv_path):
    write_inv(inv_path, rojo=0, amarillo=1, verde=2, azul=0)
    res = client.post("/reponer", json={"stock": {"rojo": 5, "azul": 2}})
    assert res.status_code == 200
    assert res.json() == {"rojo": 5, "amarillo": 1, "verde": 2, "azul": 2}
    assert read_inv(inv_path) == res.json()


@pytest.mark.parametrize(
    "body",
    [{"stock": {}}, {"stock": {"morado": 3}}, {"stock": {"rojo": -1}}, {"stock": {"rojo": 21}}],
)
def test_reponer_valida_cantidades(client, inv_path, body):
    write_inv(inv_path, rojo=1)
    assert client.post("/reponer", json=body).status_code == 422
    assert read_inv(inv_path)["rojo"] == 1


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


def test_catalogo_cubre_todas_las_bandejas(client):
    res = client.get("/medicamentos")
    assert res.status_code == 200
    assert [m["color"] for m in res.json()] == list(COLORES)


def test_estado_refleja_robot_ocupado(client, inv_path):
    write_inv(inv_path)
    assert client.get("/estado").json()["robot_ocupado"] is False
    main._dispensador_lock.acquire()
    try:
        estado = client.get("/estado").json()
    finally:
        main._dispensador_lock.release()
    assert estado["robot_ocupado"] is True
    assert estado["inventario"] == {color: DEFAULT_STOCK for color in COLORES}
    assert estado["modo_robot"] in ("lelab", "stub")


def test_estado_registra_ultima_entrega(client, inv_path, robot):
    write_inv(inv_path, azul=2)
    client.post("/solicitar", json={"color": "azul"})
    actividad = client.get("/estado").json()["ultima_actividad"]
    assert actividad["nivel"] == "success"
    assert "Omeprazol" in actividad["evento"]


@pytest.mark.parametrize(
    ("texto", "color"),
    [
        ("Quiero paracetamol, por favor", "rojo"),
        ("me da un IBUPROFENO", "amarillo"),
        ("omeprasol", "azul"),
        ("amoxicilína de quinientos", "verde"),
        ("el azul", "azul"),
    ],
)
def test_interpretar_voz(client, texto, color):
    res = client.post("/interpretar-voz", json={"texto": texto})
    assert res.status_code == 200
    assert res.json()["color"] == color
    assert res.json()["texto_recibido"] == texto


@pytest.mark.parametrize("texto", ["buenos días", "paracetamol e ibuprofeno"])
def test_interpretar_voz_sin_un_medicamento_claro(client, texto):
    res = client.post("/interpretar-voz", json={"texto": texto})
    assert res.status_code == 422


def test_receta_autorizada_se_registra(client, ocr):
    ocr["valor"] = "Dr. Pérez\nParacetamol 500 mg cada 8 horas\nFirma"
    res = validar(client, "rojo")
    assert res.status_code == 200
    body = res.json()
    assert body["autorizado"] is True
    assert body["color"] == "rojo"
    assert body["fragmento"] == "Paracetamol 500 mg cada 8 horas"

    historial = client.get("/recetas").json()
    assert [r["id"] for r in historial] == [body["id"]]
    assert historial[0]["dispensada_en"] is None


def test_receta_con_otro_medicamento_se_rechaza(client, ocr):
    ocr["valor"] = "Ibuprofeno 400 mg"
    body = validar(client, "rojo").json()
    assert body["autorizado"] is False
    assert "Ibuprofeno" in body["motivo"]


def test_receta_con_varios_medicamentos_devuelve_la_lista(client, ocr):
    ocr["valor"] = "Paracetamol 500 mg\nIbuprofeno 400 mg"
    body = validar(client).json()
    assert body["autorizado"] is False
    assert [m["color"] for m in body["detectados"]] == ["rojo", "amarillo"]
    assert body["detectados"][0]["fragmento"] == "Paracetamol 500 mg"


def test_receta_sin_color_detecta_el_medicamento(client, ocr):
    ocr["valor"] = "RP/ Omeprazol 20mg en ayunas"
    body = validar(client).json()
    assert body["autorizado"] is True
    assert body["color"] == "azul"


def test_receta_ilegible_se_rechaza(client, ocr):
    ocr["valor"] = "   "
    assert validar(client, "verde").json()["autorizado"] is False


def test_receta_sin_ocr_instalado_devuelve_503(client, monkeypatch):
    def sin_tesseract(datos):
        raise ocr_receta.OCRNoDisponible("Tesseract no está instalado")

    monkeypatch.setattr(ocr_receta, "extraer_texto", sin_tesseract)
    assert validar(client, "rojo").status_code == 503


def test_imagen_invalida_devuelve_422(client):
    assert validar(client, "rojo").status_code == 422


def test_recetas_mas_recientes_primero(client, ocr):
    ocr["valor"] = "Paracetamol"
    primera = validar(client, "rojo").json()["id"]
    ocr["valor"] = "nada"
    segunda = validar(client, "rojo").json()["id"]
    assert [r["id"] for r in client.get("/recetas").json()] == [segunda, primera]


def test_solicitar_con_receta_la_marca_como_dispensada(client, inv_path, robot, ocr):
    write_inv(inv_path, rojo=2)
    ocr["valor"] = "Paracetamol 500 mg"
    receta_id = validar(client, "rojo").json()["id"]

    res = client.post("/solicitar", json={"color": "rojo", "receta_id": receta_id})
    assert res.status_code == 200
    assert res.json()["receta_id"] == receta_id
    assert client.get("/recetas").json()[0]["dispensada_en"] is not None

    reutilizada = client.post("/solicitar", json={"color": "rojo", "receta_id": receta_id})
    assert reutilizada.status_code == 409
    assert robot == ["rojo"]


@pytest.mark.parametrize(
    ("texto_receta", "color_pedido"),
    [("Ibuprofeno", "rojo"), ("Paracetamol", "amarillo")],
)
def test_solicitar_con_receta_no_valida_no_mueve_el_robot(
    client, inv_path, robot, ocr, texto_receta, color_pedido
):
    write_inv(inv_path)
    ocr["valor"] = texto_receta
    receta_id = validar(client, "rojo").json()["id"]
    res = client.post("/solicitar", json={"color": color_pedido, "receta_id": receta_id})
    assert res.status_code == 409
    assert robot == []
    assert read_inv(inv_path) == {color: DEFAULT_STOCK for color in COLORES}


def test_solicitar_con_receta_inexistente(client, inv_path, robot):
    write_inv(inv_path)
    res = client.post("/solicitar", json={"color": "rojo", "receta_id": "no-existe"})
    assert res.status_code == 409
    assert robot == []


def test_receta_caducada(client, inv_path, robot, ocr, monkeypatch):
    write_inv(inv_path)
    ocr["valor"] = "Paracetamol"
    receta_id = validar(client, "rojo").json()["id"]
    monkeypatch.setattr(recetas_log, "VIGENCIA", recetas_log.VIGENCIA * 0)
    res = client.post("/solicitar", json={"color": "rojo", "receta_id": receta_id})
    assert res.status_code == 409
    assert "caducó" in res.json()["detail"]


def test_gerente_servido(client):
    res = client.get("/gerente.html")
    assert res.status_code == 200
    assert "Panel de gerencia" in res.text
    assert "Freno" in res.text
    assert "Cubo colocado" not in res.text


def test_freno_y_cubo_avisan_a_la_orden_en_curso(client, tmp_path, monkeypatch):
    monkeypatch.setattr(robot_control, "CONTROL_PATH", tmp_path / "robot_control.json")
    monkeypatch.setattr(robot_control, "detener_lelab", lambda: "Inferencia detenida")

    freno = client.post("/robot/freno")
    assert freno.status_code == 200
    assert freno.json()["status"] == "freno"
    assert json.loads((tmp_path / "robot_control.json").read_text())["accion"] == "freno"

    cubo = client.post("/robot/cubo-colocado")
    assert cubo.status_code == 200
    assert json.loads((tmp_path / "robot_control.json").read_text())["accion"] == "cubo"
