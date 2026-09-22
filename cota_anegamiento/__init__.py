# -*- coding: utf-8 -*-
# Complemento QGIS «Cota de Anegamiento»
# Copyright (C) 2026 Jose Ospina
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See the LICENSE file for details.


def classFactory(iface):
    from .plugin import CotaAnegamientoPlugin
    return CotaAnegamientoPlugin(iface)
