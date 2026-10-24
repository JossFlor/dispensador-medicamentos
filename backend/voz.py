from backend import medicamentos
from backend.schemas import ColorMedicamento, Medicamento

# Patients often ask by tray colour ("el azul") instead of by drug name.
COLORES_HABLADOS: dict[str, ColorMedicamento] = {
    "rojo": "rojo",
    "roja": "rojo",
    "amarillo": "amarillo",
    "amarilla": "amarillo",
    "verde": "verde",
    "azul": "azul",
}
CONFIANZA_POR_COLOR = 0.7


class VozNoReconocida(ValueError):
    pass


def interpretar(texto: str) -> tuple[Medicamento, float]:
    encontrados = medicamentos.detectar(texto)
    if len(encontrados) > 1:
        nombres = " y ".join(med.nombre for med, _ in encontrados)
        raise VozNoReconocida(f"Se mencionó más de un medicamento ({nombres}). Pida uno cada vez.")
    if encontrados:
        med, score = encontrados[0]
        return med, round(score, 2)

    colores = {COLORES_HABLADOS[p] for p in medicamentos.palabras(texto) if p in COLORES_HABLADOS}
    if len(colores) == 1:
        return medicamentos.por_color(colores.pop()), CONFIANZA_POR_COLOR
    raise VozNoReconocida("No se reconoció ningún medicamento. Diga, por ejemplo, «Paracetamol».")
