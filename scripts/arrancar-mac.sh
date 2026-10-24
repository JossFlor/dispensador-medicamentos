#!/bin/bash
# Prepara el Mac como respaldo de la laptop Linux: mismo modelo, puerto USB de este equipo.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG="data/lelab_inference.mac.json"
PORT="$(ls /dev/cu.usbmodem* 2>/dev/null | head -1 || true)"

echo "Farmacia (este proyecto): .venv listo"
echo "Tesseract: $(command -v tesseract || echo 'FALTA: brew install tesseract tesseract-lang')"
echo "LeLab: $(command -v lelab || echo 'FALTA: uv tool install git+https://github.com/huggingface/leLab.git')"

if [[ -z "$PORT" ]]; then
  echo
  echo "No hay brazo USB. Enchufa el SO-101 y vuelve a ejecutar este script."
  echo "Puertos serie ahora:"
  ls /dev/cu.* 2>/dev/null || true
else
  python3 - "$CONFIG" "$PORT" <<'PY'
import json, sys
path, port = sys.argv[1], sys.argv[2]
data = json.loads(open(path, encoding="utf-8").read())
data["follower_port"] = port
open(path, "w", encoding="utf-8").write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(f"Puerto del brazo guardado en {path}: {port}")
PY
fi

echo
echo "Cámaras: en Linux eran índice 4 (Robot) y 2 (Webcam). En el Mac cambian."
echo "Ábrelas una vez en LeLab (Configure Inference) y, si no coinciden, edita camera_index en $CONFIG."
echo
echo "Terminal 1 — robot:"
echo "  lelab"
echo
echo "Terminal 2 — farmacia (Chrome, http://localhost:8080):"
echo "  cd $(pwd)"
echo "  source .venv/bin/activate"
echo "  export USE_LELAB=1"
echo "  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8080"
