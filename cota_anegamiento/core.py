# -*- coding: utf-8 -*-
"""
Núcleo de cálculo del complemento «Cota de Anegamiento».

Solo usa numpy y la biblioteca estándar, para que funcione en cualquier
instalación de QGIS sin instalar nada adicional.

Método:
1. Relleno de depresiones (Priority-Flood, Barnes et al. 2014). Cada celda
   queda con la cota a la que se llenaría antes de verter (cota de rebose)
   y con un puntero a la celda hacia donde drena.
2. Las celdas con cota rellena > cota del terreno forman las depresiones.
   Cada grupo conectado es una depresión con una sola cota de rebose.
3. Área de aporte de cada depresión: todas las celdas cuyo camino de flujo
   llega primero a esa depresión.
4. Balance hídrico en cascada: volumen escurrido (SCS-CN o coeficiente C)
   contra la curva cota-volumen de cada depresión. Si la depresión se llena,
   el exceso pasa a la depresión de aguas abajo.
"""

import heapq
import math
from collections import deque

import numpy as np

EPS = 1e-9


# ---------------------------------------------------------------------------
# Hidrología
# ---------------------------------------------------------------------------

def gumbel(serie_mm, tr_anios):
    """Precipitación de diseño con Gumbel (método de momentos).

    Devuelve (P_T, media, desviación, K_T, n)."""
    x = np.asarray([float(v) for v in serie_mm], dtype=float)
    n = x.size
    if n < 3:
        raise ValueError("La serie de máximas anuales necesita al menos 3 valores.")
    if tr_anios <= 1:
        raise ValueError("El periodo de retorno debe ser mayor que 1 año.")
    media = float(x.mean())
    desv = float(x.std(ddof=1))
    kt = -(math.sqrt(6.0) / math.pi) * (0.5772 + math.log(math.log(tr_anios / (tr_anios - 1.0))))
    return media + kt * desv, media, desv, kt, n


def escorrentia_scs(p_mm, cn):
    """Lámina escurrida (mm) por el método del Número de Curva SCS."""
    if cn <= 0 or cn > 100:
        raise ValueError("El número de curva debe estar entre 1 y 100.")
    if cn >= 100:
        return float(p_mm)
    s = 25400.0 / cn - 254.0
    ia = 0.2 * s
    if p_mm <= ia:
        return 0.0
    return (p_mm - ia) ** 2 / (p_mm + 0.8 * s)


def escorrentia_c(p_mm, c):
    """Lámina escurrida (mm) con coeficiente de escorrentía C."""
    return float(p_mm) * float(c)


def lamina_manning(q_desb, ancho_b, n, s):
    """Tirante de flujo en lámina (canal muy ancho, R ≈ y).

    Devuelve (y, q, v): tirante (m), caudal unitario (m²/s) y velocidad (m/s)."""
    if q_desb <= 0 or ancho_b <= 0 or n <= 0 or s <= 0:
        return 0.0, 0.0, 0.0
    q = q_desb / ancho_b
    y = (n * q / math.sqrt(s)) ** 0.6
    v = q / y if y > 0 else 0.0
    return y, q, v


# ---------------------------------------------------------------------------
# Utilidades de preparación del DEM (sin GDAL, para poder probarlas)
# ---------------------------------------------------------------------------

def epsg_utm(lon, lat):
    """Código EPSG de la zona UTM (WGS 84) que contiene el punto (lon, lat)."""
    zona = int(math.floor((lon + 180.0) / 6.0)) + 1
    zona = min(max(zona, 1), 60)
    return (32600 if lat >= 0 else 32700) + zona


def metros_por_grado(lat):
    """Longitud aproximada de un grado de longitud a la latitud dada (m)."""
    return 111320.0 * math.cos(math.radians(lat))


def celda_redondeada(celda_m):
    """Redondea un tamaño de celda a un valor «bonito» (2 cifras significativas)."""
    if celda_m <= 0 or not math.isfinite(celda_m):
        return 1.0
    exp = math.floor(math.log10(celda_m))
    base = 10.0 ** (exp - 1)
    return max(round(celda_m / base) * base, base)


def factor_remuestreo(n_celdas, max_celdas):
    """Factor por el que hay que multiplicar la celda para no pasar de max_celdas."""
    if n_celdas <= max_celdas:
        return 1.0
    return math.sqrt(n_celdas / float(max_celdas))


def huecos_interiores(mascara_nodata):
    """Celdas sin dato que NO están conectadas (8 vecinos) con el borde del DEM.

    Son los huecos que conviene rellenar antes del análisis: un hueco interior
    se comporta como un sumidero falso."""
    m = np.asarray(mascara_nodata, dtype=bool)
    if not m.any():
        return np.zeros_like(m)
    lab, n = _etiquetar(m)
    if n == 0:
        return np.zeros_like(m)
    borde = np.concatenate((lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]))
    toca_borde = np.zeros(n + 1, dtype=bool)
    toca_borde[np.unique(borde)] = True
    toca_borde[0] = False
    return (lab > 0) & ~toca_borde[lab]


# ---------------------------------------------------------------------------
# Relleno de depresiones (Priority-Flood)
# ---------------------------------------------------------------------------

def _priority_flood(zp, R, C, progreso=None, cancelado=None):
    """Priority-Flood+ sobre el DEM acolchado (con borde de NaN).

    zp: array 2D (R x C) con NaN en celdas inválidas y en el borde.
    Devuelve (filled_list, parent_list, order_list)."""
    N = R * C
    zf = zp.ravel()
    invalido = ~np.isfinite(zf)
    z = np.where(invalido, 0.0, zf).tolist()
    filled = list(z)
    parent = [-1] * N
    closed = bytearray(invalido.astype(np.uint8).tobytes())

    # Semillas: celdas válidas vecinas de una celda inválida (bordes / sin datos)
    inv2 = invalido.reshape(R, C)
    vecino_inv = np.zeros((R, C), dtype=bool)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            vecino_inv[1:-1, 1:-1] |= inv2[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
    semillas = np.flatnonzero((vecino_inv & ~inv2).ravel())

    heap = [(z[i], i) for i in semillas.tolist()]
    heapq.heapify(heap)
    for i in semillas.tolist():
        closed[i] = 1

    offs = (-C - 1, -C, -C + 1, -1, 1, C - 1, C, C + 1)
    pit = deque()
    order = []
    append_order = order.append
    total = N - int(invalido.sum())
    paso = max(total // 50, 1)
    cuenta = 0
    heappop = heapq.heappop
    heappush = heapq.heappush
    pit_pop = pit.popleft
    pit_append = pit.append

    while heap or pit:
        if pit:
            c = pit_pop()
            cz = filled[c]
        else:
            cz, c = heappop(heap)
        append_order(c)
        for o in offs:
            n = c + o
            if closed[n]:
                continue
            closed[n] = 1
            parent[n] = c
            zn = z[n]
            if zn <= cz:
                filled[n] = cz
                pit_append(n)
            else:
                heappush(heap, (zn, n))
        cuenta += 1
        if cuenta % paso == 0:
            if cancelado is not None and cancelado():
                raise RuntimeError("Proceso cancelado por el usuario.")
            if progreso is not None:
                progreso(cuenta / total)
    return filled, parent, order


def _direccion_d8(filled2d, valido2d, parent_pf):
    """Puntero de flujo por celda (índice plano) sobre el DEM rellenado.

    D8 de máxima pendiente donde hay descenso; donde no lo hay (zonas planas)
    se conserva el puntero del Priority-Flood."""
    R, C = filled2d.shape
    z = np.where(valido2d, filled2d, np.inf)
    mejor = np.zeros((R, C), dtype=float)
    mejor_off = np.zeros((R, C), dtype=np.int64)
    interior = np.zeros((R, C), dtype=bool)
    interior[1:-1, 1:-1] = True
    zi = z[1:-1, 1:-1]
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            zn = z[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
            pend = (zi - zn) / (math.sqrt(2.0) if dr and dc else 1.0)
            pend = np.where(np.isfinite(pend), pend, -np.inf)
            mejora = pend > mejor[1:-1, 1:-1]
            mejor[1:-1, 1:-1] = np.where(mejora, pend, mejor[1:-1, 1:-1])
            mejor_off[1:-1, 1:-1] = np.where(mejora, dr * C + dc, mejor_off[1:-1, 1:-1])
    idx = np.arange(R * C, dtype=np.int64)
    usa_d8 = (mejor > 0).ravel() & valido2d.ravel()
    return np.where(usa_d8, idx + mejor_off.ravel(), parent_pf)


def _etiquetar(mascara):
    """Etiqueta grupos conectados (8 vecinos). Usa scipy si está disponible."""
    try:
        from scipy import ndimage
        lab, n = ndimage.label(mascara, structure=np.ones((3, 3), dtype=int))
        return lab.astype(np.int32), int(n)
    except Exception:
        pass
    R, C = mascara.shape
    lab = np.zeros((R, C), dtype=np.int32)
    m = mascara.ravel().tolist()
    labf = [0] * (R * C)
    nlab = 0
    for i0, v in enumerate(m):
        if not v or labf[i0]:
            continue
        nlab += 1
        labf[i0] = nlab
        pila = [i0]
        while pila:
            i = pila.pop()
            r, c = divmod(i, C)
            for dr in (-1, 0, 1):
                rr = r + dr
                if rr < 0 or rr >= R:
                    continue
                for dc in (-1, 0, 1):
                    cc = c + dc
                    if cc < 0 or cc >= C:
                        continue
                    j = rr * C + cc
                    if m[j] and not labf[j]:
                        labf[j] = nlab
                        pila.append(j)
    lab[:] = np.asarray(labf, dtype=np.int32).reshape(R, C)
    return lab, nlab


# ---------------------------------------------------------------------------
# Análisis completo
# ---------------------------------------------------------------------------

def analizar(dem, validos, area_celda, lamina_escurrida_mm, modo_rebose=False,
             prof_min=0.30, area_min=1000.0, mascara_via=None,
             progreso=None, cancelado=None):
    """Analiza depresiones y calcula la cota de anegamiento.

    dem: array 2D float (m).
    validos: array 2D bool (True = dato válido).
    area_celda: área de una celda (m²).
    lamina_escurrida_mm: escorrentía (mm) sobre toda el área.
    modo_rebose: True = todas las depresiones válidas llenas hasta rebose.
    prof_min, area_min: filtros de ruido del DEM.
    mascara_via: array 2D bool con las celdas del eje de la vía (opcional),
                 solo para marcar qué depresiones tocan la vía.

    Devuelve un dict con rásters (cota_agua, tirante, etiquetas, aporte,
    rellenado) y la lista de depresiones con sus atributos."""
    rows, cols = dem.shape
    R, C = rows + 2, cols + 2
    zp = np.full((R, C), np.nan, dtype=float)
    zp[1:-1, 1:-1] = np.where(validos, dem, np.nan)

    def prog(f, a, b):
        if progreso is not None:
            progreso(a + (b - a) * f)

    filled_l, parent_l, order = _priority_flood(
        zp, R, C, progreso=(lambda f: prog(f, 0.0, 0.70)), cancelado=cancelado)

    zfin = np.where(np.isfinite(zp), zp, 0.0).ravel()
    filled = np.asarray(filled_l, dtype=float)
    validp = np.isfinite(zp).ravel()
    deprimida = validp & (filled > zfin + EPS)

    lab2, nlab = _etiquetar(deprimida.reshape(R, C))
    lab = lab2.ravel()
    prog(1.0, 0.70, 0.75)

    resultado = {
        "cota_agua": np.full((rows, cols), np.nan),
        "tirante": np.full((rows, cols), np.nan),
        "etiquetas": np.zeros((rows, cols), dtype=np.int32),
        "aporte": np.zeros((rows, cols), dtype=np.int32),
        "rellenado": filled.reshape(R, C)[1:-1, 1:-1].copy(),
        "depresiones": [],
        "n_total": nlab,
        "n_ruido": 0,
        "n_validas": 0,
    }
    if nlab == 0:
        resultado["rellenado"][~validos] = np.nan
        return resultado

    # --- Atributos básicos por depresión -----------------------------------
    idx = np.flatnonzero(lab > 0)
    lab_idx = lab[idx]
    ncel = np.bincount(lab_idx, minlength=nlab + 1)
    spill = np.zeros(nlab + 1)
    spill[lab_idx] = filled[idx]
    zmin = np.full(nlab + 1, np.inf)
    np.minimum.at(zmin, lab_idx, zfin[idx])
    vmax = np.bincount(lab_idx, weights=(filled[idx] - zfin[idx]), minlength=nlab + 1) * area_celda

    # Orden de procesamiento (para saber qué depresión está aguas arriba)
    pos = np.empty(R * C, dtype=np.int64)
    pos.fill(np.iinfo(np.int64).max)
    order_arr = np.asarray(order, dtype=np.int64)
    pos[order_arr] = np.arange(order_arr.size, dtype=np.int64)
    min_pos = np.full(nlab + 1, np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(min_pos, lab_idx, pos[idx])
    celda_primera = np.full(nlab + 1, -1, dtype=np.int64)
    celda_primera[lab[order_arr[min_pos[1:]]]] = order_arr[min_pos[1:]]

    # --- Dirección de flujo híbrida ----------------------------------------
    # Fuera de las zonas planas se usa D8 (máxima pendiente) sobre el DEM
    # rellenado; en las zonas planas (depresiones rellenadas, terrenos
    # horizontales) se usa el puntero del Priority-Flood, que siempre lleva al
    # punto de vertido. Así el camino del agua no depende del orden en que el
    # algoritmo visitó las celdas, algo que en llanuras muy suaves desviaba el
    # flujo sistemáticamente hacia un lado.
    parent_arr = np.asarray(parent_l, dtype=np.int64)
    parent_h = _direccion_d8(filled.reshape(R, C), validp.reshape(R, C), parent_arr)
    # Orden topológico: los padres van antes que los hijos
    orden_topo = np.lexsort((pos, filled))
    orden_topo = orden_topo[validp[orden_topo]]
    prog(1.0, 0.75, 0.78)

    # --- Área de aporte: primera depresión en el camino de flujo ----------
    lab_list = lab.tolist()
    parent_hl = parent_h.tolist()
    catch = [0] * (R * C)
    total = orden_topo.size
    paso = max(total // 20, 1)
    for k, c in enumerate(orden_topo.tolist()):
        l = lab_list[c]
        if l:
            catch[c] = l
        else:
            p = parent_hl[c]
            catch[c] = catch[p] if p >= 0 else 0
        if k % paso == 0:
            if cancelado is not None and cancelado():
                raise RuntimeError("Proceso cancelado por el usuario.")
            prog(k / total, 0.78, 0.85)
    catch_arr = np.asarray(catch, dtype=np.int64)
    celdas_aporte = np.bincount(catch_arr[validp], minlength=nlab + 1)

    # Depresión de aguas abajo y celda de vertido
    aguas_abajo = np.zeros(nlab + 1, dtype=np.int64)
    celda_vertido = np.full(nlab + 1, -1, dtype=np.int64)
    for l in range(1, nlab + 1):
        c0 = int(celda_primera[l])
        p = parent_l[c0] if c0 >= 0 else -1
        celda_vertido[l] = p
        aguas_abajo[l] = catch[p] if p >= 0 else 0

    # Filtro de ruido
    area_dep = ncel * area_celda
    prof_dep = spill - zmin
    valida = (prof_dep >= prof_min) & (area_dep >= area_min)
    valida[0] = False

    # --- Balance hídrico en cascada ---------------------------------------
    orden_lagos = sorted(range(1, nlab + 1), key=lambda l: -int(min_pos[l]))
    # celdas de cada depresión, ordenadas por cota
    orden_lab = np.argsort(lab_idx, kind="stable")
    idx_por_lab = idx[orden_lab]
    fin = np.cumsum(ncel)
    ini = fin - ncel

    lam_m = lamina_escurrida_mm / 1000.0
    entrada = np.zeros(nlab + 1)
    vin = np.zeros(nlab + 1)
    nivel = np.full(nlab + 1, np.nan)
    rebosa = np.zeros(nlab + 1, dtype=bool)
    excedente = np.zeros(nlab + 1)

    for l in orden_lagos:
        v = lam_m * celdas_aporte[l] * area_celda + entrada[l]
        vin[l] = v
        salida = 0.0
        if not valida[l]:
            salida = v
        elif modo_rebose or v >= vmax[l] - 1e-6:
            nivel[l] = spill[l]
            rebosa[l] = v >= vmax[l] - 1e-6
            salida = max(v - vmax[l], 0.0)
        elif v <= 0:
            nivel[l] = zmin[l]
        else:
            d = np.sort(zfin[idx_por_lab[ini[l]:fin[l]]])
            cs = np.cumsum(d)
            j_arr = np.arange(d.size)
            vbreak = area_celda * (j_arr * d - np.concatenate(([0.0], cs[:-1])))
            j = int(np.searchsorted(vbreak, v, side="right") - 1)
            j = max(min(j, d.size - 1), 0)
            h = (v / area_celda + cs[j]) / (j + 1)
            nivel[l] = min(h, spill[l])
        excedente[l] = salida
        ab = aguas_abajo[l]
        if ab > 0 and salida > 0:
            entrada[ab] += salida
    prog(1.0, 0.85, 0.92)

    # --- Rásters de salida -------------------------------------------------
    niv_celda = nivel[lab]
    val_celda = valida[lab] & (lab > 0)
    moj = val_celda & np.isfinite(niv_celda) & (niv_celda > zfin + EPS)
    cota_agua = np.where(moj, niv_celda, np.nan).reshape(R, C)[1:-1, 1:-1]
    tirante = np.where(moj, niv_celda - zfin, np.nan).reshape(R, C)[1:-1, 1:-1]
    etiquetas = np.where(val_celda, lab, 0).reshape(R, C)[1:-1, 1:-1].astype(np.int32)
    # Área de aporte: id de la depresión válida a la que drena cada celda
    aporte = np.where(valida[catch_arr], catch_arr, 0).reshape(R, C)[1:-1, 1:-1].astype(np.int32)

    # Depresiones que tocan la vía y que vierten sobre la vía
    toca = np.zeros(nlab + 1, dtype=bool)
    via_p = None
    if mascara_via is not None and mascara_via.any():
        via_p = np.zeros((R, C), dtype=bool)
        via_p[1:-1, 1:-1] = mascara_via
        dil = via_p.copy()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                dil[1:-1, 1:-1] |= via_p[1 + dr:R - 1 + dr, 1 + dc:C - 1 + dc]
        toca[np.unique(lab[dil.ravel() & (lab > 0)])] = True
        toca[0] = False
    via_flat = via_p.ravel() if via_p is not None else None

    # Centroides (en filas/columnas del DEM sin acolchar)
    rr = idx // C - 1
    cc = idx % C - 1
    sum_r = np.bincount(lab_idx, weights=rr, minlength=nlab + 1)
    sum_c = np.bincount(lab_idx, weights=cc, minlength=nlab + 1)
    tir_max = np.where(np.isfinite(nivel), nivel - zmin, 0.0)
    area_moj = np.bincount(lab[moj], minlength=nlab + 1) * area_celda

    deps = []
    for l in range(1, nlab + 1):
        if not valida[l]:
            continue
        vc = int(celda_vertido[l])
        vierte_via = bool(via_flat is not None and vc >= 0 and via_flat[vc])
        deps.append({
            "id": l,
            "area_m2": float(area_dep[l]),
            "prof_max_m": float(prof_dep[l]),
            "cota_fondo": float(zmin[l]),
            "cota_rebose": float(spill[l]),
            "vol_rebose_m3": float(vmax[l]),
            "area_aporte_m2": float(celdas_aporte[l] * area_celda),
            "vol_entrada_m3": float(vin[l]),
            "excedente_m3": float(excedente[l]),
            "rebosa": bool(rebosa[l]),
            "cota_agua": float(nivel[l]) if np.isfinite(nivel[l]) else float(zmin[l]),
            "tirante_max_m": float(max(tir_max[l], 0.0)),
            "area_mojada_m2": float(area_moj[l]),
            "aguas_abajo": int(aguas_abajo[l]) if valida[aguas_abajo[l]] else 0,
            "toca_via": bool(toca[l]),
            "vierte_sobre_via": vierte_via,
            "fila": float(sum_r[l] / ncel[l]),
            "col": float(sum_c[l] / ncel[l]),
            "celdas": int(ncel[l]),
        })

    resultado["rellenado"][~validos] = np.nan
    resultado.update({
        "cota_agua": cota_agua.copy(),
        "tirante": tirante.copy(),
        "etiquetas": etiquetas.copy(),
        "aporte": aporte.copy(),
        "depresiones": deps,
        "n_ruido": int(nlab - len(deps)),
        "n_validas": len(deps),
    })
    prog(1.0, 0.92, 1.0)
    return resultado


def curva_cota_volumen(dem, etiquetas, id_dep, area_celda, cota_tope, paso=0.10):
    """Curva cota-área-volumen de una depresión, desde el fondo hasta cota_tope."""
    z = dem[etiquetas == id_dep]
    if z.size == 0:
        return []
    z = np.sort(z)
    h0 = math.floor(z[0] / paso) * paso
    filas = []
    h = h0
    while h <= cota_tope + 1e-9:
        bajo = z[z < h]
        area = bajo.size * area_celda
        vol = float(np.sum(h - bajo) * area_celda) if bajo.size else 0.0
        filas.append((round(h, 3), area, vol))
        h += paso
    if filas and filas[-1][0] < cota_tope - 1e-6:
        bajo = z[z < cota_tope]
        filas.append((round(cota_tope, 3), bajo.size * area_celda,
                      float(np.sum(cota_tope - bajo) * area_celda)))
    return filas


def elevar_via(dem, mascara_via, altura):
    """Devuelve una copia del DEM con las celdas de la vía elevadas `altura` m."""
    d = dem.copy()
    d[mascara_via] = d[mascara_via] + altura
    return d
