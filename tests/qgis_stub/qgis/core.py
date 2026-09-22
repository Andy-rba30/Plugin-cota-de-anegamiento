"""Clases mínimas de qgis.core usadas por el complemento en tiempo de importación
y en initAlgorithm()."""


class _Enum:
    def __getattr__(self, nombre):
        return nombre


class Qgis:
    QGIS_VERSION_INT = 34000
    ProcessingNumberParameterType = _Enum()
    ProcessingSourceType = _Enum()
    WkbType = _Enum()
    ProcessingParameterFlag = type("F", (), {"Advanced": 2})
    ProcessingFieldParameterDataType = _Enum()
    RasterBandStatistic = _Enum()
    ShaderInterpolationMethod = _Enum()


class QgsProcessing:
    TypeVectorLine = "line"


class QgsWkbTypes:
    MultiPolygon = "MultiPolygon"
    Point = "Point"


class QgsProcessingParameterDefinition:
    FlagAdvanced = 2

    def __init__(self, name, description="", *a, **k):
        self._name = name
        self._description = description
        self._flags = 0
        self.kwargs = k
        self.args = a

    def name(self):
        return self._name

    def description(self):
        return self._description

    def flags(self):
        return self._flags

    def setFlags(self, f):
        self._flags = f

    def isDestination(self):
        return False


class QgsProcessingParameterRasterLayer(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterExtent(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterFeatureSource(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterNumber(QgsProcessingParameterDefinition):
    Double = "double"
    Integer = "int"


class QgsProcessingParameterString(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterEnum(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterField(QgsProcessingParameterDefinition):
    Numeric = "numeric"


class QgsProcessingParameterBoolean(QgsProcessingParameterDefinition):
    pass


class _Destino(QgsProcessingParameterDefinition):
    def isDestination(self):
        return True


class QgsProcessingParameterFeatureSink(_Destino):
    pass


class QgsProcessingParameterRasterDestination(_Destino):
    pass


class QgsProcessingParameterFileDestination(_Destino):
    pass


class QgsProcessingOutputNumber:
    def __init__(self, name, description=""):
        self._name = name

    def name(self):
        return self._name


class QgsProcessingOutputString(QgsProcessingOutputNumber):
    pass


class QgsProcessingAlgorithm:
    def __init__(self):
        self._params = []
        self._outputs = []

    def addParameter(self, p):
        assert p.name() not in [q.name() for q in self._params], "parámetro duplicado: %s" % p.name()
        self._params.append(p)
        return True

    def addOutput(self, o):
        self._outputs.append(o)
        return True

    def parameterDefinitions(self):
        return list(self._params)

    def parameterDefinition(self, nombre):
        for p in self._params:
            if p.name() == nombre:
                return p
        return None

    def outputDefinitions(self):
        return list(self._outputs)


class QgsProcessingException(Exception):
    pass


class QgsProcessingLayerPostProcessorInterface:
    def __init__(self):
        pass


class QgsProcessingProvider:
    def __init__(self):
        self._algs = []

    def addAlgorithm(self, a):
        self._algs.append(a)
        return True

    def algorithms(self):
        return list(self._algs)


class _Cualquiera:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, nombre):
        return _Cualquiera()

    def __call__(self, *a, **k):
        return _Cualquiera()


for _n in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsFeature", "QgsField", "QgsFields",
           "QgsGeometry", "QgsPointXY", "QgsApplication", "QgsRasterFileWriter"):
    globals()[_n] = type(_n, (_Cualquiera,), {})
