from typing import Literal

from pydantic import BaseModel, Field

ColorMedicamento = Literal["rojo", "amarillo", "verde", "azul"]

COLORES: tuple[ColorMedicamento, ...] = ("rojo", "amarillo", "verde", "azul")


class Inventario(BaseModel):
    rojo: int = Field(ge=0)
    amarillo: int = Field(ge=0)
    verde: int = Field(ge=0)
    azul: int = Field(ge=0)


class SolicitudColor(BaseModel):
    color: ColorMedicamento


class RespuestaSolicitud(BaseModel):
    status: Literal["entregado"]
    color: ColorMedicamento
    inventario: Inventario
