import logging
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import inventory, medicamentos, ocr_receta, recetas_log, voz
from backend.inference_runner import InferenceError, InferenceTimeout, run_inference, usa_lelab
from backend.schemas import (
    Actividad,
    ColorMedicamento,
    EstadoSistema,
    Inventario,
    Medicamento,
    RegistroReceta,
    RespuestaSolicitud,
    RespuestaVoz,
    SolicitudColor,
    SolicitudReposicion,
    SolicitudVoz,
    ValidacionReceta,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
MAX_IMAGEN_BYTES = 10 * 1024 * 1024
MAX_TEXTO_OCR = 500

# There is a single physical robot: only one dispensation may run at a time.
_dispensador_lock = threading.Lock()
_dispensando: ColorMedicamento | None = None
_ultima_actividad: Actividad | None = None


def _registrar_actividad(evento: str, nivel: Literal["info", "success", "warning", "error"] = "info") -> None:
    global _ultima_actividad
    _ultima_actividad = Actividad(evento=evento, nivel=nivel, timestamp=datetime.now(timezone.utc))


def _nombre(color: ColorMedicamento) -> str:
    med = medicamentos.por_color(color)
    return f"{med.nombre} {med.dosis}"


@asynccontextmanager
async def lifespan(_: FastAPI):
    inventory.ensure_inventario_file()
    yield


app = FastAPI(
    title="Dispensador de medicamentos",
    description="API para inventario, dispensación, pedidos por voz y validación de recetas",
    version="1.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def revalidar_siempre(request: Request, call_next):
    # Without this, browsers keep serving a stale styles.css/app.js after the frontend changes.
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.exception_handler(inventory.InventarioCorrupto)
def inventario_corrupto_handler(_: Request, exc: inventory.InventarioCorrupto) -> JSONResponse:
    logger.error("%s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/inventario", response_model=Inventario)
def get_inventario() -> Inventario:
    return inventory.get_inventario()


@app.get("/medicamentos", response_model=list[Medicamento])
def get_medicamentos() -> list[Medicamento]:
    return list(medicamentos.MEDICAMENTOS)


@app.get("/estado", response_model=EstadoSistema)
def get_estado() -> EstadoSistema:
    return EstadoSistema(
        robot_ocupado=_dispensador_lock.locked(),
        dispensando=_dispensando,
        modo_robot="lelab" if usa_lelab() else "stub",
        inventario=inventory.get_inventario(),
        ultima_actividad=_ultima_actividad,
    )


@app.post(
    "/solicitar",
    response_model=RespuestaSolicitud,
    responses={
        409: {"description": "Sin stock, dispensador ocupado o receta no válida"},
        502: {"description": "El robot / inferencia falló"},
        504: {"description": "El robot no respondió a tiempo"},
    },
)
def solicitar(body: SolicitudColor) -> RespuestaSolicitud:
    global _dispensando
    color = body.color
    if not _dispensador_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="El dispensador está ocupado con otra orden")

    try:
        try:
            inventory.validate_stock(color)
            if body.receta_id:
                recetas_log.comprobar_para_dispensar(body.receta_id, color)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

        _dispensando = color
        _registrar_actividad(f"Dispensando {_nombre(color)}")
        try:
            output = run_inference(color)
            if output:
                logger.info("Inferencia: %s", output)
        except InferenceTimeout as e:
            logger.error("Inferencia sin respuesta: %s", e)
            _registrar_actividad(f"El robot no respondió al dispensar {_nombre(color)}", "error")
            raise HTTPException(status_code=504, detail=str(e)) from e
        except InferenceError as e:
            logger.error("Inferencia falló: %s stderr=%s", e, e.stderr)
            _registrar_actividad(f"Fallo del robot al dispensar {_nombre(color)}", "error")
            detail = str(e)
            if e.stderr:
                detail = f"{detail}: {e.stderr[:500]}"
            raise HTTPException(status_code=502, detail=detail) from e

        try:
            inventario = inventory.decrement_after_delivery(color)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        if body.receta_id:
            recetas_log.registrar_dispensacion(body.receta_id)
        con_receta = " con receta validada" if body.receta_id else ""
        _registrar_actividad(f"Entregado {_nombre(color)}{con_receta}", "success")
    finally:
        _dispensando = None
        _dispensador_lock.release()

    return RespuestaSolicitud(status="entregado", color=color, inventario=inventario, receta_id=body.receta_id)


@app.post(
    "/reponer",
    response_model=Inventario,
    responses={409: {"description": "El dispensador está ocupado con otra orden"}},
)
def reponer(body: SolicitudReposicion | None = None) -> Inventario:
    """Fija las unidades de las bandejas indicadas. Sin cuerpo, restablece todas al stock inicial."""
    if not _dispensador_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="El dispensador está ocupado con otra orden")
    try:
        inventario = inventory.reponer(body.stock if body else None)
    finally:
        _dispensador_lock.release()
    logger.info("Inventario repuesto: %s", inventario.model_dump())
    _registrar_actividad("Inventario repuesto")
    return inventario


@app.post(
    "/interpretar-voz",
    response_model=RespuestaVoz,
    responses={422: {"description": "No se reconoció un único medicamento en el texto"}},
)
def interpretar_voz(body: SolicitudVoz) -> RespuestaVoz:
    try:
        med, confianza = voz.interpretar(body.texto)
    except voz.VozNoReconocida as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return RespuestaVoz(color=med.color, nombre=med.nombre, confianza=confianza, texto_recibido=body.texto)


@app.post(
    "/validar-receta",
    response_model=ValidacionReceta,
    responses={
        413: {"description": "Imagen demasiado grande"},
        422: {"description": "El archivo no es una imagen válida"},
        503: {"description": "OCR no disponible en el servidor"},
    },
)
def validar_receta(
    imagen: UploadFile = File(description="Foto de la receta"),
    color: ColorMedicamento | None = Form(
        default=None, description="Medicamento solicitado. Sin él, se autoriza el que indique la receta."
    ),
) -> ValidacionReceta:
    datos = imagen.file.read(MAX_IMAGEN_BYTES + 1)
    if len(datos) > MAX_IMAGEN_BYTES:
        raise HTTPException(status_code=413, detail="La imagen supera los 10 MB.")
    try:
        texto = ocr_receta.extraer_texto(datos)
    except ocr_receta.ImagenInvalida as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ocr_receta.OCRNoDisponible as e:
        logger.error("OCR no disponible: %s", e)
        raise HTTPException(status_code=503, detail=str(e)) from e

    evaluacion = ocr_receta.evaluar(texto, color)
    med = evaluacion.medicamento
    validacion = ValidacionReceta(
        id=uuid.uuid4().hex[:12],
        timestamp=datetime.now(timezone.utc),
        color=med.color if med else None,
        medicamento=f"{med.nombre} {med.dosis}" if med else None,
        autorizado=evaluacion.autorizado,
        motivo=evaluacion.motivo,
        fragmento=evaluacion.fragmento,
        texto_ocr=" ".join(texto.split())[:MAX_TEXTO_OCR],
    )
    recetas_log.registrar_validacion(validacion)
    if validacion.autorizado:
        _registrar_actividad(f"Receta validada por IA: {validacion.medicamento}", "success")
    else:
        _registrar_actividad(f"Receta rechazada por IA: {validacion.motivo}", "warning")
    return validacion


@app.get("/recetas", response_model=list[RegistroReceta])
def get_recetas(limit: int = Query(default=50, ge=1, le=200)) -> list[RegistroReceta]:
    return recetas_log.listar(limit)


# API routes must be registered before static mount
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
