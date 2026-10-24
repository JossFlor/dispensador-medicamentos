import io
import os
from dataclasses import dataclass

from backend import medicamentos
from backend.schemas import ColorMedicamento, Medicamento

OCR_LANG = os.environ.get("OCR_LANG", "spa")
ANCHO_MINIMO = 1200
ANCHO_MAXIMO = 2400


class OCRNoDisponible(RuntimeError):
    pass


class ImagenInvalida(ValueError):
    pass


@dataclass
class Evaluacion:
    autorizado: bool
    medicamento: Medicamento | None
    motivo: str
    fragmento: str | None


def extraer_texto(datos: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as e:
        raise OCRNoDisponible("Faltan dependencias de OCR. Ejecute: pip install -r requirements.txt") from e

    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ImagenInvalida("El archivo no es una imagen válida.") from e

    img = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(img)))
    if img.width < ANCHO_MINIMO or img.width > ANCHO_MAXIMO:
        ancho = max(ANCHO_MINIMO, min(img.width, ANCHO_MAXIMO))
        img = img.resize((ancho, round(img.height * ancho / img.width)), Image.LANCZOS)

    try:
        return pytesseract.image_to_string(img, lang=OCR_LANG)
    except pytesseract.TesseractNotFoundError as e:
        raise OCRNoDisponible(
            "Tesseract no está instalado. Linux: sudo apt install tesseract-ocr tesseract-ocr-spa"
        ) from e
    except pytesseract.TesseractError as e:
        if OCR_LANG == "eng":
            raise OCRNoDisponible(f"Tesseract falló: {e}") from e
    # The Spanish language pack is missing; drug names are Latin script, so English still reads them.
    try:
        return pytesseract.image_to_string(img, lang="eng")
    except pytesseract.TesseractError as e:
        raise OCRNoDisponible(f"Tesseract falló: {e}") from e


def _fragmento(texto: str, med: Medicamento) -> str | None:
    for linea in texto.splitlines():
        if medicamentos.mejor_coincidencia(linea, med) >= medicamentos.SIMILITUD_MINIMA:
            return " ".join(linea.split())[:160]
    return None


def evaluar(texto: str, color: ColorMedicamento | None) -> Evaluacion:
    if not texto.strip():
        pedido = medicamentos.por_color(color) if color else None
        return Evaluacion(
            False, pedido, "No se pudo leer texto en la imagen. Acerque la receta y use buena luz.", None
        )

    encontrados = [med for med, _ in medicamentos.detectar(texto)]

    if color:
        pedido = medicamentos.por_color(color)
        if pedido in encontrados:
            return Evaluacion(True, pedido, f"La receta incluye {pedido.nombre}.", _fragmento(texto, pedido))
        if encontrados:
            otros = ", ".join(med.nombre for med in encontrados)
            return Evaluacion(False, pedido, f"La receta indica {otros}, no {pedido.nombre}.", None)
        return Evaluacion(False, pedido, f"No se encontró {pedido.nombre} en la receta.", None)

    if not encontrados:
        return Evaluacion(False, None, "No se reconoció ningún medicamento del catálogo en la receta.", None)
    if len(encontrados) > 1:
        nombres = " y ".join(med.nombre for med in encontrados)
        return Evaluacion(
            False, None, f"La receta incluye {nombres}. Seleccione cuál dispensar y vuelva a validar.", None
        )
    med = encontrados[0]
    return Evaluacion(True, med, f"La receta incluye {med.nombre}.", _fragmento(texto, med))
