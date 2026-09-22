# -*- coding: utf-8 -*-
# Complemento QGIS «Cota de Anegamiento»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
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
