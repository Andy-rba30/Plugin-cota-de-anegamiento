# -*- coding: utf-8 -*-
import math
import os

import numpy as np
import pytest

from cota_anegamiento import herramientas as h

GT = (500000.0, 5.0, 0.0, 9400000.0, 0.0, -5.0)


def test_celda_xy_ida_y_vuelta():
    f, c = h.celda_de_xy(500012.0, 9399988.0, GT)
    assert (f, c) == (2, 2)
    x, y = h.xy_de_celda(2, 2, GT)
    assert (x, y) == (500012.5, 9399987.5)


def test_mascara_polilineas_sin_fugas_diagonales():
    m = h.mascara_polilineas([[(500000.0, 9400000.0), (500050.0, 9399950.0)]], GT, (12, 12))
    assert m.any()
    # cada paso diagonal debe tener un vecino ortogonal marcado (conectividad 4)
    filas, cols = np.nonzero(m)
    for f, c in zip(filas, cols):
        vecinos = [(f + 1, c), (f - 1, c), (f, c + 1), (f, c - 1)]
        ok = any(0 <= a < 12 and 0 <= b < 12 and m[a, b] for a, b in vecinos)
        assert ok


def test_muestrear_polilineas():
    pts = h.muestrear_polilineas([[(0.0, 0.0), (100.0, 0.0)]], 20.0)
    progs = [p[0] for p in pts]
    assert progs == [0, 20, 40, 60, 80, 100]
    assert pts[-1][1] == 100.0
    # dos polilíneas: la progresiva continúa
    pts2 = h.muestrear_polilineas([[(0.0, 0.0), (50.0, 0.0)], [(0.0, 0.0), (0.0, 30.0)]], 25.0)
    assert [p[0] for p in pts2] == [0, 25, 50, 50, 75, 80]


def test_perfil_eje_y_tramos():
    dem = np.full((10, 10), 100.0)
    cota_sin = np.full((10, 10), np.nan)
    cota_sin[5, 5] = 101.2
    muestras = [(0.0, 500002.5, 9399997.5), (20.0, 500027.5, 9399972.5), (40.0, 500047.5, 9399952.5)]
    perfil = h.perfil_eje(muestras, GT, dem, cota_sin, None, radio_m=0.0, y_lamina=0.0, borde_libre=0.5)
    assert len(perfil) == 3
    assert perfil[0]["control"] == "Sin anegamiento"
    assert perfil[1]["control"] == "Pluvial sin vía"
    assert perfil[1]["cota_diseno"] == 101.2
    assert perfil[1]["rasante_min"] == 101.7
    assert perfil[1]["tirante_sin_via"] == pytest.approx(1.2)
    # con radio de búsqueda, el punto vecino también ve el agua
    perfil_r = h.perfil_eje(muestras, GT, dem, cota_sin, None, radio_m=25.0, y_lamina=0.0, borde_libre=0.5)
    assert perfil_r[2]["control"] == "Pluvial sin vía"
    # lámina de desborde manda cuando es mayor
    perfil_l = h.perfil_eje(muestras, GT, dem, cota_sin, None, radio_m=0.0, y_lamina=2.0, borde_libre=0.5)
    assert all(p["control"] == "Desborde en lámina" for p in perfil_l)
    tramos = h.tramos_anegados(perfil)
    assert len(tramos) == 1
    assert tramos[0]["inicio"] == 20.0 and tramos[0]["fin"] == 20.0
    assert tramos[0]["cota_max"] == 101.2


def test_progresiva_km():
    assert h.progresiva_km(0) == "0+000"
    assert h.progresiva_km(1234.6) == "1+235"
    assert h.progresiva_km(float("nan")) == "-"


def test_grafico_svg():
    perfil = [
        {"progresiva": 0.0, "terreno": 100.0, "agua_sin_via": float("nan"), "agua_con_via": float("nan"),
         "rasante_min": 100.5, "cota_diseno": 100.0, "control": "Sin anegamiento"},
        {"progresiva": 20.0, "terreno": 99.0, "agua_sin_via": 100.2, "agua_con_via": float("nan"),
         "rasante_min": 100.7, "cota_diseno": 100.2, "control": "Pluvial sin vía"},
    ]
    svg = h.grafico_perfil_svg(perfil)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "Rasante mínima" in svg and "polygon" in svg
    assert h.grafico_perfil_svg([]) == ""


def test_informe_y_csv(tmp_path):
    datos = {
        "parametros": {"dem": "dem.tif", "celda_x": 5.0, "celda_y": 5.0, "filas": 10, "cols": 10,
                       "crs": "EPSG:32717", "preproceso": "reproyección automática", "modo": "Balance",
                       "prof_min": 0.3, "area_min": 2000.0, "eje": "eje", "con_via": True,
                       "altura_terraplen": 2.0, "borde_libre": 0.5, "radio": 50.0},
        "hidrologia": {"p": 150.0, "metodo": "scs", "cn": 88.0, "s": 34.6, "lamina": 115.0,
                       "gumbel": {"media": 100.0, "desv": 50.0, "kt": 2.59, "n": 10, "tr": 50}},
        "lamina": {"Q": 300.0, "B": 3000.0, "n": 0.035, "S": 0.00036, "y": 0.4, "q": 0.1, "v": 0.25},
        "escenarios": [{"titulo": "4. Sin vía", "n_total": 3, "n_ruido": 1, "n_validas": 2,
                        "nota_tabla": "nota",
                        "tabla": [{"id": 1, "progresiva": 20.0, "area_m2": 3000.0, "cota_fondo": 98.0,
                                   "cota_rebose": 100.0, "vol_rebose_m3": 500.0, "area_aporte_m2": 20000.0,
                                   "vol_entrada_m3": 300.0, "rebosa": False, "cota_agua": 99.5,
                                   "tirante_max_m": 1.5, "vierte_sobre_via": True, "toca_via": True}]}],
        "resumen_eje": {"cota_max": 99.5, "tirante_max": 1.5, "rasante_max": 100.0, "long_anegada": 40.0},
        "tramos": [{"inicio": 0.0, "fin": 40.0, "cota_max": 99.5, "tirante_max": 1.5, "rasante_max": 100.0,
                    "controles": {"Pluvial sin vía"}}],
        "perfil": [{"progresiva": 0.0, "x": 0, "y": 0, "terreno": 98.5, "agua_sin_via": 99.5,
                    "agua_con_via": float("nan"), "lamina_desborde": 98.9, "tirante_sin_via": 1.0,
                    "tirante_con_via": 0.0, "cota_diseno": 99.5, "rasante_min": 100.0, "altura_min": 1.5,
                    "control": "Pluvial sin vía"}],
    }
    datos["top_depresiones"] = datos["escenarios"][0]["tabla"]
    datos["texto_perfil"] = h.texto_perfil(datos)
    assert "Gumbel" in datos["texto_perfil"] and "terraplén" in datos["texto_perfil"]
    ruta = tmp_path / "informe.html"
    h.informe_html(str(ruta), datos)
    html = ruta.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "reproyección automática" in html
    assert "requiere alcantarilla" in html
    csv = tmp_path / "curvas.csv"
    h.escribir_curvas_csv(str(csv), [("sin_via", 1, [(98.0, 0.0, 0.0), (98.1, 25.0, 1.25)])])
    lineas = csv.read_text(encoding="utf-8-sig").splitlines()
    assert lineas[0] == "escenario;id_depresion;cota_m;area_m2;volumen_m3"
    assert lineas[2] == "sin_via;1;98.100;25.0;1.2"
