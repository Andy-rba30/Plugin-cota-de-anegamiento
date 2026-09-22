# -*- coding: utf-8 -*-
"""Importa el complemento con un sustituto mínimo de PyQGIS y revisa la
definición de parámetros (nombres únicos, avanzados, salidas)."""
from cota_anegamiento import algoritmo, provider


def test_algoritmo_completo_define_parametros():
    a = algoritmo.CotaAnegamientoAlgorithm()
    a.initAlgorithm()
    nombres = [p.name() for p in a.parameterDefinitions()]
    assert nombres[0] == "DEM"
    for n in ("EJE", "P_DISENO", "CN", "CELDA", "HUECOS", "DRENES", "CAMPO_CAUDAL", "DURACION",
              "OUT_DEPRESIONES", "OUT_INFORME", "OUT_APORTE"):
        assert n in nombres
    assert len(nombres) == len(set(nombres))
    salidas = [o.name() for o in a.outputDefinitions()]
    assert "COTA_AGUA_MAX" in salidas and "RASANTE_MIN" in salidas
    # los parámetros de desborde son avanzados; el DEM no
    assert a.parameterDefinition("Q_DESB").flags() & 2
    assert not a.parameterDefinition("DEM").flags() & 2


def test_algoritmo_rapido_solo_dem_visible():
    a = algoritmo.CotaAnegamientoRapidoAlgorithm()
    a.initAlgorithm()
    visibles = [p.name() for p in a.parameterDefinitions()
                if not p.isDestination() and not (p.flags() & 2)]
    assert visibles == ["DEM", "EJE", "P_DISENO", "CN", "PROF_MIN", "AREA_MIN", "ALTURA_VIA", "BORDE_LIBRE",
                        "DRENES", "CAMPO_CAUDAL", "CAMPO_ANCHO", "CAMPO_PROF", "DURACION"]
    assert visibles[0] == "DEM"
    # lo especializado sigue en avanzados
    for n in ("SERIE", "TR", "C", "MODO", "CELDA", "HUECOS", "Q_DESB"):
        assert a.parameterDefinition(n).flags() & 2
    assert a.name() == "cota_anegamiento_rapido"
    assert a.createInstance().name() == "cota_anegamiento_rapido"
    assert "DEM" in a.shortHelpString()


def test_proveedor_registra_dos_algoritmos():
    p = provider.CotaAnegamientoProvider()
    p.loadAlgorithms()
    assert sorted(a.name() for a in p.algorithms()) == ["cota_anegamiento", "cota_anegamiento_rapido"]
    assert p.id() == "cotaanegamiento"


def test_plugin_importa():
    from cota_anegamiento import plugin
    assert plugin.ID_ALGORITMO_RAPIDO == "cotaanegamiento:cota_anegamiento_rapido"
