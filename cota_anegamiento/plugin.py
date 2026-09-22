# -*- coding: utf-8 -*-
# Complemento QGIS «Cota de Anegamiento»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.
import os

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
try:
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # Qt6
    from qgis.PyQt.QtGui import QAction
from qgis.core import QgsApplication

from .provider import CotaAnegamientoProvider

ID_ALGORITMO_RAPIDO = "cotaanegamiento:cota_anegamiento_rapido"
ID_ALGORITMO_COMPLETO = "cotaanegamiento:cota_anegamiento"
MENU = "&Cota de Anegamiento"
URL_GUIA = "https://github.com/Andy-rba30/Plugin-cota-de-anegamiento/blob/main/docs/Guia_Cota_Anegamiento.pdf"


class CotaAnegamientoPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.acciones = []

    def initProcessing(self):
        if self.provider is None:
            self.provider = CotaAnegamientoProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        carpeta = os.path.dirname(__file__)
        icono = QIcon(os.path.join(carpeta, "icon.png"))

        rapido = QAction(icono, "Cota de anegamiento (análisis rápido)", self.iface.mainWindow())
        rapido.setToolTip("Elige el DEM, revisa lluvia, CN y filtros, y ejecuta")
        rapido.triggered.connect(lambda: self.ejecutar(ID_ALGORITMO_RAPIDO))
        self.iface.addToolBarIcon(rapido)
        self.iface.addPluginToMenu(MENU, rapido)
        self.acciones.append(rapido)

        completo = QAction(icono, "Análisis completo…", self.iface.mainWindow())
        completo.setToolTip("Todos los parámetros a la vista: lluvia, CN, eje de la vía, desborde del río")
        completo.triggered.connect(lambda: self.ejecutar(ID_ALGORITMO_COMPLETO))
        self.iface.addPluginToMenu(MENU, completo)
        self.acciones.append(completo)

        guia = QAction("Guía de uso (PDF)", self.iface.mainWindow())
        guia.triggered.connect(self.abrir_guia)
        self.iface.addPluginToMenu(MENU, guia)
        self.acciones.append(guia)

    def ejecutar(self, id_algoritmo):
        import processing
        processing.execAlgorithmDialog(id_algoritmo)

    def abrir_guia(self):
        local = os.path.join(os.path.dirname(__file__), "Guia_Cota_Anegamiento.pdf")
        if os.path.exists(local):
            QDesktopServices.openUrl(QUrl.fromLocalFile(local))
        else:
            QDesktopServices.openUrl(QUrl(URL_GUIA))

    def unload(self):
        for accion in self.acciones:
            self.iface.removeToolBarIcon(accion)
            self.iface.removePluginMenu(MENU, accion)
        self.acciones = []
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
