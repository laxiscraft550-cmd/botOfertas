"""Promart (promart.pe) — plataforma VTEX (home center: construcción,
ferretería, electrohogar, muebles). Es del Grupo Intercorp, igual que
Plaza Vea y Oechsle.

Endpoint verificado en vivo:
    https://www.promart.pe/api/catalog_system/pub/products/search
        ?O=OrderByBestDiscountDESC&_from=0&_to=49
    → HTTP 206 con JSON de productos (items[0].sellers[0].commertialOffer).
"""
from __future__ import annotations

from .vtex import TiendaVTEX


class Promart(TiendaVTEX):
    nombre = "promart"
    dominio = "www.promart.pe"
    ordenar_por_descuento = True
