import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import inventory
from backend.inference_runner import InferenceError, InferenceTimeout, run_inference
from backend.schemas import Inventario, RespuestaSolicitud, SolicitudColor, SolicitudReposicion

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# There is a single physical robot: only one dispensation may run at a time.
_dispensador_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    inventory.ensure_inventario_file()
    yield


app = FastAPI(
    title="Dispensador de medicamentos",
    description="API para inventario y solicitud de cubos por color",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(inventory.InventarioCorrupto)
def inventario_corrupto_handler(_: Request, exc: inventory.InventarioCorrupto) -> JSONResponse:
    logger.error("%s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/inventario", response_model=Inventario)
def get_inventario() -> Inventario:
    return inventory.get_inventario()


@app.post(
    "/solicitar",
    response_model=RespuestaSolicitud,
    responses={
        409: {"description": "Sin stock o dispensador ocupado con otra orden"},
        502: {"description": "El robot / inferencia falló"},
        504: {"description": "El robot no respondió a tiempo"},
    },
)
def solicitar(body: SolicitudColor) -> RespuestaSolicitud:
    color = body.color
    if not _dispensador_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="El dispensador está ocupado con otra orden")

    try:
        try:
            inventory.validate_stock(color)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

        try:
            output = run_inference(color)
            if output:
                logger.info("Inferencia: %s", output)
        except InferenceTimeout as e:
            logger.error("Inferencia sin respuesta: %s", e)
            raise HTTPException(status_code=504, detail=str(e)) from e
        except InferenceError as e:
            logger.error("Inferencia falló: %s stderr=%s", e, e.stderr)
            detail = str(e)
            if e.stderr:
                detail = f"{detail}: {e.stderr[:500]}"
            raise HTTPException(status_code=502, detail=detail) from e

        try:
            inventario = inventory.decrement_after_delivery(color)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    finally:
        _dispensador_lock.release()

    return RespuestaSolicitud(status="entregado", color=color, inventario=inventario)


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
    return inventario


# API routes must be registered before static mount
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
