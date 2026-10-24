# Farmacias Similares · Sistema de Dispensación Automatizada

Panel web de farmacia que controla un robot dispensador: inventario en tiempo real, órdenes de dispensación con confirmación, pedidos por voz, validación de recetas por OCR, reposición de stock y un panel de gerencia.

- **Backend:** FastAPI. Gestiona el inventario (persistido en JSON), interpreta los pedidos por voz, lee recetas con Tesseract y orquesta el robot a través de `scripts/inference.py` (stub o LeLab).
- **Frontend:** HTML, CSS y JavaScript sin dependencias, servido por el mismo backend. Kiosko en `/` y panel de gerencia en `/gerente.html`.

## Requisitos

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) con el idioma español, solo para validar recetas (sin él, el resto funciona y `POST /validar-receta` responde `503`):
  - Linux: `sudo apt install -y tesseract-ocr tesseract-ocr-spa`
  - macOS: `brew install tesseract tesseract-lang`
- Google Chrome o Microsoft Edge para el pedido por voz (Web Speech API; necesita internet y abrir la web en `localhost` o HTTPS).

## Guía rápida Linux (compañero con robot)

Copiar y pegar en **Ubuntu / Debian** (ajusta la ruta del repo si clonaste en otro sitio).

**Una sola vez — dependencias del sistema y entorno Python:**

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git tesseract-ocr tesseract-ocr-spa

cd ~/dispensador-medicamentos   # o la carpeta donde tengáis el proyecto
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Si `python3 -m venv .venv` falla, instala el paquete `python3-venv` (comando `apt` de arriba).

**LeLab** (aparte de este repo; quien tenga el brazo USB):

```bash
# requiere https://docs.astral.sh/uv/getting-started/installation/
uv tool install git+https://github.com/huggingface/leLab.git
lelab   # escucha en http://127.0.0.1:8000
```

Revisa en `data/lelab_inference.json` el `follower_port` (p. ej. `/dev/ttyACM0` o `/dev/ttyACM1`) y los `camera_index` según `lerobot-find-port` / las cámaras en LeLab.

**Cada vez que vayan a probar — dos terminales:**

```bash
# Terminal 1 (misma máquina que el robot)
lelab
```

```bash
# Terminal 2
cd ~/dispensador-medicamentos
source .venv/bin/activate
export USE_LELAB=1
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8080
```

Abrir en el navegador: **http://localhost:8080** (no uses el 8000: ese es LeLab).

Prueba sin la web (terminal 2, con LeLab ya encendido):

```bash
source .venv/bin/activate
export USE_LELAB=1
python scripts/inference.py --lelab --color azul
```

**Errores frecuentes en Linux**

| Mensaje | Qué hacer |
|---------|-----------|
| No existe `.venv` | Ejecutar otra vez `python3 -m venv .venv` y `pip install -r requirements.txt` dentro del repo |
| `uvicorn: command not found` | `source .venv/bin/activate` o usar `.venv/bin/uvicorn ...` |
| No se pudo conectar a LeLab | Terminal 1: `lelab` debe estar corriendo antes de dispensar |
| Permiso denegado en `/dev/ttyACM*` | `sudo usermod -aG dialout $USER` y cerrar sesión, o reglas udev del SO-101 |
| `Form data requires "python-multipart"` al arrancar | Faltan dependencias nuevas: `pip install -r requirements.txt` |
| *Tesseract no está instalado* al validar receta | `sudo apt install -y tesseract-ocr tesseract-ocr-spa` |
| Voz: *El reconocimiento de voz necesita internet* | Usar Google Chrome (Chromium de Linux no trae el servicio de voz) |

## Instalación

```bash
cd dispensador-medicamentos
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Arranque (un solo puerto: API + web)

LeLab usa el puerto **8000** por defecto. Con robot real, arranca primero LeLab y la farmacia en **otro puerto**:

```bash
# Terminal 1 — robot + modelo (LeLab)
lelab

# Terminal 2 — panel de farmacia (desde la raíz del repo)
cd dispensador-medicamentos
python3 -m venv .venv          # solo la primera vez
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt   # solo la primera vez
export USE_LELAB=1
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8080
```

Sin activar el venv puedes usar la ruta directa:

```bash
export USE_LELAB=1
.venv/bin/uvicorn backend.main:app --reload --host 0.0.0.0 --port 8080
```

Sin LeLab (stub de 2–4 s), con el venv activado:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- **Kiosko:** http://localhost:8080/ (con LeLab) o http://localhost:8000/ (solo stub)
- **Panel de gerencia:** mismo host, ruta `/gerente.html`
- **Documentación de la API (Swagger):** mismo host, ruta `/docs`

En la red local del hackathon, usa la IP de tu máquina: `http://<tu-ip>:8080`

## Interfaz

| Zona | Qué muestra |
|------|-------------|
| Cabecera | Marca, sucursal, fecha y hora, e indicador *Sistema en línea* / *Sin conexión* |
| Inventario | Medicamento, bandeja, existencias con barra de nivel y estado (*Disponible*, *Stock bajo* con 1 unidad, *Agotado*). El botón **Reponer stock** abre un formulario donde se marcan las bandejas repuestas y se indican sus unidades |
| Nueva dispensación | **Pedir por voz**, **Escanear receta**, selección del medicamento, botón de confirmación y progreso en tres pasos con cronómetro |
| Registro de actividad | Órdenes, pedidos por voz, recetas, entregas, fallos y cortes de conexión de la sesión |
| Panel de gerencia (`/gerente.html`) | Inventario, estado del robot (disponible / dispensando, modo LeLab o simulación, última actividad) e historial persistente de recetas validadas por la IA |

### Kiosko: voz y receta (opcionales)

El botón **Dispensar** funciona igual que antes; la voz y la receta son ayudas que se pueden usar o no.

1. **Pedir por voz:** el navegador transcribe lo que dice el paciente (Web Speech API, `es-ES`) y el backend lo interpreta (`POST /interpretar-voz`). Reconoce el nombre del medicamento aunque se pronuncie o transcriba con errores («omeprasol»), marcas comunes («Tylenol», «Advil») y el color de la bandeja («el azul»). Solo **preselecciona** el medicamento: la orden se confirma con **Dispensar**.
2. **Escanear receta:** abre la cámara (en móvil/tablet) o el selector de archivos, muestra la foto y **Validar con IA** la envía a `POST /validar-receta`. Tesseract lee el texto y se busca el medicamento:
   - Con un medicamento seleccionado, se autoriza si la receta lo incluye.
   - Sin selección, se autoriza el medicamento que indique la receta y se preselecciona.
   - Si se rechaza, se muestra el motivo y el texto leído para que el personal lo revise.
3. Al dispensar con una receta autorizada para ese medicamento, la orden la adjunta (`receta_id`). El backend comprueba que sea del mismo medicamento, que no se haya usado antes y que tenga menos de 15 minutos; si no, responde `409` y el robot no se mueve.

Cada validación queda en `data/recetas.jsonl` (no se sube a git porque contiene texto de recetas reales). Las imágenes no se guardan.

### Catálogo

Los medicamentos de cada bandeja y las palabras clave que los identifican en voz y recetas están en [`backend/medicamentos.py`](backend/medicamentos.py); el kiosko y el panel de gerencia los leen de `GET /medicamentos`. El campo `color` debe coincidir con el que usan la API y el robot:

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
| `GET` | `/medicamentos` | Catálogo: nombre, dosis, bandeja y palabras clave de cada `color` |
| `GET` | `/estado` | Robot ocupado o libre, orden en curso, modo (`lelab` / `stub`), inventario y última actividad |
| `POST` | `/solicitar` | Body: `{"color": "rojo"}` o `{"color": "rojo", "receta_id": "…"}`. Ejecuta el robot y descuenta 1 unidad si la entrega tiene éxito |
| `POST` | `/reponer` | Body: `{"stock": {"rojo": 1, "azul": 5}}`. Fija las unidades (0–20) de las bandejas indicadas; las demás no cambian. Sin body, devuelve todas al stock inicial (1). Responde `409` si hay una dispensación en curso |
| `POST` | `/interpretar-voz` | Body: `{"texto": "quiero paracetamol"}`. Devuelve el `color` reconocido y la confianza; `422` si no hay un único medicamento claro |
| `POST` | `/validar-receta` | `multipart/form-data` con `imagen` y, opcional, `color`. Devuelve `autorizado`, `motivo`, el fragmento detectado y el texto leído; `422` si no es una imagen, `413` si supera 10 MB, `503` si falta Tesseract |
| `GET` | `/recetas?limit=50` | Historial de validaciones, la más reciente primero, con la hora de dispensación si se usó |

Respuestas de `POST /solicitar`:

| Código | Significado |
|--------|-------------|
| `200` | Entregado; devuelve el inventario actualizado |
| `409` | Sin stock de ese color, dispensador ocupado, o `receta_id` no válida (inexistente, rechazada, de otro medicamento, ya usada o caducada) |
| `422` | Color no válido |
| `502` | El robot / script de inferencia falló (el stock no cambia) |
| `504` | El robot no respondió a tiempo (el stock no cambia) |
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
| `OCR_LANG` | `spa` | Idioma de Tesseract para las recetas (si falta el paquete `spa`, usa `eng`) |

El campo `tasks_by_color` en el JSON permite un `task` distinto por bandeja si el modelo es language-conditioned; con ACT suele dejarse `""`.

> Cada orden lanza de nuevo el rollout en LeLab (hasta `duration_s`, p. ej. 60 s). Cierra vistas de cámara en LeLab antes de dispensar desde la web.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Cubren la dispensación correcta y su persistencia, color inválido, falta de stock, fallo y timeout del robot, órdenes simultáneas (incluida la última unidad), inventario corrupto, escritura atómica y permisos del archivo, reposición de stock, el script de inferencia real, la interpretación de voz, la validación de recetas (con el OCR simulado, no hace falta Tesseract), el historial de recetas y el uso de `receta_id` al dispensar.

## Guion de demo (presentación)

1. Abrir la farmacia (http://localhost:8080 con LeLab + robot, o http://localhost:8000 solo con stub). El indicador muestra *Sistema en línea* y el registro, *Sistema iniciado*.
2. Señalar el inventario: cuatro medicamentos con existencias y estado, sincronizados cada 2 s.
3. Seleccionar **Omeprazol 20 mg** y pulsar **Dispensar Omeprazol 20 mg**. Mientras el robot trabaja se ven los pasos *Orden registrada → Dispensando → Entregado* con cronómetro; al terminar, la fila del inventario se resalta y las existencias bajan.
4. Pulsar **Pedir por voz** y decir «Quiero paracetamol»: se preselecciona *Paracetamol 500 mg*.
5. Pulsar **Escanear receta**, fotografiar una receta impresa que diga «Paracetamol 500 mg» y **Validar con IA**: aparece *Receta validada por IA* con el fragmento leído. Dispensar: la orden sale con la receta adjunta.
6. Abrir **Vista gerente** en otra pestaña o pantalla: el inventario baja, el robot pasa a *Dispensando* y la receta aparece en el historial como autorizada y dispensada.
7. Opcional: escanear una receta de otro medicamento para enseñar el rechazo, dispensar hasta dejar una bandeja *Agotado* y reponerla desde **Reponer stock**.
8. Opcional: abrir `/docs` para mostrar la API.

Consejo para la receta: texto impreso, buena luz y la hoja ocupando toda la foto. Tesseract lee mal la letra manuscrita.

Antes de presentar, abre **Reponer stock**, marca **Seleccionar todas** y confirma para empezar con todas las bandejas llenas.

## Estructura

```
backend/     FastAPI: API, inventario, catálogo, voz, OCR de recetas y ejecución del robot
frontend/    index.html + app.js (kiosko), gerente.html + gerente.js (gerencia),
             comun.js, styles.css, logo-simi.png, favicon.png
scripts/     inference.py (stub del robot / puente a LeLab)
data/        inventario.json, lelab_inference.json, recetas.jsonl (se crea al validar)
tests/       tests de la API (pytest)
```
