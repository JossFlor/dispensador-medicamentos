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

LeLab usa el puerto **8000** por defecto. Con robot real, arranca primero LeLab y la farmacia en **otro puerto**:

```bash
# Terminal 1 — robot + modelo (LeLab)
lelab

# Terminal 2 — panel de farmacia
export USE_LELAB=1
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8080
```

Sin LeLab (stub de 2–4 s):

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- **Interfaz:** http://localhost:8080/ (con LeLab) o http://localhost:8000/ (solo stub)
- **Documentación de la API (Swagger):** mismo host, ruta `/docs`

En la red local del hackathon, usa la IP de tu máquina: `http://<tu-ip>:8080`

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
| `POST` | `/reponer` | Body: `{"stock": {"rojo": 1, "azul": 5}}`. Fija las unidades (0–20) de las bandejas indicadas; las demás no cambian. Sin body, devuelve todas al stock inicial (1). Responde `409` si hay una dispensación en curso |

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
- **Persistencia segura:** el inventario se guarda en [`data/inventario.json`](data/inventario.json) con escritura atómica, de modo que un corte a mitad de escritura no deja el archivo dañado. Si se borra el archivo, se recrea con 1 unidad por bandeja; si está dañado, `POST /reponer` lo restablece.

## Inferencia: stub o LeLab

**Stub** (sin hardware):

```bash
python scripts/inference.py --color azul
python scripts/inference.py --color rojo --fail   # simula fallo (stock no baja vía API)
```

**LeLab** (mismo cuerpo que el botón *Start Inference* en LeLab):

1. Copia [`data/lelab_inference.json.example`](data/lelab_inference.json.example) a `data/lelab_inference.json` y ajusta puerto USB / índices de cámara si cambian.
2. Con `lelab` en marcha en `http://127.0.0.1:8000`:

```bash
export USE_LELAB=1
python scripts/inference.py --lelab --color azul
```

Variables útiles:

| Variable | Valor por defecto | Uso |
|----------|-------------------|-----|
| `USE_LELAB` | (vacío → stub) | `1` para disparar `POST /start-inference` en LeLab |
| `LELAB_URL` | `http://127.0.0.1:8000` | URL del backend LeLab |
| `LELAB_CONFIG` | `data/lelab_inference.json` | Payload de inferencia |
| `INFERENCE_TIMEOUT` | `200` con LeLab, `120` sin | Segundos máximos por orden en el backend |

El campo `tasks_by_color` en el JSON permite un `task` distinto por bandeja si el modelo es language-conditioned; con ACT suele dejarse `""`.

> Cada orden lanza de nuevo el rollout en LeLab (hasta `duration_s`, p. ej. 60 s). Cierra vistas de cámara en LeLab antes de dispensar desde la web.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Cubren la dispensación correcta y su persistencia, color inválido, falta de stock, fallo y timeout del robot, órdenes simultáneas (incluida la última unidad), inventario corrupto, escritura atómica y permisos del archivo, reposición de stock y el script de inferencia real.

## Guion de demo (presentación)

1. Abrir la farmacia (http://localhost:8080 con LeLab + robot, o http://localhost:8000 solo con stub). El indicador muestra *Sistema en línea* y el registro, *Sistema iniciado*.
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
