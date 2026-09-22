# -*- coding: utf-8 -*-
# Complemento QGIS «Cota de Anegamiento»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
"""
Funciones auxiliares sin dependencia de QGIS: eje de la vía, perfil a lo
largo del eje, curvas cota-volumen en CSV e informe HTML.
"""

import datetime
import html
import math

import numpy as np


# ---------------------------------------------------------------------------
# Geometría del eje
# ---------------------------------------------------------------------------

def celda_de_xy(x, y, gt):
    """Fila y columna de la celda que contiene el punto (x, y)."""
    col = int(math.floor((x - gt[0]) / gt[1]))
    fila = int(math.floor((y - gt[3]) / gt[5]))
    return fila, col


def xy_de_celda(fila, col, gt):
    """Coordenadas del centro de una celda (admite valores fraccionarios)."""
    return gt[0] + (col + 0.5) * gt[1], gt[3] + (fila + 0.5) * gt[5]


def mascara_polilineas(polilineas, gt, forma):
    """Rasteriza polilíneas con conectividad de 4 vecinos.

    Con 4 vecinos el terraplén no deja «fugas» en diagonal para el flujo
    D8. polilineas: lista de listas de (x, y)."""
    filas, cols = forma
    m = np.zeros(forma, dtype=bool)
    paso = min(abs(gt[1]), abs(gt[5])) / 4.0

    def marcar(f, c):
        if 0 <= f < filas and 0 <= c < cols:
            m[f, c] = True

    for pts in polilineas:
        previa = None
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            n = max(int(math.ceil(L / paso)), 1)
            for k in range(n + 1):
                t = k / n
                f, c = celda_de_xy(x0 + t * (x1 - x0), y0 + t * (y1 - y0), gt)
                if previa is not None and (f, c) != previa:
                    df, dc = f - previa[0], c - previa[1]
                    if abs(df) >= 1 and abs(dc) >= 1:
                        marcar(previa[0], c)  # cierra el paso diagonal
                marcar(f, c)
                previa = (f, c)
    return m


def raster_drenes(drenes, gt, forma):
    """Rasteriza drenes como franjas de su ancho. Devuelve array int32 con el
    id del dren en cada celda (0 = ninguno).

    drenes: lista de (id, polilinea[(x, y)], ancho_m). Un dren más angosto que
    la celda ocupa al menos la línea de celdas por donde pasa (4 vecinos)."""
    filas, cols = forma
    salida = np.zeros(forma, dtype=np.int32)
    celda = min(abs(gt[1]), abs(gt[5]))
    for id_dren, pts, ancho in drenes:
        if len(pts) < 2:
            continue
        linea = mascara_polilineas([pts], gt, forma)
        radio = max(float(ancho or 0.0) / 2.0, 0.0)
        if radio > celda / 2.0:
            n = int(math.ceil(radio / celda))
            paso = celda / 2.0
            for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
                L = math.hypot(x1 - x0, y1 - y0)
                k_max = max(int(math.ceil(L / paso)), 1)
                for k in range(k_max + 1):
                    t = k / k_max
                    x, y = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
                    f, c = celda_de_xy(x, y, gt)
                    f0, f1 = max(f - n, 0), min(f + n + 1, filas)
                    c0, c1 = max(c - n, 0), min(c + n + 1, cols)
                    if f0 >= f1 or c0 >= c1:
                        continue
                    ff, cc = np.mgrid[f0:f1, c0:c1]
                    cx = gt[0] + (cc + 0.5) * gt[1]
                    cy = gt[3] + (ff + 0.5) * gt[5]
                    linea[f0:f1, c0:c1] |= np.hypot(cx - x, cy - y) <= radio
        salida[linea & (salida == 0)] = int(id_dren)
    return salida


def muestrear_polilineas(polilineas, paso):
    """Puntos cada `paso` m a lo largo de las polilíneas.

    Devuelve lista de (progresiva, x, y). La progresiva continúa de una
    polilínea a la siguiente en el orden recibido."""
    salida = []
    base = 0.0
    for pts in polilineas:
        if len(pts) < 2:
            continue
        seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts[:-1], pts[1:])]
        total = sum(seg)
        if total <= 0:
            continue
        d = 0.0
        distancias = []
        while d < total - 1e-9:
            distancias.append(d)
            d += paso
        distancias.append(total)
        acum = 0.0
        i = 0
        for dist in distancias:
            while i < len(seg) - 1 and acum + seg[i] < dist - 1e-9:
                acum += seg[i]
                i += 1
            t = 0.0 if seg[i] == 0 else (dist - acum) / seg[i]
            t = min(max(t, 0.0), 1.0)
            a, b = pts[i], pts[i + 1]
            salida.append((base + dist, a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        base += total
    return salida


def perfil_eje(muestras, gt, dem, cota_sin, cota_con, radio_m, y_lamina, borde_libre):
    """Calcula la cota de diseño en cada punto del eje.

    cota_sin / cota_con: rásters de cota de agua (NaN = seco); cota_con puede
    ser None. y_lamina: tirante de desborde en lámina (0 = no se evalúa)."""
    filas, cols = dem.shape
    celda = min(abs(gt[1]), abs(gt[5]))
    rc = max(int(math.ceil(radio_m / celda)), 0)
    res = []

    def maximo_ventana(r, f, c):
        if r is None:
            return float("nan")
        v = r[max(f - rc, 0):min(f + rc + 1, filas), max(c - rc, 0):min(c + rc + 1, cols)]
        if v.size == 0 or not np.isfinite(v).any():
            return float("nan")
        return float(np.nanmax(v))

    for prog, x, y in muestras:
        f, c = celda_de_xy(x, y, gt)
        if not (0 <= f < filas and 0 <= c < cols):
            continue
        terreno = float(dem[f, c])
        if not math.isfinite(terreno):
            continue
        ws = maximo_ventana(cota_sin, f, c)
        wc = maximo_ventana(cota_con, f, c)
        wl = terreno + y_lamina if y_lamina > 0 else float("nan")
        candidatos = [("Pluvial sin vía", ws), ("Pluvial con vía (sin alcantarillas)", wc),
                      ("Desborde en lámina", wl)]
        candidatos = [(n, v) for n, v in candidatos if math.isfinite(v) and v > terreno + 1e-6]
        if candidatos:
            control, cota = max(candidatos, key=lambda t: t[1])
        else:
            control, cota = "Sin anegamiento", terreno
        rasante = cota + borde_libre
        res.append({
            "progresiva": prog, "x": x, "y": y, "terreno": terreno,
            "agua_sin_via": ws, "agua_con_via": wc, "lamina_desborde": wl,
            "tirante_sin_via": max(ws - terreno, 0.0) if math.isfinite(ws) else 0.0,
            "tirante_con_via": max(wc - terreno, 0.0) if math.isfinite(wc) else 0.0,
            "cota_diseno": cota, "rasante_min": rasante,
            "altura_min": rasante - terreno, "control": control,
        })
    return res


def tramos_anegados(perfil):
    """Agrupa puntos consecutivos anegados en tramos (inicio, fin, datos)."""
    tramos = []
    actual = None
    for p in perfil:
        anegado = p["control"] != "Sin anegamiento"
        if anegado:
            if actual is None:
                actual = {"inicio": p["progresiva"], "fin": p["progresiva"],
                          "cota_max": p["cota_diseno"], "tirante_max": p["cota_diseno"] - p["terreno"],
                          "rasante_max": p["rasante_min"], "controles": {p["control"]}}
            else:
                actual["fin"] = p["progresiva"]
                actual["cota_max"] = max(actual["cota_max"], p["cota_diseno"])
                actual["tirante_max"] = max(actual["tirante_max"], p["cota_diseno"] - p["terreno"])
                actual["rasante_max"] = max(actual["rasante_max"], p["rasante_min"])
                actual["controles"].add(p["control"])
        elif actual is not None:
            tramos.append(actual)
            actual = None
    if actual is not None:
        tramos.append(actual)
    return tramos


def progresiva_km(m):
    """Formato de progresiva 0+000."""
    if m is None or not math.isfinite(m):
        return "-"
    total = int(round(m))
    return "%d+%03d" % (total // 1000, total % 1000)


# ---------------------------------------------------------------------------
# Gráfico SVG del perfil (sin dependencias)
# ---------------------------------------------------------------------------

def grafico_perfil_svg(perfil, ancho=1000, alto=320):
    """Perfil longitudinal en SVG: terreno, cota de agua y rasante mínima."""
    if not perfil:
        return ""
    xs = [p["progresiva"] for p in perfil]
    series = [
        ("terreno", "Terreno", "#7b8794", 1.5, [p["terreno"] for p in perfil]),
        ("agua_sin_via", "Agua sin vía", "#2b8ad9", 1.5, [p["agua_sin_via"] for p in perfil]),
        ("agua_con_via", "Agua con vía", "#c0392b", 1.5, [p["agua_con_via"] for p in perfil]),
        ("rasante_min", "Rasante mínima", "#1e8449", 2.0, [p["rasante_min"] for p in perfil]),
    ]
    valores = [v for _, _, _, _, ys in series for v in ys if v is not None and math.isfinite(v)]
    if not valores:
        return ""
    ymin, ymax = min(valores), max(valores)
    if ymax - ymin < 1.0:
        ymax = ymin + 1.0
    margen = (ymax - ymin) * 0.08
    ymin -= margen
    ymax += margen
    xmin, xmax = min(xs), max(xs)
    if xmax - xmin <= 0:
        xmax = xmin + 1.0
    ml, mr, mt, mb = 70, 20, 20, 45
    w_ = ancho - ml - mr
    h_ = alto - mt - mb

    def sx(x):
        return ml + (x - xmin) / (xmax - xmin) * w_

    def sy(y):
        return mt + (ymax - y) / (ymax - ymin) * h_

    out = ["<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 %d %d' width='100%%' "
           "style='max-width:%dpx;font-family:Segoe UI,Arial,sans-serif;font-size:11px'>" % (ancho, alto, ancho)]
    out.append("<rect x='0' y='0' width='%d' height='%d' fill='white'/>" % (ancho, alto))
    # rejilla
    for k in range(6):
        y = ymin + (ymax - ymin) * k / 5.0
        out.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#e4e7eb'/>" % (ml, sy(y), ancho - mr, sy(y)))
        out.append("<text x='%d' y='%.1f' text-anchor='end' fill='#52606d'>%.1f</text>" % (ml - 6, sy(y) + 4, y))
    for k in range(6):
        x = xmin + (xmax - xmin) * k / 5.0
        out.append("<line x1='%.1f' y1='%d' x2='%.1f' y2='%d' stroke='#e4e7eb'/>" % (sx(x), mt, sx(x), alto - mb))
        out.append("<text x='%.1f' y='%d' text-anchor='middle' fill='#52606d'>%s</text>"
                   % (sx(x), alto - mb + 16, progresiva_km(x)))
    out.append("<text x='%d' y='%d' text-anchor='middle' fill='#52606d'>Progresiva</text>"
               % (ml + w_ / 2, alto - 6))
    out.append("<text transform='translate(14,%d) rotate(-90)' text-anchor='middle' fill='#52606d'>Cota (msnm)</text>"
               % (mt + h_ / 2))
    # área anegada (entre terreno y cota de diseño)
    poly = []
    for p in perfil:
        if p["control"] != "Sin anegamiento":
            poly.append("%.1f,%.1f" % (sx(p["progresiva"]), sy(p["cota_diseno"])))
    if poly:
        arriba = []
        abajo = []
        for p in perfil:
            arriba.append("%.1f,%.1f" % (sx(p["progresiva"]), sy(p["cota_diseno"])))
            abajo.append("%.1f,%.1f" % (sx(p["progresiva"]), sy(p["terreno"])))
        out.append("<polygon points='%s' fill='#2b8ad9' fill-opacity='0.18' stroke='none'/>"
                   % " ".join(arriba + abajo[::-1]))
    # series
    for clave, nombre, color, grosor, ys in series:
        segs = []
        actual = []
        for x, y in zip(xs, ys):
            if y is None or not math.isfinite(y):
                if actual:
                    segs.append(actual)
                    actual = []
                continue
            actual.append("%.1f,%.1f" % (sx(x), sy(y)))
        if actual:
            segs.append(actual)
        for seg in segs:
            if len(seg) == 1:
                cx, cy = seg[0].split(",")
                out.append("<circle cx='%s' cy='%s' r='2' fill='%s'/>" % (cx, cy, color))
            else:
                out.append("<polyline points='%s' fill='none' stroke='%s' stroke-width='%.1f'/>"
                           % (" ".join(seg), color, grosor))
    # leyenda
    lx = ml + 8
    for _, nombre, color, _, ys in series:
        if not any(v is not None and math.isfinite(v) for v in ys):
            continue
        out.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='%s' stroke-width='2'/>" % (lx, mt + 8, lx + 18, mt + 8, color))
        out.append("<text x='%d' y='%d' fill='#1f2933'>%s</text>" % (lx + 22, mt + 12, nombre))
        lx += 22 + 8 * len(nombre) + 14
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# CSV de curvas cota-volumen
# ---------------------------------------------------------------------------

def escribir_curvas_csv(ruta, curvas):
    """curvas: lista de (escenario, id, filas[(cota, area, volumen)])."""
    with open(ruta, "w", encoding="utf-8-sig") as f:
        f.write("escenario;id_depresion;cota_m;area_m2;volumen_m3\n")
        for esc, did, filas in curvas:
            for cota, area, vol in filas:
                f.write("%s;%d;%.3f;%.1f;%.1f\n" % (esc, did, cota, area, vol))


# ---------------------------------------------------------------------------
# Informe HTML
# ---------------------------------------------------------------------------

def _n(v, dec=2):
    if v is None:
        return "-"
    try:
        if not math.isfinite(v):
            return "-"
    except TypeError:
        return html.escape(str(v))
    s = "{:,.{d}f}".format(v, d=dec)
    return s.replace(",", " ")


CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px auto;max-width:1100px;color:#1f2933;line-height:1.45;padding:0 16px}
h1{font-size:24px;margin-bottom:4px}h2{font-size:18px;margin-top:28px;border-bottom:2px solid #d9e2ec;padding-bottom:4px}
.sub{color:#52606d;margin-top:0}
table{border-collapse:collapse;width:100%;margin:8px 0 16px;font-size:13px}
th,td{border:1px solid #d9e2ec;padding:4px 6px;text-align:right}th{background:#f0f4f8;text-align:center}
td.t{text-align:left}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}
.kpi{border:1px solid #d9e2ec;border-radius:6px;padding:10px 14px;min-width:180px;flex:1}
.kpi b{display:block;font-size:22px;color:#102a43}.kpi span{font-size:12px;color:#52606d}
.aviso{background:#fff8e1;border-left:4px solid #f0b429;padding:8px 12px;margin:10px 0}
.ok{background:#e3f9e5;border-left:4px solid #3ebd93;padding:8px 12px;margin:10px 0}
.cita{background:#f0f4f8;padding:12px;border-radius:6px;font-size:14px}
"""


def informe_html(ruta, datos):
    """Escribe el informe. `datos` es un dict armado por el algoritmo."""
    e = html.escape
    p = datos["parametros"]
    out = []
    w = out.append
    w("<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>")
    w("<title>Cota de anegamiento</title><style>%s</style></head><body>" % CSS)
    w("<h1>Cota de anegamiento – informe de cálculo</h1>")
    w("<p class='sub'>Generado el %s con el complemento QGIS «Cota de Anegamiento». "
      "Resultado referencial para estudios a nivel de perfil.</p>"
      % datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))

    # --- Resumen -----------------------------------------------------------
    w("<h2>1. Resultado principal</h2>")
    r = datos.get("resumen_eje")
    if r:
        w("<div class='kpis'>")
        w("<div class='kpi'><b>%s msnm</b><span>Cota de agua máxima a lo largo del eje</span></div>"
          % _n(r["cota_max"]))
        w("<div class='kpi'><b>%s m</b><span>Tirante máximo sobre el terreno</span></div>" % _n(r["tirante_max"]))
        w("<div class='kpi'><b>%s msnm</b><span>Rasante mínima recomendada (máx.)</span></div>"
          % _n(r["rasante_max"]))
        w("<div class='kpi'><b>%s m</b><span>Longitud de eje con anegamiento</span></div>"
          % _n(r["long_anegada"], 0))
        w("</div>")
        w("<p>Rasante mínima = cota de diseño + borde libre (%s m). La cota de diseño en cada punto es la "
          "mayor entre el encharcamiento pluvial (sin vía y con vía) y el desborde en lámina, "
          "buscando agua en un radio de %s m alrededor del eje.</p>" % (_n(p["borde_libre"]), _n(p["radio"], 0)))
        tr = datos.get("tramos") or []
        if tr:
            w("<h3>Tramos anegados</h3><table><tr><th>Desde</th><th>Hasta</th><th>Cota de agua máx. (msnm)</th>"
              "<th>Tirante máx. (m)</th><th>Rasante mín. (msnm)</th><th>Controla</th></tr>")
            for t in tr:
                w("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='t'>%s</td></tr>"
                  % (progresiva_km(t["inicio"]), progresiva_km(t["fin"]), _n(t["cota_max"]),
                     _n(t["tirante_max"]), _n(t["rasante_max"]), e(", ".join(sorted(t["controles"])))))
            w("</table>")
        else:
            w("<div class='ok'>Ningún punto del eje queda anegado con los parámetros usados.</div>")
    else:
        w("<div class='aviso'>No se ingresó eje de vía: el informe muestra las depresiones de todo el DEM. "
          "Para obtener la cota a lo largo de la vía, vuelve a ejecutar indicando la capa del eje.</div>")
        top = datos.get("top_depresiones") or []
        if top:
            m = max(top, key=lambda d: d["cota_agua"])
            g = max(top, key=lambda d: d["tirante_max_m"])
            w("<div class='kpis'>")
            w("<div class='kpi'><b>%s msnm</b><span>Cota de agua más alta entre las depresiones analizadas "
              "(id %d)</span></div>" % (_n(m["cota_agua"]), m["id"]))
            w("<div class='kpi'><b>%s m</b><span>Tirante máximo (depresión id %d)</span></div>"
              % (_n(g["tirante_max_m"]), g["id"]))
            w("<div class='kpi'><b>%d</b><span>Depresiones analizadas</span></div>"
              % datos["escenarios"][0]["n_validas"])
            w("</div>")

    # --- Parámetros --------------------------------------------------------
    w("<h2>2. Datos de entrada</h2><table>")
    filas = [
        ("DEM", p["dem"]),
        ("Preparación automática del DEM", p.get("preproceso") or "ninguna (se usó tal cual)"),
        ("Tamaño de celda", "%s × %s m" % (_n(p["celda_x"]), _n(p["celda_y"]))),
        ("Filas × columnas", "%d × %d" % (p["filas"], p["cols"])),
        ("Sistema de coordenadas", p["crs"]),
        ("Modo de cálculo", p["modo"]),
        ("Filtro de ruido", "profundidad ≥ %s m y área ≥ %s m²" % (_n(p["prof_min"]), _n(p["area_min"], 0))),
        ("Eje de la vía", p.get("eje") or "no ingresado"),
        ("Red de drenes", p.get("drenes") or "no ingresada"),
        ("Altura de terraplén (escenario con vía)", "%s m" % _n(p["altura_terraplen"]) if p.get("con_via") else "no evaluado"),
        ("Borde libre", "%s m" % _n(p["borde_libre"])),
    ]
    for k, v in filas:
        w("<tr><td class='t'><b>%s</b></td><td class='t'>%s</td></tr>" % (e(k), e(str(v))))
    w("</table>")

    # --- Lluvia --------------------------------------------------------------
    h = datos["hidrologia"]
    w("<h2>3. Lluvia de diseño y escorrentía</h2>")
    if h.get("gumbel"):
        g = h["gumbel"]
        w("<p>Precipitación de diseño calculada con la distribución de <b>Gumbel</b> (método de momentos) "
          "a partir de %d valores de máximas anuales:</p>" % g["n"])
        w("<table><tr><th>Media (mm)</th><th>Desv. estándar (mm)</th><th>Tr (años)</th><th>K<sub>T</sub></th>"
          "<th>P<sub>T</sub> (mm)</th></tr><tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><b>%s</b></td></tr></table>"
          % (_n(g["media"]), _n(g["desv"]), _n(g["tr"], 0), _n(g["kt"], 3), _n(h["p"])))
        w("<p>K<sub>T</sub> = −(√6/π)·[0.5772 + ln(ln(T/(T−1)))] ; P<sub>T</sub> = media + K<sub>T</sub>·s</p>")
        w("<div class='aviso'>En Piura la serie mezcla años normales y años El Niño. Si el ajuste Gumbel simple "
          "se ve bajo frente a 1983, 1998 o 2017, usa como lluvia de diseño el valor de un ajuste Doble Gumbel "
          "o el acumulado observado del evento El Niño.</div>")
    else:
        w("<p>Precipitación de diseño ingresada directamente: <b>%s mm</b>.</p>" % _n(h["p"]))
    if h["metodo"] == "scs":
        w("<p>Escorrentía por el método del <b>Número de Curva SCS</b> con CN = %s: "
          "S = 25400/CN − 254 = %s mm ; Q = (P − 0.2S)² / (P + 0.8S) = <b>%s mm</b>.</p>"
          % (_n(h["cn"], 1), _n(h["s"], 1), _n(h["lamina"])))
    else:
        w("<p>Escorrentía con coeficiente C = %s: Q = C·P = <b>%s mm</b>.</p>" % (_n(h["c"]), _n(h["lamina"])))
    w("<p>Volumen escurrido hacia cada depresión = Q × área de aporte + excedentes de las depresiones aguas arriba.</p>")

    # --- Drenes --------------------------------------------------------------
    dr = datos.get("drenes")
    if dr:
        w("<h2>Red de drenes</h2>")
        w("<p>Capa <b>%s</b>: %d drenes. Duración del evento: %s h. Volumen que un dren puede evacuar de una "
          "depresión = capacidad × duración; si varios drenes cruzan la misma depresión se suman. "
          "%s</p>" % (e(dr["capa"]), dr["n"], _n(dr["duracion_h"], 1),
                      "Los drenes se grabaron en el DEM con su profundidad, de modo que conectan las "
                      "depresiones que atraviesan." if dr.get("grabados") else
                      "Los drenes no se grabaron en el DEM (profundidad 0): solo descuentan volumen."))
        w("<table><tr><th>Id</th><th>Nombre</th><th>Ancho (m)</th><th>Profundidad (m)</th>"
          "<th>Capacidad (m³/s)</th><th>Vol. evacuable (m³)</th><th>Depresiones que cruza</th></tr>")
        for d in dr["lista"]:
            w("<tr><td>%d</td><td class='t'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
              % (d["id"], e(str(d.get("nombre") or "")), _n(d["ancho"]), _n(d["prof"]), _n(d["q"], 3),
                 _n(d["q"] * dr["duracion_h"] * 3600.0, 0), e(", ".join(str(i) for i in d.get("depresiones", [])) or "-")))
        w("</table>")
        w("<div class='aviso'>Simplificación: se supone que el dren funciona a su capacidad durante toda la "
          "duración del evento y que descarga fuera de la zona de estudio. Las alcantarillas que cruzan la vía "
          "no se modelan; revisa que los drenes tengan salida real aguas abajo.</div>")

    # --- Depresiones -------------------------------------------------------
    for esc in datos["escenarios"]:
        w("<h2>%s</h2>" % e(esc["titulo"]))
        w("<p>Depresiones encontradas: %d · descartadas como ruido del DEM: %d · analizadas: %d.</p>"
          % (esc["n_total"], esc["n_ruido"], esc["n_validas"]))
        lista = esc["tabla"]
        if not lista:
            w("<p>No hay depresiones que mostrar.</p>")
            continue
        w("<p>%s</p>" % e(esc["nota_tabla"]))
        w("<table><tr><th>Id</th><th>Prog. cercana</th><th>Área (m²)</th><th>Fondo (msnm)</th><th>Rebose (msnm)</th>"
          "<th>Vol. rebose (m³)</th><th>Área aporte (ha)</th><th>Vol. entrada (m³)</th><th>¿Se llena?</th>"
          "<th>Cota de agua (msnm)</th><th>Tirante máx. (m)</th><th>Observación</th></tr>")
        for d in lista:
            obs = []
            if d.get("vierte_sobre_via"):
                obs.append("Vierte sobre la vía: requiere alcantarilla")
            elif d.get("toca_via"):
                obs.append("Toca la vía")
            if d.get("vol_dren_m3", 0) > 0:
                obs.append("Dren %s evacúa %s m³" % (", ".join(str(i) for i in d.get("drenes", [])),
                                                     _n(d["vol_dren_m3"], 0)))
            elif d.get("drenes"):
                obs.append("Cruzado por dren %s" % ", ".join(str(i) for i in d["drenes"]))
            w("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
              "<td>%s</td><td><b>%s</b></td><td>%s</td><td class='t'>%s</td></tr>"
              % (d["id"], progresiva_km(d.get("progresiva")), _n(d["area_m2"], 0), _n(d["cota_fondo"]),
                 _n(d["cota_rebose"]), _n(d["vol_rebose_m3"], 0), _n(d["area_aporte_m2"] / 10000.0),
                 _n(d["vol_entrada_m3"], 0), "Sí" if d["rebosa"] else "No", _n(d["cota_agua"]),
                 _n(d["tirante_max_m"]), e("; ".join(obs))))
        w("</table>")
        if esc.get("aviso"):
            w("<div class='aviso'>%s</div>" % e(esc["aviso"]))

    # --- Lámina -------------------------------------------------------------
    lam = datos.get("lamina")
    w("<h2>Desborde del río en lámina (Manning, canal muy ancho)</h2>")
    if lam and lam["y"] > 0:
        w("<p>q = Q<sub>desbordado</sub> / B = %s / %s = %s m²/s ; y = (n·q/√S)<sup>3/5</sup> con n = %s y S = %s "
          "→ <b>y = %s m</b> ; velocidad = q/y = %s m/s.</p>"
          % (_n(lam["Q"], 1), _n(lam["B"], 0), _n(lam["q"], 3), _n(lam["n"], 3), _n(lam["S"], 5),
             _n(lam["y"]), _n(lam["v"])))
        w("<p>La cota por desborde en cada punto del eje es terreno + %s m.</p>" % _n(lam["y"]))
    else:
        w("<p>No evaluado (caudal desbordado = 0).</p>")

    # --- Perfil ------------------------------------------------------------
    perfil = datos.get("perfil") or []
    if perfil:
        w("<h2>Perfil a lo largo del eje</h2>")
        svg = grafico_perfil_svg(perfil)
        if svg:
            w("<div style='border:1px solid #d9e2ec;border-radius:6px;padding:6px;margin:8px 0'>%s</div>" % svg)
            w("<p class='sub'>Zona sombreada: tramos anegados (entre el terreno y la cota de diseño).</p>")
        paso = max(len(perfil) // 300, 1)
        if paso > 1:
            w("<p>Se muestra 1 de cada %d puntos; la capa de puntos del eje tiene todos.</p>" % paso)
        w("<table><tr><th>Progresiva</th><th>Terreno</th><th>Agua sin vía</th><th>Agua con vía</th>"
          "<th>Lámina desborde</th><th>Cota de diseño</th><th>Rasante mín.</th><th>Altura mín. terraplén (m)</th>"
          "<th>Controla</th></tr>")
        for i, q in enumerate(perfil):
            if i % paso and q["control"] == "Sin anegamiento":
                continue
            w("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><b>%s</b></td><td>%s</td>"
              "<td>%s</td><td class='t'>%s</td></tr>"
              % (progresiva_km(q["progresiva"]), _n(q["terreno"]), _n(q["agua_sin_via"]), _n(q["agua_con_via"]),
                 _n(q["lamina_desborde"]), _n(q["cota_diseno"]), _n(q["rasante_min"]), _n(q["altura_min"]),
                 e(q["control"])))
        w("</table>")

    # --- Limitaciones y texto para el perfil ------------------------------
    w("<h2>Limitaciones</h2><ul>")
    for t in [
        "La precisión depende del DEM. Con DEM satelitales de 30 m (error vertical de 1 a 3 m) los resultados son "
        "solo indicativos; con LiDAR o topografía propia son mucho más confiables.",
        "Las celdas sin datos y los bordes del DEM se tratan como salidas de agua. Usa un DEM más grande que la "
        "zona de estudio.",
        "Cuando una depresión no se llena, su nivel se calcula como un solo espejo de agua sobre toda la depresión.",
        "No se consideran infiltración durante el evento, evaporación, bombeo ni alcantarillas existentes. Los "
        "drenes solo se consideran si se ingresa la red de drenes, y como un descuento de volumen a capacidad "
        "constante.",
        "El escenario «con vía» supone un terraplén continuo sin alcantarillas: muestra dónde se represa el agua y "
        "sirve para ubicar las obras de cruce, no para dimensionarlas.",
        "El desborde del río se evalúa solo con la fórmula de lámina; no reemplaza un modelo hidráulico 2D.",
    ]:
        w("<li>%s</li>" % e(t))
    w("</ul>")
    w("<h2>Texto sugerido para el perfil</h2><div class='cita'>%s</div>" % e(datos["texto_perfil"]))
    w("</body></html>")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def texto_perfil(datos):
    """Párrafo de sustento metodológico listo para pegar en el perfil."""
    h = datos["hidrologia"]
    p = datos["parametros"]
    r = datos.get("resumen_eje")
    lluvia = ("una precipitación de diseño de %s mm obtenida con la distribución de Gumbel para un periodo de "
              "retorno de %s años" % (_n(h["p"], 1), _n(h["gumbel"]["tr"], 0))) if h.get("gumbel") else \
        "una precipitación de diseño de %s mm" % _n(h["p"], 1)
    esc = ("el método del Número de Curva SCS (CN = %s)" % _n(h["cn"], 0)) if h["metodo"] == "scs" else \
        ("un coeficiente de escorrentía C = %s" % _n(h["c"]))
    t = ("Ante la ausencia de registros de huellas de inundación y de evaluaciones de riesgo para el ámbito del "
         "proyecto, la cota de anegamiento se determinó por un método teórico sobre el modelo digital de elevación "
         "(celda de %s m): se identificaron las depresiones naturales del terreno mediante el algoritmo de relleno "
         "Priority-Flood, descartando como ruido las de profundidad menor a %s m o área menor a %s m², y se "
         "realizó un balance hídrico en cascada entre el volumen escurrido y la curva cota-volumen de cada "
         "depresión, con %s y %s. "
         % (_n(p["celda_x"], 1), _n(p["prof_min"]), _n(p["area_min"], 0), lluvia, esc))
    dr = datos.get("drenes")
    if dr:
        t += ("Se consideró la red de drenes existente (%d drenes) descontando de cada depresión el volumen "
              "que sus drenes pueden evacuar durante el evento (capacidad × %s h). "
              % (dr["n"], _n(dr["duracion_h"], 0)))
    lam = datos.get("lamina")
    if lam and lam["y"] > 0:
        t += ("Adicionalmente se verificó el desborde del río como flujo en lámina con la ecuación de Manning para "
              "canal muy ancho, obteniéndose un tirante de %s m. " % _n(lam["y"]))
    if p.get("con_via"):
        t += ("Se evaluó el efecto de represamiento del terraplén de la vía (altura %s m, sin alcantarillas) para "
              "ubicar las obras de cruce necesarias. " % _n(p["altura_terraplen"]))
    if r:
        t += ("La cota de agua máxima resultante a lo largo del eje es %s msnm y la rasante mínima recomendada, "
              "incluyendo un borde libre de %s m, es %s msnm. "
              % (_n(r["cota_max"]), _n(p["borde_libre"]), _n(r["rasante_max"])))
    t += ("Estos valores son referenciales y deberán validarse en la etapa de expediente técnico con levantamiento "
          "topográfico de detalle, identificación de huellas de inundación y modelamiento hidráulico.")
    return t
