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


class SolicitudColor(BaseModel):
    color: ColorMedicamento


class SolicitudReposicion(BaseModel):
    stock: dict[ColorMedicamento, Annotated[int, Field(ge=0, le=MAX_STOCK)]] = Field(
        min_length=1,
        description="Unidades que quedan en cada bandeja repuesta; las bandejas no incluidas no cambian.",
        examples=[{"rojo": 3, "azul": 2}],
    )


class RespuestaSolicitud(BaseModel):
    status: Literal["entregado"]
    color: ColorMedicamento
    inventario: Inventario
