#!/usr/bin/env python3
"""Stub de inferencia / robot. Sustituir por Hugging Face o LeRobot manteniendo --color."""

import argparse
import random
import sys
import time

VALID_COLORS = ("rojo", "amarillo", "verde", "azul")


def main() -> int:
    parser = argparse.ArgumentParser(description="Entrega simulada de medicamento por color.")
    parser.add_argument(
        "--color",
        required=True,
        choices=VALID_COLORS,
        help="Color del cubo a entregar",
    )
    parser.add_argument(
        "--fail",
        action="store_true",
        help="Simular fallo del robot (para pruebas del backend)",
    )
    args = parser.parse_args()

    delay = random.uniform(2.0, 4.0)
    time.sleep(delay)

    if args.fail:
        print(f"Error: no se pudo entregar cubo {args.color}", file=sys.stderr)
        return 1

    print(f"Entregando cubo {args.color}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
