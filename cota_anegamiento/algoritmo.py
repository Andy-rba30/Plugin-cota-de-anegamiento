# -*- coding: utf-8 -*-
"""
Algoritmos de Procesos de QGIS del complemento «Cota de Anegamiento».

- CotaAnegamientoAlgorithm: análisis completo (todos los parámetros a la vista).
- CotaAnegamientoRapidoAlgorithm: análisis con solo el DEM; el resto de
  parámetros queda en «Parámetros avanzados» con valores por defecto.

El DEM se prepara automáticamente: recorte a la zona elegida, reproyección
a UTM si viene en grados, remuestreo si tiene demasiadas celdas y relleno
de huecos pequeños sin datos.
"""

import math
import os

import numpy as np

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsWkbTypes,
)

from . import core, herramientas

# Límite de celdas a partir del cual el DEM se remuestrea automáticamente
MAX_CELDAS_AUTO = 6_000_000

# ---------------------------------------------------------------------------
# Compatibilidad entre versiones de QGIS 3.x (y QGIS 4)
# ---------------------------------------------------------------------------

try:
    _NUM_DOUBLE = Qgis.ProcessingNumberParameterType.Double
    _NUM_INT = Qgis.ProcessingNumberParameterType.Integer
except AttributeError:
    _NUM_DOUBLE = QgsProcessingParameterNumber.Double
    _NUM_INT = QgsProcessingParameterNumber.Integer

try:
    _TIPO_LINEA = Qgis.ProcessingSourceType.VectorLine
except AttributeError:
    _TIPO_LINEA = QgsProcessing.TypeVectorLine

try:
    _WKB_POLIGONO = Qgis.WkbType.MultiPolygon
    _WKB_PUNTO = Qgis.WkbType.Point
except AttributeError:
    _WKB_POLIGONO = QgsWkbTypes.MultiPolygon
    _WKB_PUNTO = QgsWkbTypes.Point

if Qgis.QGIS_VERSION_INT >= 33800:
    from qgis.PyQt.QtCore import QMetaType
    _T_DOUBLE, _T_INT, _T_STR = QMetaType.Type.Double, QMetaType.Type.Int, QMetaType.Type.QString
else:
    _T_DOUBLE, _T_INT, _T_STR = QVariant.Double, QVariant.Int, QVariant.String


def _avanzado(param):
    try:
        param.setFlags(param.flags() | Qgis.ProcessingParameterFlag.Advanced)
    except AttributeError:
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
    return param


def _num(v):
    """NaN -> None (NULL en la tabla de atributos)."""
    if v is None:
        return None
    try:
        return None if not math.isfinite(v) else float(v)
    except TypeError:
        return None


def _tr(texto):
    return QCoreApplication.translate("CotaAnegamiento", texto)


# ---------------------------------------------------------------------------
# Estilos automáticos de las capas de salida
# ---------------------------------------------------------------------------

# Referencias vivas a los post-procesadores (QGIS no las conserva por sí solo)
_POST_PROCESADORES = []


def _estilo_pseudocolor(capa, colores):
    """Pseudocolor monobanda continuo entre el mínimo y el máximo de la banda."""
    from qgis.core import (QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer)
    prov = capa.dataProvider()
    try:
        est = prov.bandStatistics(1, Qgis.RasterBandStatistic.All)
    except AttributeError:
        from qgis.core import QgsRasterBandStats
        est = prov.bandStatistics(1, QgsRasterBandStats.All)
    mn, mx = float(est.minimumValue), float(est.maximumValue)
    if not (math.isfinite(mn) and math.isfinite(mx)):
        return
    if mx - mn < 1e-6:
        mx = mn + 1e-6
    fn = QgsColorRampShader()
    try:
        fn.setColorRampType(Qgis.ShaderInterpolationMethod.Linear)
    except AttributeError:
        fn.setColorRampType(QgsColorRampShader.Interpolated)
    n = len(colores)
    items = []
    for i, c in enumerate(colores):
        v = mn + (mx - mn) * i / (n - 1)
        items.append(QgsColorRampShader.ColorRampItem(v, QColor(c), "%.2f" % v))
    fn.setColorRampItemList(items)
    sombreado = QgsRasterShader()
    sombreado.setRasterShaderFunction(fn)
    capa.setRenderer(QgsSingleBandPseudoColorRenderer(prov, 1, sombreado))
    capa.triggerRepaint()


def _estilo_tirante(capa):
    _estilo_pseudocolor(capa, ["#deebf7", "#9ecae1", "#4292c6", "#08519c", "#08306b"])


def _estilo_cota(capa):
    _estilo_pseudocolor(capa, ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"])


def _estilo_aporte(capa):
    """Colores aleatorios por id de área de aporte."""
    from qgis.core import QgsPalettedRasterRenderer
    prov = capa.dataProvider()
    try:
        clases = QgsPalettedRasterRenderer.classDataFromRaster(prov, 1)
        capa.setRenderer(QgsPalettedRasterRenderer(prov, 1, clases))
        capa.triggerRepaint()
    except Exception:
        pass


def _estilo_depresiones(capa):
    """Relleno azul translúcido; borde rojo cuando la depresión vierte sobre la vía."""
    from qgis.core import QgsRuleBasedRenderer, QgsFillSymbol
    base = QgsFillSymbol.createSimple({"color": "43,140,190,110", "outline_color": "8,81,156,255",
                                       "outline_width": "0.4"})
    raiz = QgsRuleBasedRenderer.Rule(None)
    r1 = QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(
        {"color": "220,60,60,120", "outline_color": "160,0,0,255", "outline_width": "0.8"}),
        0, 0, "\"vierte_via\" = 'SI'", _tr("Vierte sobre la vía (alcantarilla)"))
    r2 = QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(
        {"color": "255,170,0,120", "outline_color": "200,110,0,255", "outline_width": "0.6"}),
        0, 0, "\"toca_via\" = 'SI'", _tr("Toca la vía"))
    r3 = QgsRuleBasedRenderer.Rule(base, 0, 0, "ELSE", _tr("Depresión"))
    for r in (r1, r2, r3):
        raiz.appendChild(r)
    capa.setRenderer(QgsRuleBasedRenderer(raiz))
    capa.triggerRepaint()


def _estilo_perfil(capa):
    """Puntos del eje: verde seco, azul/rojo anegado según el tirante."""
    from qgis.core import QgsGraduatedSymbolRenderer, QgsMarkerSymbol, QgsRendererRange
    rangos = [
        (0.0, 0.0001, "#2ecc71", _tr("Sin anegamiento")),
        (0.0001, 0.5, "#74add1", _tr("Tirante hasta 0.5 m")),
        (0.5, 1.0, "#2166ac", _tr("Tirante 0.5 – 1.0 m")),
        (1.0, 1e9, "#b2182b", _tr("Tirante mayor a 1.0 m")),
    ]
    lista = []
    for a, b, color, etiqueta in rangos:
        s = QgsMarkerSymbol.createSimple({"name": "circle", "color": color, "outline_color": "#333333",
                                          "outline_width": "0.2", "size": "2.2"})
        lista.append(QgsRendererRange(a, b, s, etiqueta))
    capa.setRenderer(QgsGraduatedSymbolRenderer("cota_dis - terreno", lista))
    capa.triggerRepaint()


class _PostProcesador(QgsProcessingLayerPostProcessorInterface):
    def __init__(self, funcion, nombre=None):
        super().__init__()
        self.funcion = funcion
        self.nombre = nombre

    def postProcessLayer(self, capa, context, feedback):
        try:
            if self.nombre:
                capa.setName(self.nombre)
            self.funcion(capa)
        except Exception as err:  # el estilo nunca debe hacer fallar el algoritmo
            feedback.pushWarning(_tr("No se pudo aplicar el estilo automático: %s") % err)


def _programar_estilo(context, ruta_o_id, funcion, nombre=None):
    if not ruta_o_id:
        return
    try:
        if context.willLoadLayerOnCompletion(ruta_o_id):
            pp = _PostProcesador(funcion, nombre)
            _POST_PROCESADORES.append(pp)
            detalles = context.layerToLoadOnCompletionDetails(ruta_o_id)
            if nombre:
                detalles.name = nombre
            detalles.setPostProcessor(pp)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# E/S de rásters con GDAL (viene con QGIS)
# ---------------------------------------------------------------------------

def _preparar_dem(ruta, extension=None, celda_objetivo=0.0, max_huecos=10, max_celdas=MAX_CELDAS_AUTO,
                  feedback=None):
    """Abre el DEM con GDAL y lo deja listo para el análisis.

    Devuelve (arr, validos, gt, wkt, notas):
    - arr: array 2D float64 con NaN donde no hay dato;
    - validos: array 2D bool;
    - gt: geotransformación (sin rotación);
    - wkt: sistema de coordenadas de salida;
    - notas: lista de textos con lo que se hizo automáticamente."""
    from osgeo import gdal, osr

    def info(msg):
        if feedback is not None:
            feedback.pushInfo(msg)

    notas = []
    ds = gdal.Open(ruta)
    if ds is None:
        raise QgsProcessingException(_tr("No se pudo abrir el DEM con GDAL: %s") % ruta)
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()

    # 1. Recorte a la zona de estudio
    if extension is not None:
        xmin, ymin, xmax, ymax = extension
        ds = gdal.Translate("", ds, format="MEM", projWin=[xmin, ymax, xmax, ymin])
        if ds is None or ds.RasterXSize == 0 or ds.RasterYSize == 0:
            raise QgsProcessingException(_tr("La extensión elegida no se superpone con el DEM."))
        notas.append(_tr("recorte a la zona indicada"))

    # 2. Sistema de coordenadas
    wkt = ds.GetProjection() or ""
    srs = osr.SpatialReference()
    geografico = False
    if wkt:
        srs.ImportFromWkt(wkt)
        geografico = bool(srs.IsGeographic())
    gt = ds.GetGeoTransform()
    rotado = abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12
    nd_warp = nodata if nodata is not None else -9999.0

    if geografico:
        cx = gt[0] + gt[1] * ds.RasterXSize / 2.0 + gt[2] * ds.RasterYSize / 2.0
        cy = gt[3] + gt[4] * ds.RasterXSize / 2.0 + gt[5] * ds.RasterYSize / 2.0
        epsg = core.epsg_utm(cx, cy)
        celda = celda_objetivo if celda_objetivo > 0 else core.celda_redondeada(
            abs(gt[5]) * 111320.0)
        info(_tr("El DEM está en grados: se reproyecta a EPSG:%d (UTM) con celda de %g m.") % (epsg, celda))
        ds = gdal.Warp("", ds, format="MEM", dstSRS="EPSG:%d" % epsg, xRes=celda, yRes=celda,
                       resampleAlg="bilinear", srcNodata=nodata, dstNodata=nd_warp)
        if ds is None:
            raise QgsProcessingException(_tr("No se pudo reproyectar el DEM a UTM."))
        notas.append(_tr("reproyección automática de grados a EPSG:%d, celda %g m") % (epsg, celda))
        wkt = ds.GetProjection()
        gt = ds.GetGeoTransform()
    elif rotado or (celda_objetivo > 0 and abs(abs(gt[1]) - celda_objetivo) > 1e-9):
        celda = celda_objetivo if celda_objetivo > 0 else core.celda_redondeada(math.hypot(gt[1], gt[2]))
        alg = "average" if celda > abs(gt[1]) * 1.5 else "bilinear"
        info(_tr("Remuestreando el DEM a celda de %g m…") % celda)
        ds = gdal.Warp("", ds, format="MEM", xRes=celda, yRes=celda, resampleAlg=alg,
                       srcNodata=nodata, dstNodata=nd_warp)
        if ds is None:
            raise QgsProcessingException(_tr("No se pudo remuestrear el DEM."))
        notas.append(_tr("remuestreo a celda de %g m") % celda)
        gt = ds.GetGeoTransform()

    # 3. Remuestreo automático si el DEM es demasiado grande
    n = ds.RasterXSize * ds.RasterYSize
    if celda_objetivo <= 0 and n > max_celdas:
        f = core.factor_remuestreo(n, max_celdas)
        celda = core.celda_redondeada(abs(gt[1]) * f)
        if celda > abs(gt[1]):
            info(_tr("El DEM tiene %.1f millones de celdas: se remuestrea a %g m para que el cálculo sea "
                     "manejable. Fija el «tamaño de celda de trabajo» si prefieres otro valor.")
                 % (n / 1e6, celda))
            ds = gdal.Warp("", ds, format="MEM", xRes=celda, yRes=celda, resampleAlg="average",
                           srcNodata=nodata, dstNodata=nd_warp)
            if ds is None:
                raise QgsProcessingException(_tr("No se pudo remuestrear el DEM."))
            notas.append(_tr("remuestreo automático a celda de %g m por tamaño (%.1f millones de celdas)")
                         % (celda, n / 1e6))
            gt = ds.GetGeoTransform()

    # 4. Relleno de huecos pequeños sin datos
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    if max_huecos and max_huecos > 0 and nodata is not None:
        arr0 = banda.ReadAsArray()
        huecos = np.isclose(arr0, nodata) | ~np.isfinite(arr0)
        # Solo se rellenan los huecos interiores: los grupos de celdas sin dato
        # que tocan el borde del DEM son «exterior» y se dejan como están.
        interior = core.huecos_interiores(huecos)
        if interior.any():
            if ds.GetDriver().ShortName != "MEM":
                ds = gdal.GetDriverByName("MEM").CreateCopy("", ds)
                banda = ds.GetRasterBand(1)
            mds = gdal.GetDriverByName("MEM").Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
            mb = mds.GetRasterBand(1)
            mb.WriteArray(np.where(interior, 0, 255).astype(np.uint8))  # 0 = celda a interpolar
            gdal.FillNodata(targetBand=banda, maskBand=mb, maxSearchDist=int(max_huecos),
                            smoothingIterations=0)
            banda.FlushCache()
            n_huecos = int(interior.sum())
            notas.append(_tr("relleno de %d celdas sin dato en huecos interiores (búsqueda máxima %d celdas)")
                         % (n_huecos, int(max_huecos)))
            info(_tr("Se rellenaron %d celdas sin dato en huecos interiores del DEM.") % n_huecos)

    gt = ds.GetGeoTransform()
    if abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12:
        raise QgsProcessingException(_tr("El DEM sigue rotado tras el remuestreo; reproyéctalo manualmente."))
    banda = ds.GetRasterBand(1)
    arr = banda.ReadAsArray().astype(np.float64)
    nodata = banda.GetNoDataValue()
    validos = np.isfinite(arr)
    if nodata is not None:
        validos &= ~np.isclose(arr, nodata)
    validos &= arr > -1000  # valores basura típicos (-32768, -9999)
    arr = np.where(validos, arr, np.nan)
    return arr, validos, gt, ds.GetProjection() or wkt, notas


def _escribir_raster(ruta, arr, gt, wkt, nodata=-9999.0, entero=False):
    from osgeo import gdal
    from qgis.core import QgsRasterFileWriter
    ext = os.path.splitext(ruta)[1].lower().lstrip(".")
    driver_nombre = QgsRasterFileWriter.driverForExtension(ext) if ext else "GTiff"
    drv = gdal.GetDriverByName(driver_nombre or "GTiff") or gdal.GetDriverByName("GTiff")
    filas, cols = arr.shape
    opciones = ["COMPRESS=DEFLATE", "TILED=YES"] if drv.ShortName == "GTiff" else []
    tipo = gdal.GDT_Int32 if entero else gdal.GDT_Float32
    ds = drv.Create(ruta, cols, filas, 1, tipo, options=opciones)
    if ds is None:
        raise QgsProcessingException(_tr("No se pudo crear el ráster de salida: %s") % ruta)
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    if entero:
        b.SetNoDataValue(0)
        b.WriteArray(arr.astype(np.int32))
    else:
        b.SetNoDataValue(nodata)
        b.WriteArray(np.where(np.isfinite(arr), arr, nodata).astype(np.float32))
    b.FlushCache()
    ds = None


def _poligonos(etiquetas, gt, wkt):
    """Polígonos por depresión: dict id -> QgsGeometry."""
    from osgeo import gdal, ogr
    filas, cols = etiquetas.shape
    ds = gdal.GetDriverByName("MEM").Create("", cols, filas, 1, gdal.GDT_Int32)
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    b.WriteArray(etiquetas.astype(np.int32))
    b.SetNoDataValue(0)
    drv = ogr.GetDriverByName("Memory") or ogr.GetDriverByName("MEM")
    vds = drv.CreateDataSource("poligonos")
    capa = vds.CreateLayer("p", geom_type=ogr.wkbPolygon)
    capa.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
    gdal.Polygonize(b, b.GetMaskBand(), capa, 0, ["8CONNECTED=8"], callback=None)
    partes = {}
    for f in capa:
        i = f.GetField(0)
        if i:
            partes.setdefault(i, []).append(QgsGeometry.fromWkt(f.GetGeometryRef().ExportToWkt()))
    salida = {}
    for i, geoms in partes.items():
        g = geoms[0] if len(geoms) == 1 else QgsGeometry.unaryUnion(geoms)
        g.convertToMultiType()
        salida[i] = g
    return salida


# ---------------------------------------------------------------------------
# Algoritmo completo
# ---------------------------------------------------------------------------

class CotaAnegamientoAlgorithm(QgsProcessingAlgorithm):
    DEM = "DEM"
    EXTENSION = "EXTENSION"
    EJE = "EJE"
    P_DISENO = "P_DISENO"
    SERIE = "SERIE"
    TR = "TR"
    METODO = "METODO"
    CN = "CN"
    C = "C"
    MODO = "MODO"
    PROF_MIN = "PROF_MIN"
    AREA_MIN = "AREA_MIN"
    ALTURA_VIA = "ALTURA_VIA"
    RADIO = "RADIO"
    PASO = "PASO"
    BORDE_LIBRE = "BORDE_LIBRE"
    CELDA = "CELDA"
    HUECOS = "HUECOS"
    Q_DESB = "Q_DESB"
    ANCHO_B = "ANCHO_B"
    N_MANNING = "N_MANNING"
    PENDIENTE = "PENDIENTE"
    OUT_DEP = "OUT_DEPRESIONES"
    OUT_EJE = "OUT_EJE"
    OUT_TIRANTE = "OUT_TIRANTE"
    OUT_COTA = "OUT_COTA_AGUA"
    OUT_TIRANTE_VIA = "OUT_TIRANTE_VIA"
    OUT_APORTE = "OUT_APORTE"
    OUT_INFORME = "OUT_INFORME"
    OUT_CURVAS = "OUT_CURVAS"
    RES_COTA_MAX = "COTA_AGUA_MAX"
    RES_RASANTE = "RASANTE_MIN"
    RES_TIRANTE = "TIRANTE_MAX"
    RES_N_DEP = "N_DEPRESIONES"
    RES_RESUMEN = "RESUMEN"

    METODOS = ["Número de Curva SCS (recomendado)", "Coeficiente de escorrentía C"]
    MODOS = ["Balance hídrico con la lluvia de diseño (recomendado)",
             "Llenado hasta el rebose (envolvente máxima, más conservador)"]

    def tr(self, texto):
        return _tr(texto)

    def createInstance(self):
        return CotaAnegamientoAlgorithm()

    def name(self):
        return "cota_anegamiento"

    def displayName(self):
        return self.tr("Cota de anegamiento por depresiones del DEM (completo)")

    def group(self):
        return self.tr("Hidrología vial")

    def groupId(self):
        return "hidrologia_vial"

    def shortHelpString(self):
        return self.tr(
            "<p>Calcula la <b>cota de anegamiento teórica</b> a partir de un DEM, sin trabajo de campo.</p>"
            "<ol><li>Prepara el DEM: recorta a la zona elegida, lo reproyecta a UTM si está en grados, "
            "lo remuestrea si es muy grande y rellena los huecos pequeños sin datos.</li>"
            "<li>Rellena las depresiones del DEM (Priority-Flood) y obtiene la cota de rebose de cada una.</li>"
            "<li>Descarta como ruido las depresiones poco profundas o pequeñas.</li>"
            "<li>Calcula el área de aporte de cada depresión y hace un balance hídrico en cascada con la lluvia de "
            "diseño (SCS-CN o coeficiente C).</li>"
            "<li>Si das el eje de la vía, entrega la cota de agua y la rasante mínima cada cierta distancia, y "
            "repite el análisis con la vía en terraplén para ver dónde se represa el agua (dónde van alcantarillas).</li>"
            "<li>Opcional: tirante del desborde del río en lámina con Manning.</li></ol>"
            "<p><b>Lo único obligatorio es el DEM.</b> Conviene que cubra la zona de estudio con un margen de "
            "2 a 3 km, porque los bordes del DEM se tratan como salidas de agua.</p>"
            "<p>Las capas de salida se cargan ya con simbología. El resultado es referencial, para estudios a "
            "nivel de perfil.</p>")

    # ------------------------------------------------------------------
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.DEM, self.tr("DEM (modelo digital de elevación)")))
        self.addParameter(QgsProcessingParameterExtent(
            self.EXTENSION, self.tr("Zona a analizar (opcional; vacío = todo el DEM)"), optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.EJE, self.tr("Eje de la vía (línea, opcional pero recomendado)"), [_TIPO_LINEA], optional=True))

        self.addParameter(QgsProcessingParameterNumber(
            self.P_DISENO, self.tr("Precipitación de diseño (mm) – se usa si no ingresas serie"),
            type=_NUM_DOUBLE, defaultValue=150.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterString(
            self.SERIE, self.tr("Serie de precipitaciones máximas anuales en mm, separadas por comas "
                                "(opcional: calcula la lluvia de diseño con Gumbel)"),
            optional=True, multiLine=False))
        self.addParameter(QgsProcessingParameterNumber(
            self.TR, self.tr("Periodo de retorno para Gumbel (años)"),
            type=_NUM_DOUBLE, defaultValue=50.0, minValue=1.01))
        self.addParameter(QgsProcessingParameterEnum(
            self.METODO, self.tr("Método de escorrentía"), options=self.METODOS, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CN, self.tr("Número de curva CN (condición húmeda; arcillas cultivadas 85–92)"),
            type=_NUM_DOUBLE, defaultValue=88.0, minValue=1.0, maxValue=100.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.C, self.tr("Coeficiente de escorrentía C (si usas ese método)"),
            type=_NUM_DOUBLE, defaultValue=0.60, minValue=0.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.MODO, self.tr("Modo de cálculo"), options=self.MODOS, defaultValue=0))

        self.addParameter(QgsProcessingParameterNumber(
            self.PROF_MIN, self.tr("Profundidad mínima para aceptar una depresión (m) – filtro de ruido"),
            type=_NUM_DOUBLE, defaultValue=0.30, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_MIN, self.tr("Área mínima para aceptar una depresión (m²) – filtro de ruido"),
            type=_NUM_DOUBLE, defaultValue=2000.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.ALTURA_VIA, self.tr("Altura del terraplén para el escenario con vía (m; 0 = no evaluar)"),
            type=_NUM_DOUBLE, defaultValue=2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BORDE_LIBRE, self.tr("Borde libre (m)"), type=_NUM_DOUBLE, defaultValue=0.50, minValue=0.0))

        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.CELDA, self.tr("Tamaño de celda de trabajo (m; 0 = automático)"),
            type=_NUM_DOUBLE, defaultValue=0.0, minValue=0.0)))
        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.HUECOS, self.tr("Rellenar huecos sin datos de hasta N celdas (0 = no rellenar)"),
            type=_NUM_INT, defaultValue=10, minValue=0)))
        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.RADIO, self.tr("Radio de búsqueda de agua alrededor del eje (m)"),
            type=_NUM_DOUBLE, defaultValue=50.0, minValue=0.0)))
        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.PASO, self.tr("Distancia entre puntos del perfil del eje (m)"),
            type=_NUM_DOUBLE, defaultValue=20.0, minValue=1.0)))

        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.Q_DESB, self.tr("Desborde del río: caudal desbordado (m³/s; 0 = no evaluar)"),
            type=_NUM_DOUBLE, defaultValue=0.0, minValue=0.0)))
        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.ANCHO_B, self.tr("Desborde del río: ancho de la franja inundable B (m)"),
            type=_NUM_DOUBLE, defaultValue=3000.0, minValue=1.0)))
        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.N_MANNING, self.tr("Desborde del río: rugosidad de Manning n de la llanura"),
            type=_NUM_DOUBLE, defaultValue=0.035, minValue=0.001)))
        self.addParameter(_avanzado(QgsProcessingParameterNumber(
            self.PENDIENTE, self.tr("Desborde del río: pendiente del valle S (m/m)"),
            type=_NUM_DOUBLE, defaultValue=0.00036, minValue=0.0000001)))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DEP, self.tr("Depresiones (polígonos con resultados)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_EJE, self.tr("Perfil del eje (puntos con cota de agua y rasante)"),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUT_TIRANTE, self.tr("Tirante de agua sin vía (m)")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUT_COTA, self.tr("Cota de agua sin vía (msnm)")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUT_TIRANTE_VIA, self.tr("Tirante de agua con vía en terraplén (m)"),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUT_APORTE, self.tr("Áreas de aporte por depresión (id)"),
            optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUT_INFORME, self.tr("Informe de cálculo"), fileFilter="HTML (*.html)"))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUT_CURVAS, self.tr("Curvas cota-volumen (CSV)"), fileFilter="CSV (*.csv)",
            optional=True, createByDefault=True))

        # Salidas numéricas para usar en el modelador
        self.addOutput(QgsProcessingOutputNumber(self.RES_COTA_MAX, self.tr("Cota de agua máxima (msnm)")))
        self.addOutput(QgsProcessingOutputNumber(self.RES_RASANTE, self.tr("Rasante mínima (msnm)")))
        self.addOutput(QgsProcessingOutputNumber(self.RES_TIRANTE, self.tr("Tirante máximo (m)")))
        self.addOutput(QgsProcessingOutputNumber(self.RES_N_DEP, self.tr("Depresiones analizadas")))
        self.addOutput(QgsProcessingOutputString(self.RES_RESUMEN, self.tr("Resumen")))

    # ------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        capa_dem = self.parameterAsRasterLayer(parameters, self.DEM, context)
        if capa_dem is None:
            raise QgsProcessingException(self.tr("No se pudo cargar el DEM."))
        crs_capa = capa_dem.crs()

        # --- Lectura y preparación del DEM -----------------------------------
        extension = None
        if parameters.get(self.EXTENSION):
            r = self.parameterAsExtent(parameters, self.EXTENSION, context, crs_capa)
            if r is not None and not r.isNull() and not r.isEmpty():
                extension = (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum())
        celda_obj = self.parameterAsDouble(parameters, self.CELDA, context)
        max_huecos = self.parameterAsInt(parameters, self.HUECOS, context)
        feedback.pushInfo(self.tr("Leyendo y preparando el DEM…"))
        fuente = capa_dem.source()
        try:
            dem, validos, gt, wkt, notas = _preparar_dem(fuente, extension, celda_obj, max_huecos,
                                                         feedback=feedback)
        except QgsProcessingException:
            raise
        except Exception as err:
            raise QgsProcessingException(self.tr("Error al preparar el DEM: %s") % err)

        crs = QgsCoordinateReferenceSystem()
        if wkt:
            crs.createFromWkt(wkt)
        if not crs.isValid():
            crs = crs_capa
        if crs.isValid() and crs.isGeographic():
            raise QgsProcessingException(self.tr(
                "El DEM sigue en coordenadas geográficas tras la preparación. Reproyéctalo a un sistema en "
                "metros (por ejemplo WGS 84 / UTM) con Ráster > Proyecciones > Combar (reproyectar)."))
        if not crs.isValid():
            feedback.pushWarning(self.tr("El DEM no tiene sistema de coordenadas: se asume que las unidades "
                                         "son metros."))

        filas, cols = dem.shape
        area_celda = abs(gt[1] * gt[5])
        n_celdas = filas * cols
        feedback.pushInfo(self.tr("DEM de trabajo: %d filas × %d columnas, celda de %.2f × %.2f m (%s).")
                          % (filas, cols, abs(gt[1]), abs(gt[5]), crs.authid() or crs.description()))
        if n_celdas > 25_000_000:
            raise QgsProcessingException(self.tr(
                "El DEM tiene %.1f millones de celdas. Indica un tamaño de celda de trabajo mayor o recorta el "
                "DEM a la zona de estudio.") % (n_celdas / 1e6))
        if n_celdas > MAX_CELDAS_AUTO:
            feedback.pushWarning(self.tr(
                "DEM grande (%.1f millones de celdas): el cálculo puede tardar varios minutos.") % (n_celdas / 1e6))
        if not validos.any():
            raise QgsProcessingException(self.tr("El DEM no tiene celdas con datos válidos en la zona elegida."))
        if abs(abs(gt[1]) - abs(gt[5])) > 1e-6 * abs(gt[1]):
            feedback.pushWarning(self.tr("Las celdas del DEM no son cuadradas (%.3f × %.3f m); el área de celda "
                                         "se toma como su producto.") % (abs(gt[1]), abs(gt[5])))

        # --- Hidrología ------------------------------------------------------
        hid = {}
        serie_txt = (self.parameterAsString(parameters, self.SERIE, context) or "").strip()
        tr_anios = self.parameterAsDouble(parameters, self.TR, context)
        if serie_txt:
            try:
                serie = [float(x.replace(" ", "")) for x in
                         serie_txt.replace(";", ",").replace("\n", ",").split(",") if x.strip()]
                p_t, media, desv, kt, n = core.gumbel(serie, tr_anios)
            except ValueError as err:
                raise QgsProcessingException(self.tr("Serie de precipitaciones no válida: %s") % err)
            hid["p"] = p_t
            hid["gumbel"] = {"media": media, "desv": desv, "kt": kt, "n": n, "tr": tr_anios}
            feedback.pushInfo(self.tr("Lluvia de diseño Gumbel (Tr = %.0f años): %.1f mm") % (tr_anios, p_t))
        else:
            hid["p"] = self.parameterAsDouble(parameters, self.P_DISENO, context)
        metodo = self.parameterAsEnum(parameters, self.METODO, context)
        if metodo == 0:
            cn = self.parameterAsDouble(parameters, self.CN, context)
            hid.update({"metodo": "scs", "cn": cn, "s": 25400.0 / cn - 254.0,
                        "lamina": core.escorrentia_scs(hid["p"], cn)})
        else:
            c = self.parameterAsDouble(parameters, self.C, context)
            hid.update({"metodo": "c", "c": c, "lamina": core.escorrentia_c(hid["p"], c)})
        feedback.pushInfo(self.tr("Lámina escurrida: %.1f mm") % hid["lamina"])

        modo_rebose = self.parameterAsEnum(parameters, self.MODO, context) == 1
        prof_min = self.parameterAsDouble(parameters, self.PROF_MIN, context)
        area_min = self.parameterAsDouble(parameters, self.AREA_MIN, context)
        altura = self.parameterAsDouble(parameters, self.ALTURA_VIA, context)
        borde = self.parameterAsDouble(parameters, self.BORDE_LIBRE, context)
        radio = self.parameterAsDouble(parameters, self.RADIO, context)
        paso = self.parameterAsDouble(parameters, self.PASO, context)
        if area_min < area_celda:
            feedback.pushInfo(self.tr("El área mínima (%.0f m²) es menor que una celda (%.0f m²): se acepta "
                                      "cualquier depresión de una celda o más.") % (area_min, area_celda))

        y_lam, q_lam, v_lam = core.lamina_manning(
            self.parameterAsDouble(parameters, self.Q_DESB, context),
            self.parameterAsDouble(parameters, self.ANCHO_B, context),
            self.parameterAsDouble(parameters, self.N_MANNING, context),
            self.parameterAsDouble(parameters, self.PENDIENTE, context))
        lamina = {"Q": self.parameterAsDouble(parameters, self.Q_DESB, context),
                  "B": self.parameterAsDouble(parameters, self.ANCHO_B, context),
                  "n": self.parameterAsDouble(parameters, self.N_MANNING, context),
                  "S": self.parameterAsDouble(parameters, self.PENDIENTE, context),
                  "y": y_lam, "q": q_lam, "v": v_lam}

        # --- Eje de la vía ---------------------------------------------------
        polilineas = []
        fuente_eje = self.parameterAsSource(parameters, self.EJE, context)
        nombre_eje = None
        if fuente_eje is not None:
            nombre_eje = fuente_eje.sourceName()
            transf = QgsCoordinateTransform(fuente_eje.sourceCrs(), crs, context.transformContext())
            for f in fuente_eje.getFeatures():
                g = QgsGeometry(f.geometry())
                if g.isNull() or g.isEmpty():
                    continue
                if transf.isValid() and fuente_eje.sourceCrs().isValid() and crs.isValid():
                    g.transform(transf)
                partes = g.asGeometryCollection() if g.isMultipart() else [g]
                for parte in partes:
                    pl = parte.asPolyline()
                    if len(pl) >= 2:
                        polilineas.append([(pt.x(), pt.y()) for pt in pl])
            if not polilineas:
                feedback.pushWarning(self.tr("La capa del eje no tiene líneas válidas; se ignora."))
        mascara_via = herramientas.mascara_polilineas(polilineas, gt, dem.shape) if polilineas else None
        if mascara_via is not None and not mascara_via.any():
            feedback.pushWarning(self.tr("El eje de la vía cae fuera del DEM; se ignora."))
            mascara_via, polilineas = None, []
        muestras = herramientas.muestrear_polilineas(polilineas, paso) if polilineas else []

        # --- Escenario sin vía ---------------------------------------------
        con_via = mascara_via is not None and altura > 0
        tramo = 0.5 if con_via else 0.9

        def progreso(a, b):
            return lambda f: feedback.setProgress(100.0 * (a + (b - a) * f))

        feedback.pushInfo(self.tr("Analizando depresiones del terreno natural (sin vía)…"))
        try:
            res_sin = core.analizar(dem, validos, area_celda, hid["lamina"], modo_rebose, prof_min, area_min,
                                    mascara_via=mascara_via, progreso=progreso(0.0, tramo),
                                    cancelado=feedback.isCanceled)
        except RuntimeError as err:
            raise QgsProcessingException(str(err))
        feedback.pushInfo(self.tr("Depresiones: %d en total, %d descartadas como ruido, %d analizadas.")
                          % (res_sin["n_total"], res_sin["n_ruido"], len(res_sin["depresiones"])))
        if res_sin["n_total"] > 0 and not res_sin["depresiones"]:
            feedback.pushWarning(self.tr(
                "Todas las depresiones quedaron descartadas por el filtro de ruido. Baja la profundidad mínima "
                "o el área mínima si esperabas encontrar zonas anegables."))
        elif res_sin["n_total"] > 5000 and res_sin["n_ruido"] < 0.5 * res_sin["n_total"]:
            feedback.pushWarning(self.tr(
                "Se aceptaron %d depresiones: probablemente el DEM tiene ruido. Considera subir la profundidad "
                "mínima (0.5–1.0 m) y el área mínima (5 000–10 000 m²).") % len(res_sin["depresiones"]))

        # --- Escenario con vía ---------------------------------------------
        res_con = None
        dem_con = None
        if con_via:
            feedback.pushInfo(self.tr("Analizando con la vía en terraplén de %.2f m (sin alcantarillas)…") % altura)
            dem_con = core.elevar_via(dem, mascara_via & validos, altura)
            try:
                res_con = core.analizar(dem_con, validos, area_celda, hid["lamina"], modo_rebose, prof_min,
                                        area_min, mascara_via=mascara_via, progreso=progreso(0.5, 0.9),
                                        cancelado=feedback.isCanceled)
            except RuntimeError as err:
                raise QgsProcessingException(str(err))

        # --- Perfil del eje ---------------------------------------------------
        perfil = []
        if muestras:
            perfil = herramientas.perfil_eje(
                muestras, gt, dem, res_sin["cota_agua"], res_con["cota_agua"] if res_con else None,
                radio, y_lam, borde)

        def prog_cercana(d):
            if not muestras:
                return None
            x, y = herramientas.xy_de_celda(d["fila"], d["col"], gt)
            arr = np.asarray([(m[1], m[2]) for m in muestras])
            k = int(np.argmin((arr[:, 0] - x) ** 2 + (arr[:, 1] - y) ** 2))
            return muestras[k][0]

        for res in (res_sin, res_con):
            if res:
                for d in res["depresiones"]:
                    d["progresiva"] = prog_cercana(d) if d["toca_via"] else None

        resultados = {}

        # --- Rásters ----------------------------------------------------------
        feedback.pushInfo(self.tr("Escribiendo rásters…"))
        ruta = self.parameterAsOutputLayer(parameters, self.OUT_TIRANTE, context)
        _escribir_raster(ruta, res_sin["tirante"], gt, wkt)
        resultados[self.OUT_TIRANTE] = ruta
        _programar_estilo(context, ruta, _estilo_tirante, self.tr("Tirante de agua sin vía (m)"))

        ruta = self.parameterAsOutputLayer(parameters, self.OUT_COTA, context)
        _escribir_raster(ruta, res_sin["cota_agua"], gt, wkt)
        resultados[self.OUT_COTA] = ruta
        _programar_estilo(context, ruta, _estilo_cota, self.tr("Cota de agua sin vía (msnm)"))

        if res_con is not None and parameters.get(self.OUT_TIRANTE_VIA) is not None:
            ruta = self.parameterAsOutputLayer(parameters, self.OUT_TIRANTE_VIA, context)
            if ruta:
                _escribir_raster(ruta, res_con["tirante"], gt, wkt)
                resultados[self.OUT_TIRANTE_VIA] = ruta
                _programar_estilo(context, ruta, _estilo_tirante, self.tr("Tirante de agua con vía (m)"))

        if parameters.get(self.OUT_APORTE) is not None:
            ruta = self.parameterAsOutputLayer(parameters, self.OUT_APORTE, context)
            if ruta:
                _escribir_raster(ruta, res_sin["aporte"], gt, wkt, entero=True)
                resultados[self.OUT_APORTE] = ruta
                _programar_estilo(context, ruta, _estilo_aporte, self.tr("Áreas de aporte (id de depresión)"))

        # --- Capa de depresiones ------------------------------------------
        feedback.pushInfo(self.tr("Creando polígonos de depresiones…"))
        campos = QgsFields()
        for nombre, tipo in [("id", _T_INT), ("escenario", _T_STR), ("area_m2", _T_DOUBLE),
                             ("prof_max", _T_DOUBLE), ("cota_fondo", _T_DOUBLE), ("cota_rebo", _T_DOUBLE),
                             ("vol_rebo", _T_DOUBLE), ("a_aporte", _T_DOUBLE), ("vol_entr", _T_DOUBLE),
                             ("excedente", _T_DOUBLE), ("se_llena", _T_STR), ("cota_agua", _T_DOUBLE),
                             ("tirante", _T_DOUBLE), ("toca_via", _T_STR), ("vierte_via", _T_STR),
                             ("prog_cerc", _T_STR), ("aguas_ab", _T_INT)]:
            campos.append(QgsField(nombre, tipo))
        sink, dest = self.parameterAsSink(parameters, self.OUT_DEP, context, campos, _WKB_POLIGONO, crs)
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUT_DEP))
        for esc_nombre, res in (("sin_via", res_sin), ("con_via", res_con)):
            if res is None or not res["depresiones"]:
                continue
            geoms = _poligonos(res["etiquetas"], gt, wkt)
            for d in res["depresiones"]:
                g = geoms.get(d["id"])
                if g is None:
                    continue
                f = QgsFeature(campos)
                f.setGeometry(g)
                f.setAttributes([
                    d["id"], esc_nombre, _num(d["area_m2"]), _num(d["prof_max_m"]), _num(d["cota_fondo"]),
                    _num(d["cota_rebose"]), _num(d["vol_rebose_m3"]), _num(d["area_aporte_m2"]),
                    _num(d["vol_entrada_m3"]), _num(d["excedente_m3"]), "SI" if d["rebosa"] else "NO",
                    _num(d["cota_agua"]), _num(d["tirante_max_m"]), "SI" if d["toca_via"] else "NO",
                    "SI" if d["vierte_sobre_via"] else "NO",
                    herramientas.progresiva_km(d["progresiva"]) if d.get("progresiva") is not None else None,
                    d["aguas_abajo"] or None])
                sink.addFeature(f)
            if feedback.isCanceled():
                break
        try:
            sink.finalize()
        except AttributeError:
            pass
        del sink
        resultados[self.OUT_DEP] = dest
        _programar_estilo(context, dest, _estilo_depresiones, self.tr("Depresiones (cota de anegamiento)"))

        # --- Capa de puntos del eje --------------------------------------
        if perfil and parameters.get(self.OUT_EJE) is not None:
            campos_e = QgsFields()
            for nombre, tipo in [("prog_m", _T_DOUBLE), ("progresiva", _T_STR), ("terreno", _T_DOUBLE),
                                 ("agua_sin", _T_DOUBLE), ("agua_con", _T_DOUBLE), ("lamina", _T_DOUBLE),
                                 ("tir_sin", _T_DOUBLE), ("tir_con", _T_DOUBLE), ("cota_dis", _T_DOUBLE),
                                 ("rasante", _T_DOUBLE), ("alt_min", _T_DOUBLE), ("controla", _T_STR)]:
                campos_e.append(QgsField(nombre, tipo))
            sink_e, dest_e = self.parameterAsSink(parameters, self.OUT_EJE, context, campos_e, _WKB_PUNTO, crs)
            if sink_e is not None:
                for q in perfil:
                    f = QgsFeature(campos_e)
                    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(q["x"], q["y"])))
                    f.setAttributes([
                        _num(q["progresiva"]), herramientas.progresiva_km(q["progresiva"]), _num(q["terreno"]),
                        _num(q["agua_sin_via"]), _num(q["agua_con_via"]), _num(q["lamina_desborde"]),
                        _num(q["tirante_sin_via"]), _num(q["tirante_con_via"]), _num(q["cota_diseno"]),
                        _num(q["rasante_min"]), _num(q["altura_min"]), q["control"]])
                    sink_e.addFeature(f)
                try:
                    sink_e.finalize()
                except AttributeError:
                    pass
                del sink_e
                resultados[self.OUT_EJE] = dest_e
                _programar_estilo(context, dest_e, _estilo_perfil, self.tr("Perfil del eje (cota de agua)"))

        # --- Tablas para el informe --------------------------------------
        def tabla(res, solo_via):
            deps = res["depresiones"]
            if solo_via:
                sel = [d for d in deps if d["toca_via"]]
                return sorted(sel, key=lambda d: d["progresiva"] if d["progresiva"] is not None else 0)
            return sorted(deps, key=lambda d: -d["vol_rebose_m3"])[:20]

        hay_eje = bool(muestras)
        escenarios = [{
            "titulo": "4. Depresiones del terreno natural (sin vía)",
            "n_total": res_sin["n_total"], "n_ruido": res_sin["n_ruido"],
            "n_validas": len(res_sin["depresiones"]),
            "tabla": tabla(res_sin, hay_eje),
            "nota_tabla": ("Depresiones que tocan el eje de la vía (o están a una celda de él)." if hay_eje else
                           "Las 20 depresiones de mayor volumen."),
        }]
        if res_con is not None:
            t = tabla(res_con, True)
            n_vierte = sum(1 for d in t if d["vierte_sobre_via"])
            escenarios.append({
                "titulo": "5. Escenario con la vía en terraplén (sin alcantarillas)",
                "n_total": res_con["n_total"], "n_ruido": res_con["n_ruido"],
                "n_validas": len(res_con["depresiones"]), "tabla": t,
                "nota_tabla": "Depresiones pegadas al terraplén: son las zonas donde la vía represa el agua.",
                "aviso": ("%d depresión(es) llegan a verter por encima de la vía: en esos puntos hacen falta "
                          "alcantarillas u obras de cruce. Ubícalas en el punto más bajo de cada depresión junto a "
                          "la vía." % n_vierte) if n_vierte else
                ("Ninguna depresión llega a rebosar sobre el terraplén, pero las depresiones listadas acumularán "
                 "agua contra el talud: prevé alcantarillas de alivio y protección del talud hasta la cota de agua."),
            })

        resumen = None
        if perfil:
            anegados = [q for q in perfil if q["control"] != "Sin anegamiento"]
            tramos = herramientas.tramos_anegados(perfil)
            long_aneg = sum(max(t["fin"] - t["inicio"], paso) for t in tramos)
            if anegados:
                resumen = {"cota_max": max(q["cota_diseno"] for q in anegados),
                           "tirante_max": max(q["cota_diseno"] - q["terreno"] for q in anegados),
                           "rasante_max": max(q["rasante_min"] for q in anegados),
                           "long_anegada": long_aneg}
            else:
                resumen = {"cota_max": float("nan"), "tirante_max": 0.0,
                           "rasante_max": float("nan"), "long_anegada": 0.0}
        else:
            tramos = []

        datos = {
            "parametros": {
                "dem": capa_dem.name(), "celda_x": abs(gt[1]), "celda_y": abs(gt[5]),
                "filas": filas, "cols": cols, "crs": crs.authid() or crs.description(),
                "preproceso": "; ".join(notas) if notas else None,
                "modo": self.MODOS[1 if modo_rebose else 0], "prof_min": prof_min, "area_min": area_min,
                "eje": nombre_eje, "con_via": con_via, "altura_terraplen": altura,
                "borde_libre": borde, "radio": radio,
            },
            "hidrologia": hid,
            "lamina": lamina,
            "escenarios": escenarios,
            "resumen_eje": resumen,
            "tramos": tramos,
            "perfil": perfil,
            "top_depresiones": escenarios[0]["tabla"],
        }
        datos["texto_perfil"] = herramientas.texto_perfil(datos)

        # --- Curvas cota-volumen -----------------------------------------
        ruta_csv = self.parameterAsFileOutput(parameters, self.OUT_CURVAS, context)
        if ruta_csv:
            curvas = []
            for esc_nombre, res, d_dem in (("sin_via", res_sin, dem), ("con_via", res_con, dem_con)):
                if res is None:
                    continue
                lista = tabla(res, hay_eje or esc_nombre == "con_via")[:30]
                for d in lista:
                    curvas.append((esc_nombre, d["id"], core.curva_cota_volumen(
                        d_dem, res["etiquetas"], d["id"], area_celda, d["cota_rebose"])))
            herramientas.escribir_curvas_csv(ruta_csv, curvas)
            resultados[self.OUT_CURVAS] = ruta_csv

        # --- Informe -----------------------------------------------------
        ruta_html = self.parameterAsFileOutput(parameters, self.OUT_INFORME, context)
        herramientas.informe_html(ruta_html, datos)
        resultados[self.OUT_INFORME] = ruta_html

        # --- Resultados numéricos ----------------------------------------
        deps = res_sin["depresiones"]
        cota_max = float("nan")
        rasante = float("nan")
        tirante_max = 0.0
        if resumen and math.isfinite(resumen["cota_max"]):
            cota_max, rasante, tirante_max = resumen["cota_max"], resumen["rasante_max"], resumen["tirante_max"]
            texto = self.tr("RESULTADO: cota de agua máxima en el eje = %.2f msnm; rasante mínima = %.2f msnm; "
                            "tirante máximo = %.2f m.") % (cota_max, rasante, tirante_max)
        elif resumen:
            texto = self.tr("RESULTADO: ningún punto del eje queda anegado con los parámetros usados.")
        elif deps:
            m = max(deps, key=lambda d: d["cota_agua"])
            g = max(deps, key=lambda d: d["tirante_max_m"])
            cota_max, tirante_max = m["cota_agua"], g["tirante_max_m"]
            rasante = cota_max + borde
            texto = self.tr("RESULTADO: %d depresiones analizadas; cota de agua más alta = %.2f msnm (id %d); "
                            "tirante máximo = %.2f m (id %d). Ingresa el eje de la vía para obtener la rasante "
                            "a lo largo del trazo.") % (len(deps), cota_max, m["id"], tirante_max, g["id"])
        else:
            texto = self.tr("RESULTADO: no se encontraron depresiones que superen el filtro de ruido.")
        feedback.pushInfo(texto)
        resultados[self.RES_COTA_MAX] = cota_max if math.isfinite(cota_max) else None
        resultados[self.RES_RASANTE] = rasante if math.isfinite(rasante) else None
        resultados[self.RES_TIRANTE] = tirante_max
        resultados[self.RES_N_DEP] = len(deps)
        resultados[self.RES_RESUMEN] = texto
        feedback.pushInfo(self.tr("Informe: %s") % ruta_html)
        feedback.setProgress(100)
        return resultados


# ---------------------------------------------------------------------------
# Algoritmo rápido: solo el DEM es visible, el resto va en «avanzados»
# ---------------------------------------------------------------------------

class CotaAnegamientoRapidoAlgorithm(CotaAnegamientoAlgorithm):
    """Misma lógica que el algoritmo completo, pero solo pide el DEM.

    Todos los demás parámetros quedan con sus valores por defecto dentro de
    la sección «Parámetros avanzados», de modo que basta con elegir el DEM y
    pulsar Ejecutar."""

    VISIBLES = (CotaAnegamientoAlgorithm.DEM, CotaAnegamientoAlgorithm.EJE)

    def createInstance(self):
        return CotaAnegamientoRapidoAlgorithm()

    def name(self):
        return "cota_anegamiento_rapido"

    def displayName(self):
        return self.tr("Análisis rápido: cota de anegamiento solo con el DEM")

    def shortHelpString(self):
        return self.tr(
            "<p><b>Elige el DEM y pulsa Ejecutar.</b> Todo lo demás es opcional y tiene valores por defecto "
            "razonables para un estudio a nivel de perfil (lluvia de diseño de 150 mm, CN = 88, filtro de ruido "
            "de 0.30 m y 2 000 m², terraplén de 2 m, borde libre de 0.50 m).</p>"
            "<p>El DEM puede estar en grados o en metros: si está en grados se reproyecta solo a la zona UTM que "
            "corresponde; si es muy grande se remuestrea; los huecos pequeños sin datos se rellenan.</p>"
            "<p>Si además indicas el eje de la vía, obtendrás la cota de agua y la rasante mínima a lo largo del "
            "trazo. Para ajustar lluvia, CN, filtros o el desborde del río, despliega «Parámetros avanzados» o "
            "usa el algoritmo completo.</p>"
            "<p>Salidas: depresiones (polígonos), rásters de tirante y cota de agua, perfil del eje, curvas "
            "cota-volumen (CSV) e informe HTML, todos con simbología automática.</p>")

    def initAlgorithm(self, config=None):
        super().initAlgorithm(config)
        for p in self.parameterDefinitions():
            if p.name() in self.VISIBLES or p.isDestination():
                continue
            _avanzado(p)
