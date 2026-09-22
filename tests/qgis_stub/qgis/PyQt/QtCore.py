class QCoreApplication:
    @staticmethod
    def translate(contexto, texto):
        return texto


class QVariant:
    Double = "double"
    Int = "int"
    String = "string"


class _Tipo:
    Double = "double"
    Int = "int"
    QString = "string"


class QMetaType:
    Type = _Tipo


class QUrl:
    def __init__(self, *a, **k):
        pass

    @staticmethod
    def fromLocalFile(ruta):
        return QUrl(ruta)
