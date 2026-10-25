import io
import os
import shutil
import sys
from dataclasses import dataclass

from backend import medicamentos
from backend.schemas import ColorMedicamento, Medicamento

OCR_LANG = os.environ.get("OCR_LANG", "spa")
ANCHO_MINIMO = 1200
ANCHO_MAXIMO = 2400
_RUTAS_TESSERACT = ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract")


def _mensaje_instalacion() -> str:
    if sys.platform == "darwin":
        return "Tesseract no está instalado. En el Mac: brew install tesseract tesseract-lang"
    return "Tesseract no está instalado. Linux: sudo apt install tesseract-ocr tesseract-ocr-spa"


def _asegurar_binario() -> None:
    import pytesseract

    if shutil.which("tesseract"):
        return
    for ruta in _RUTAS_TESSERACT:
        if os.path.isfile(ruta):
            pytesseract.pytesseract.tesseract_cmd = ruta
            return


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
    detectados: list[Medicamento]


def extraer_texto(datos: bytes) -> str:
    if _es_pdf(datos):
        return _texto_pdf(datos)
    return _texto_imagen(datos)


def _es_pdf(datos: bytes) -> bool:
    return b"%PDF" in datos[:1024]


def _texto_imagen(datos: bytes) -> str:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as e:
        raise OCRNoDisponible("Faltan dependencias de OCR. Ejecute: pip install -r requirements.txt") from e
    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ImagenInvalida("El archivo no es una imagen ni un PDF válido.") from e
    return _ocr_pil(img)


def _texto_pdf(datos: bytes) -> str:
    """Digital PDFs are read as text. A scan, with no text layer, is rendered and passed to OCR."""
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise OCRNoDisponible("Faltan dependencias de OCR. Ejecute: pip install -r requirements.txt") from e
    try:
        doc = pdfium.PdfDocument(datos)
    except Exception as e:
        raise ImagenInvalida("El archivo no es un PDF válido.") from e
    try:
        total = len(doc)
        if total == 0:
            raise ImagenInvalida("El PDF no tiene páginas.")
        n = min(total, 2)
        textos = [_texto_pagina(doc[i]) for i in range(n)]
        texto = "\n".join(textos)
        if len("".join(texto.split())) >= 8:
            return texto
        return "\n".join(_ocr_pil(_render_pagina(doc[i])) for i in range(n))
    finally:
        doc.close()


def _texto_pagina(page) -> str:
    textpage = page.get_textpage()
    try:
        return textpage.get_text_bounded() or ""
    finally:
        textpage.close()
        page.close()


def _render_pagina(page):
    bitmap = page.render(scale=2)
    try:
        return bitmap.to_pil()
    finally:
        bitmap.close()
        page.close()


def _ocr_pil(img) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError as e:
        raise OCRNoDisponible("Faltan dependencias de OCR. Ejecute: pip install -r requirements.txt") from e

    img = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(img)))
    if img.width < ANCHO_MINIMO or img.width > ANCHO_MAXIMO:
        ancho = max(ANCHO_MINIMO, min(img.width, ANCHO_MAXIMO))
        img = img.resize((ancho, round(img.height * ancho / img.width)), Image.LANCZOS)

    _asegurar_binario()
    try:
        return pytesseract.image_to_string(img, lang=OCR_LANG)
    except pytesseract.TesseractNotFoundError as e:
        raise OCRNoDisponible(_mensaje_instalacion()) from e
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
            False, pedido, "No se pudo leer texto en la receta. Acerque la foto o suba un PDF con texto seleccionable.", None, []
        )

    encontrados = [med for med, _ in medicamentos.detectar(texto)]

    if color:
        pedido = medicamentos.por_color(color)
        if pedido in encontrados:
            return Evaluacion(True, pedido, f"La receta incluye {pedido.nombre}.", _fragmento(texto, pedido), encontrados)
        if encontrados:
            otros = ", ".join(med.nombre for med in encontrados)
            return Evaluacion(False, pedido, f"La receta indica {otros}, no {pedido.nombre}.", None, encontrados)
        return Evaluacion(False, pedido, f"No se encontró {pedido.nombre} en la receta.", None, [])

    if not encontrados:
        return Evaluacion(False, None, "No se reconoció ningún medicamento del catálogo en la receta.", None, [])
    if len(encontrados) > 1:
        nombres = " y ".join(med.nombre for med in encontrados)
        return Evaluacion(True, None, f"La receta incluye {nombres}.", None, encontrados)
    med = encontrados[0]
    return Evaluacion(True, med, f"La receta incluye {med.nombre}.", _fragmento(texto, med), encontrados)
