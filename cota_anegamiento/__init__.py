# -*- coding: utf-8 -*-


def classFactory(iface):
    from .plugin import CotaAnegamientoPlugin
    return CotaAnegamientoPlugin(iface)
