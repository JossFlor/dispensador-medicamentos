# Farmacias Similares · Sistema de Dispensación Automatizada

Panel web de farmacia que controla un robot dispensador: inventario en tiempo real, órdenes de dispensación con confirmación, reposición de stock y registro de actividad.

- **Backend:** FastAPI. Gestiona el inventario (persistido en JSON) y orquesta el robot a través de `scripts/inference.py` (stub sustituible por Hugging Face / LeRobot).
- **Frontend:** HTML, CSS y JavaScript sin dependencias, servido por el mismo backend.

## Requisitos

- Python 3.10+

## Instalación

```bash
cd dispensador-medicamentos
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Arranque (un solo puerto: API + web)

Desde la raíz del proyecto:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- **Interfaz:** http://localhost:8000/
- **Documentación de la API (Swagger):** http://localhost:8000/docs

En la red local del hackathon, usa la IP de tu máquina: `http://<tu-ip>:8000`

## Interfaz

| Zona | Qué muestra |
|------|-------------|
| Cabecera | Marca, sucursal, fecha y hora, e indicador *Sistema en línea* / *Sin conexión* |
| Inventario | Medicamento, bandeja, existencias con barra de nivel y estado (*Disponible*, *Stock bajo* con 1 unidad, *Agotado*). El botón **Reponer stock** abre un formulario donde se marcan las bandejas repuestas y se indican sus unidades |
| Nueva dispensación | Selección del medicamento, botón de confirmación y progreso en tres pasos con cronómetro |
| Registro de actividad | Órdenes, entregas, fallos y cortes de conexión de la sesión |

Los medicamentos asociados a cada bandeja se configuran en la lista `MEDICAMENTOS` al principio de [`frontend/app.js`](frontend/app.js). El campo `color` debe coincidir con el que usan la API y el robot:

| Bandeja | `color` | Medicamento (demo) |
|---------|---------|--------------------|
| A · Roja | `rojo` | Paracetamol 500 mg |
| B · Amarilla | `amarillo` | Ibuprofeno 400 mg |
| C · Verde | `verde` | Amoxicilina 500 mg |
| D · Azul | `azul` | Omeprazol 20 mg |

## API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/inventario` | Stock actual (`rojo`, `amarillo`, `verde`, `azul`) |
| `POST` | `/solicitar` | Body: `{"color": "rojo"}`. Ejecuta el robot y descuenta 1 unidad si la entrega tiene éxito |
| `POST` | `/reponer` | Body: `{"stock": {"rojo": 3, "azul": 5}}`. Fija las unidades (0–20) de las bandejas indicadas; las demás no cambian. Sin body, devuelve todas al stock inicial (3). Responde `409` si hay una dispensación en curso |

Respuestas de `POST /solicitar`:

| Código | Significado |
|--------|-------------|
| `200` | Entregado; devuelve el inventario actualizado |
| `409` | Sin stock de ese color, o el dispensador está ocupado con otra orden |
| `422` | Color no válido |
| `502` | El robot / script de inferencia falló (el stock no cambia) |
| `504` | El robot no respondió en 120 s (el stock no cambia) |
| `500` | `data/inventario.json` está corrupto o tiene valores inválidos |

Garantías del backend:

- **Una orden a la vez:** solo hay un robot físico, así que mientras se dispensa cualquier otra orden recibe `409` al instante, en lugar de mover el robot dos veces en paralelo.
- **El stock solo baja si la entrega tiene éxito.**
- **Persistencia segura:** el inventario se guarda en [`data/inventario.json`](data/inventario.json) con escritura atómica, de modo que un corte a mitad de escritura no deja el archivo dañado. Si se borra el archivo, se recrea con 3 unidades por bandeja; si está dañado, `POST /reponer` lo restablece.

## Stub de inferencia

```bash
python scripts/inference.py --color azul
python scripts/inference.py --color rojo --fail   # simula fallo (stock no baja vía API)
```

Para integrar el robot real, edita [`scripts/inference.py`](scripts/inference.py) manteniendo el argumento `--color` y el contrato: código de salida `0` si la entrega tuvo éxito y distinto de `0` (con el motivo en stderr) si falló.

> El backend lanza un proceso nuevo por cada orden. Con el stub no importa, pero si el robot real carga un modelo pesado (Hugging Face / LeRobot), cárgalo una sola vez en un proceso persistente en lugar de en cada llamada, o cada dispensación pagará el tiempo de carga del modelo.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Cubren la dispensación correcta y su persistencia, color inválido, falta de stock, fallo y timeout del robot, órdenes simultáneas (incluida la última unidad), inventario corrupto, escritura atómica y permisos del archivo, reposición de stock y el script de inferencia real.

## Guion de demo (presentación)

1. Abrir http://localhost:8000. El indicador muestra *Sistema en línea* y el registro, *Sistema iniciado*.
2. Señalar el inventario: cuatro medicamentos con existencias y estado, sincronizados cada 2 s.
3. Seleccionar **Omeprazol 20 mg** y pulsar **Dispensar Omeprazol 20 mg**. Mientras el robot trabaja se ven los pasos *Orden registrada → Dispensando → Entregado* con cronómetro; al terminar, la fila del inventario se resalta y las existencias bajan.
4. Opcional: dispensar hasta dejar una bandeja en *Stock bajo* o *Agotado* para enseñar las alertas, y reponerla desde **Reponer stock**.
5. Opcional: abrir `/docs` y probar `POST /solicitar` para mostrar la API.
6. Reiniciar el servidor y comprobar que el stock guardado se mantiene.

Antes de presentar, abre **Reponer stock**, marca **Seleccionar todas** y confirma para empezar con todas las bandejas llenas.

## Estructura

```
backend/     FastAPI: API, inventario y ejecución del robot
frontend/    index.html, styles.css, app.js, logo-simi.png, favicon.png
             (doctor-simi-logo.jpeg es la imagen original del logo)
scripts/     inference.py (stub del robot)
data/        inventario.json
tests/       tests de la API (pytest)
```
