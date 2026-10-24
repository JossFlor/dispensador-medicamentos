#!/usr/bin/env bash
# Ubuntu: duplica la Webcam fija para que LeLab y el validador la lean a la vez.
#   LeLab (Webcam)  -> /dev/video10   (camera_index 10 en data/lelab_inference.json)
#   Validador       -> /dev/video11   (live_index 11 en data/vision.json)
# Requiere: sudo apt install v4l2loopback-dkms ffmpeg v4l-utils
# Déjalo corriendo en su propia terminal mientras se usa el robot.
set -euo pipefail

ORIGEN="${1:-/dev/video2}"
FORMATO="${FORMATO:-mjpeg}"

if [ ! -e /dev/video10 ] || [ ! -e /dev/video11 ]; then
  sudo modprobe -r v4l2loopback 2>/dev/null || true
  sudo modprobe v4l2loopback devices=2 video_nr=10,11 card_label="LeLab Webcam","Validador cubo" exclusive_caps=1
fi

echo "Compartiendo $ORIGEN -> /dev/video10 (LeLab) y /dev/video11 (validador). Ctrl+C para parar."
exec ffmpeg -hide_banner -loglevel warning \
  -f v4l2 -input_format "$FORMATO" -video_size 640x480 -framerate 30 -i "$ORIGEN" \
  -map 0:v -pix_fmt yuyv422 -f v4l2 /dev/video10 \
  -map 0:v -pix_fmt yuyv422 -f v4l2 /dev/video11
