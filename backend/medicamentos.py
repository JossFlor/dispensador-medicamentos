import re
import unicodedata
from difflib import SequenceMatcher

from backend.schemas import ColorMedicamento, Medicamento

# Every term must be written already normalized (lowercase, no accents).
MEDICAMENTOS: tuple[Medicamento, ...] = (
    Medicamento(
        color="rojo",
        nombre="Paracetamol",
        dosis="500 mg",
        presentacion="Comprimidos",
        bandeja="Bandeja A · Roja",
        palabras_clave=["paracetamol", "acetaminofen", "tempra", "tylenol"],
    ),
    Medicamento(
        color="amarillo",
        nombre="Ibuprofeno",
        dosis="400 mg",
        presentacion="Comprimidos",
        bandeja="Bandeja B · Amarilla",
        palabras_clave=["ibuprofeno", "ibuprofen", "advil", "motrin"],
    ),
    Medicamento(
        color="verde",
        nombre="Amoxicilina",
        dosis="500 mg",
        presentacion="Cápsulas",
        bandeja="Bandeja C · Verde",
        palabras_clave=["amoxicilina", "amoxicillin", "amoxil"],
    ),
    Medicamento(
        color="azul",
        nombre="Omeprazol",
        dosis="20 mg",
        presentacion="Cápsulas",
        bandeja="Bandeja D · Azul",
        palabras_clave=["omeprazol", "omeprazole", "prilosec"],
    ),
)

_POR_COLOR = {m.color: m for m in MEDICAMENTOS}

# Speech recognition and OCR both misspell drug names ("omeprasol", "amoxicilna"),
# so words are compared by similarity instead of exact equality.
SIMILITUD_MINIMA = 0.8


def por_color(color: ColorMedicamento) -> Medicamento:
    return _POR_COLOR[color]


def normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_acentos.lower()


def palabras(texto: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalizar(texto))


def similitud(palabra: str, med: Medicamento) -> float:
    if len(palabra) < 4:
        return 0.0
    return max(SequenceMatcher(None, palabra, clave).ratio() for clave in med.palabras_clave)


def mejor_coincidencia(texto: str, med: Medicamento) -> float:
    return max((similitud(p, med) for p in palabras(texto)), default=0.0)


def detectar(texto: str) -> list[tuple[Medicamento, float]]:
    """Medicamentos mencionados en el texto, de mayor a menor similitud."""
    encontrados = []
    for med in MEDICAMENTOS:
        score = mejor_coincidencia(texto, med)
        if score >= SIMILITUD_MINIMA:
            encontrados.append((med, score))
    return sorted(encontrados, key=lambda par: par[1], reverse=True)
