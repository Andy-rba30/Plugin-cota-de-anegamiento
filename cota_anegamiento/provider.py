# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider

from .algoritmo import CotaAnegamientoAlgorithm, CotaAnegamientoRapidoAlgorithm


class CotaAnegamientoProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(CotaAnegamientoRapidoAlgorithm())
        self.addAlgorithm(CotaAnegamientoAlgorithm())

    def id(self):
        return "cotaanegamiento"

    def name(self):
        return "Cota de Anegamiento"

    def longName(self):
        return self.name()

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))
