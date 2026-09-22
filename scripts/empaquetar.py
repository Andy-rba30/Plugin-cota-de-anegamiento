#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera cota_anegamiento.zip listo para «Instalar a partir de ZIP» en QGIS.

Uso: python scripts/empaquetar.py [carpeta_salida]
"""
import os
import sys
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA = os.path.join(RAIZ, "cota_anegamiento")
EXCLUIR_DIRS = {"__pycache__"}
EXCLUIR_EXT = {".pyc", ".pyo"}


def version():
    with open(os.path.join(CARPETA, "metadata.txt"), encoding="utf-8") as f:
        for linea in f:
            if linea.startswith("version="):
                return linea.split("=", 1)[1].strip()
    return "0.0.0"


def main():
    salida_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "dist")
    os.makedirs(salida_dir, exist_ok=True)
    ruta = os.path.join(salida_dir, "cota_anegamiento.zip")
    guia = os.path.join(RAIZ, "docs", "Guia_Cota_Anegamiento.pdf")
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, archivos in os.walk(CARPETA):
            dirs[:] = [d for d in dirs if d not in EXCLUIR_DIRS]
            for a in sorted(archivos):
                if os.path.splitext(a)[1] in EXCLUIR_EXT:
                    continue
                completo = os.path.join(base, a)
                z.write(completo, os.path.relpath(completo, RAIZ))
        if os.path.exists(guia):
            z.write(guia, os.path.join("cota_anegamiento", "Guia_Cota_Anegamiento.pdf"))
        manual = os.path.join(RAIZ, "docs", "MANUAL_PARAMETROS.md")
        if os.path.exists(manual):
            z.write(manual, os.path.join("cota_anegamiento", "MANUAL_PARAMETROS.md"))
    print("Creado %s (v%s, %.0f KB)" % (ruta, version(), os.path.getsize(ruta) / 1024.0))


if __name__ == "__main__":
    main()
