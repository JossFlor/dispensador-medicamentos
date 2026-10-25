from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

ColorMedicamento = Literal["rojo", "amarillo", "verde", "azul"]

COLORES: tuple[ColorMedicamento, ...] = ("rojo", "amarillo", "verde", "azul")

MAX_STOCK = 20


class Inventario(BaseModel):
    rojo: int = Field(ge=0)
    amarillo: int = Field(ge=0)
    verde: int = Field(ge=0)
    azul: int = Field(ge=0)


class Medicamento(BaseModel):
    color: ColorMedicamento
    nombre: str
    dosis: str
    presentacion: str
    bandeja: str
    palabras_clave: list[str] = Field(description="Términos que identifican el medicamento en voz y en recetas")


class SolicitudColor(BaseModel):
    color: ColorMedicamento
    receta_id: str | None = Field(
        default=None,
        description="Receta validada por OCR que respalda la orden. Opcional: sin ella la orden se dispensa igual.",
    )


class SolicitudReposicion(BaseModel):
    stock: dict[ColorMedicamento, Annotated[int, Field(ge=0, le=MAX_STOCK)]] = Field(
        min_length=1,
        description="Unidades que quedan en cada bandeja repuesta; las bandejas no incluidas no cambian.",
        examples=[{"rojo": 3, "azul": 2}],
    )


class MedicamentoDetectado(BaseModel):
    color: ColorMedicamento
    nombre: str
    dosis: str
    bandeja: str
    fragmento: str | None = None


class RespuestaSolicitud(BaseModel):
    status: Literal["completado"]
    color: ColorMedicamento
    inventario: Inventario
    receta_id: str | None = None


class Actividad(BaseModel):
    evento: str
    nivel: Literal["info", "success", "warning", "error"]
    timestamp: datetime


class EstadoSistema(BaseModel):
    robot_ocupado: bool
    dispensando: ColorMedicamento | None
    modo_robot: Literal["lelab", "stub"]
    colores_robot: list[ColorMedicamento] = Field(description="Bandejas que el robot sabe entregar")
    inventario: Inventario
    ultima_actividad: Actividad | None


class SolicitudVoz(BaseModel):
    texto: str = Field(min_length=1, max_length=500)


class RespuestaVoz(BaseModel):
    color: ColorMedicamento
    nombre: str
    confianza: float = Field(ge=0, le=1)
    texto_recibido: str


class ValidacionReceta(BaseModel):
    id: str
    timestamp: datetime
    color: ColorMedicamento | None = Field(description="Medicamento autorizado o, si se rechazó, el solicitado")
    medicamento: str | None
    autorizado: bool
    motivo: str
    fragmento: str | None = Field(description="Línea de la receta donde se encontró el medicamento")
    texto_ocr: str
    detectados: list[MedicamentoDetectado] = Field(
        default_factory=list,
        description="Medicamentos del catálogo leídos en la receta. Con más de uno, el kiosko deja elegir la cola.",
    )


class RegistroEntrega(BaseModel):
    timestamp: datetime
    color: ColorMedicamento
    medicamento: str
    bandeja: str
    receta_id: str | None = None


class RegistroReceta(ValidacionReceta):
    dispensada_en: datetime | None = None
    dispensados: list[ColorMedicamento] = Field(
        default_factory=list, description="Medicamentos ya entregados con esta receta"
    )
