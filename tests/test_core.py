# -*- coding: utf-8 -*-
"""Pruebas del núcleo de cálculo (solo numpy)."""
import math

import numpy as np
import pytest

from cota_anegamiento import core


def cubeta(n=120, centro=(60, 60), radio=20, prof=2.0, base=100.0):
    """Plano a `base` m con una cubeta parabólica."""
    yy, xx = np.mgrid[0:n, 0:n]
    dem = np.full((n, n), base)
    r = np.hypot(xx - centro[1], yy - centro[0])
    m = r < radio
    dem[m] = base - prof * (1 - (r[m] / radio) ** 2)
    return dem


# --- Hidrología -------------------------------------------------------------

def test_gumbel_valores_conocidos():
    serie = [45, 60, 380, 610, 30, 55, 70, 40]
    p, media, desv, kt, n = core.gumbel(serie, 50)
    assert n == 8
    assert media == pytest.approx(np.mean(serie))
    assert desv == pytest.approx(np.std(serie, ddof=1))
    # K_T de Gumbel para Tr = 50 años (método de momentos) ≈ 2.592
    assert kt == pytest.approx(2.592, abs=0.002)
    assert p == pytest.approx(media + kt * desv)


def test_gumbel_rechaza_series_cortas():
    with pytest.raises(ValueError):
        core.gumbel([1, 2], 50)
    with pytest.raises(ValueError):
        core.gumbel([1, 2, 3], 1)


def test_scs():
    # CN = 88 -> S = 34.6 mm ; P = 150 mm -> Q ≈ 115.2 mm
    q = core.escorrentia_scs(150.0, 88.0)
    s = 25400.0 / 88.0 - 254.0
    assert q == pytest.approx((150 - 0.2 * s) ** 2 / (150 + 0.8 * s))
    assert core.escorrentia_scs(5.0, 88.0) == 0.0          # por debajo de Ia
    assert core.escorrentia_scs(50.0, 100.0) == 50.0       # impermeable
    with pytest.raises(ValueError):
        core.escorrentia_scs(50.0, 0)


def test_manning_lamina():
    y, q, v = core.lamina_manning(300.0, 3000.0, 0.035, 0.00036)
    assert q == pytest.approx(0.1)
    assert y == pytest.approx((0.035 * 0.1 / math.sqrt(0.00036)) ** 0.6)
    assert v == pytest.approx(q / y)
    assert core.lamina_manning(0, 100, 0.03, 0.001) == (0.0, 0.0, 0.0)


# --- Utilidades de preparación del DEM --------------------------------------

def test_epsg_utm():
    assert core.epsg_utm(-80.6, -5.2) == 32717     # Piura, Perú
    assert core.epsg_utm(-74.1, 4.7) == 32618      # Bogotá
    assert core.epsg_utm(-3.7, 40.4) == 32630      # Madrid
    assert core.epsg_utm(-180, 0) == 32601
    assert core.epsg_utm(180, 0) == 32660


def test_celda_redondeada():
    assert core.celda_redondeada(27.83) == pytest.approx(28.0)
    assert core.celda_redondeada(0.926) == pytest.approx(0.93)
    assert core.celda_redondeada(12.7) == pytest.approx(13.0)
    assert core.celda_redondeada(0) == 1.0


def test_factor_remuestreo():
    assert core.factor_remuestreo(1000, 6000) == 1.0
    assert core.factor_remuestreo(24_000_000, 6_000_000) == pytest.approx(2.0)


def test_huecos_interiores():
    m = np.zeros((6, 6), dtype=bool)
    m[2:4, 2:4] = True      # hueco interior
    m[0, 0:3] = True        # hueco pegado al borde
    h = core.huecos_interiores(m)
    assert h[2:4, 2:4].all()
    assert not h[0, :].any()
    assert h.sum() == 4


# --- Análisis de depresiones --------------------------------------------------

def test_cubeta_volumen_y_rebose():
    dem = cubeta()
    validos = np.ones_like(dem, dtype=bool)
    celda = 5.0
    res = core.analizar(dem, validos, celda ** 2, 50.0, prof_min=0.3, area_min=100.0)
    assert res["n_total"] == 1
    assert res["n_ruido"] == 0
    d = res["depresiones"][0]
    # volumen de un paraboloide: V = π r² h / 2 con r = 100 m y h = 2 m
    assert d["vol_rebose_m3"] == pytest.approx(math.pi * 100 ** 2 * 2 / 2, rel=0.01)
    assert d["cota_rebose"] == pytest.approx(100.0)
    assert d["cota_fondo"] == pytest.approx(98.0)
    assert d["prof_max_m"] == pytest.approx(2.0)
    assert not d["rebosa"]
    # el nivel calculado debe ser coherente con la curva cota-volumen
    curva = core.curva_cota_volumen(dem, res["etiquetas"], d["id"], celda ** 2, d["cota_rebose"], 0.01)
    cotas = np.array([c[0] for c in curva])
    vols = np.array([c[2] for c in curva])
    v_interp = np.interp(d["cota_agua"], cotas, vols)
    assert v_interp == pytest.approx(d["vol_entrada_m3"], rel=0.02)
    # el ráster de tirante es coherente con el nivel
    tir = res["tirante"]
    assert np.nanmax(tir) == pytest.approx(d["tirante_max_m"], abs=1e-6)
    assert (res["etiquetas"] > 0).sum() == d["celdas"]
    # el área de aporte incluye a la propia depresión
    assert d["area_aporte_m2"] >= d["area_m2"]
    assert (res["aporte"] == d["id"]).sum() * celda ** 2 == pytest.approx(d["area_aporte_m2"])


def test_modo_rebose_llena_hasta_el_borde():
    dem = cubeta()
    res = core.analizar(dem, np.ones_like(dem, bool), 25.0, 0.0, modo_rebose=True, prof_min=0.3, area_min=100)
    d = res["depresiones"][0]
    assert d["cota_agua"] == pytest.approx(d["cota_rebose"])
    assert d["tirante_max_m"] == pytest.approx(2.0)


def test_filtro_de_ruido():
    dem = cubeta(prof=0.2)
    res = core.analizar(dem, np.ones_like(dem, bool), 25.0, 50.0, prof_min=0.3, area_min=100)
    assert res["n_total"] == 1
    assert res["n_ruido"] == 1
    assert res["depresiones"] == []
    assert np.isnan(res["tirante"]).all()


def test_cascada_dos_cubetas():
    """La cubeta pequeña se llena y vierte en la grande, aguas abajo."""
    n = 160
    yy, xx = np.mgrid[0:n, 0:n]
    dem = 100.0 + (n - 1 - yy) * 0.02          # pendiente hacia el sur (filas grandes = más bajo)
    for (cy, cx, radio, prof) in ((40, 80, 8, 1.0), (110, 80, 25, 3.0)):
        r = np.hypot(xx - cx, yy - cy)
        m = r < radio
        dem[m] = dem[m] - prof * (1 - (r[m] / radio) ** 2)
    res = core.analizar(dem, np.ones_like(dem, bool), 25.0, 200.0, prof_min=0.3, area_min=100)
    deps = sorted(res["depresiones"], key=lambda d: d["area_m2"])
    assert len(deps) == 2
    chica, grande = deps
    assert chica["rebosa"]
    assert chica["excedente_m3"] > 0
    assert chica["aguas_abajo"] == grande["id"]
    assert grande["aguas_abajo"] == 0
    # lo que recibe la grande incluye el excedente de la chica
    assert grande["vol_entrada_m3"] == pytest.approx(0.2 * grande["area_aporte_m2"] + chica["excedente_m3"])


def test_flujo_d8_en_ladera_plana():
    """En una ladera uniforme el agua baja recto, sin desviarse de lado."""
    n = 120
    yy, xx = np.mgrid[0:n, 0:n]
    dem = 100.0 + (n - 1 - yy) * 0.02
    r = np.hypot(xx - 60, yy - 90)
    m = r < 10
    dem[m] = dem[m] - 1.0 * (1 - (r[m] / 10) ** 2)
    res = core.analizar(dem, np.ones_like(dem, bool), 25.0, 10.0, prof_min=0.3, area_min=100)
    d = res["depresiones"][0]
    ap = res["aporte"] == d["id"]
    # toda la columna central aguas arriba de la cubeta drena a ella
    assert ap[0:80, 60].all()
    # y las columnas alejadas no
    assert not ap[0:80, 20].any() and not ap[0:80, 100].any()


def test_nodata_como_salida():
    dem = cubeta()
    validos = np.ones_like(dem, bool)
    validos[60, 60] = False                      # hueco en el fondo de la cubeta
    res = core.analizar(dem, validos, 25.0, 50.0, prof_min=0.3, area_min=100)
    # el hueco actúa como sumidero: la cubeta desaparece
    assert res["depresiones"] == []


def test_terraplen_represa():
    """Un terraplén transversal a la pendiente crea una depresión aguas arriba."""
    n = 100
    yy, xx = np.mgrid[0:n, 0:n]
    # valle en V que baja hacia el sur; la vía lo cruza sin llegar a los bordes
    dem = 100.0 + (n - 1 - yy) * 0.03 + 0.05 * np.abs(xx - 50)
    via = np.zeros((n, n), dtype=bool)
    via[70, 10:91] = True
    res0 = core.analizar(dem, np.ones_like(dem, bool), 25.0, 100.0, prof_min=0.1, area_min=25)
    assert res0["depresiones"] == []
    dem_via = core.elevar_via(dem, via, 1.5)
    res1 = core.analizar(dem_via, np.ones_like(dem, bool), 25.0, 150.0, prof_min=0.1, area_min=25,
                         mascara_via=via)
    assert len(res1["depresiones"]) == 1
    d = res1["depresiones"][0]
    assert d["toca_via"]
    assert d["vierte_sobre_via"]
    assert d["rebosa"]
    # vierte por el punto más bajo del terraplén (col 50, fila 70)
    assert d["cota_rebose"] == pytest.approx(100.0 + 29 * 0.03 + 1.5)
    assert d["cota_fondo"] == pytest.approx(100.0 + 30 * 0.03)


def test_cancelacion():
    dem = cubeta()
    with pytest.raises(RuntimeError):
        core.analizar(dem, np.ones_like(dem, bool), 25.0, 50.0, cancelado=lambda: True)


def test_curva_cota_volumen_monotona():
    dem = cubeta()
    res = core.analizar(dem, np.ones_like(dem, bool), 25.0, 50.0, prof_min=0.3, area_min=100)
    d = res["depresiones"][0]
    curva = core.curva_cota_volumen(dem, res["etiquetas"], d["id"], 25.0, d["cota_rebose"])
    vols = [c[2] for c in curva]
    assert vols == sorted(vols)
    assert curva[-1][2] == pytest.approx(d["vol_rebose_m3"], rel=1e-6)
