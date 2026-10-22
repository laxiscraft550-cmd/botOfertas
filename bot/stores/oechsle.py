"""Oechsle (oechsle.pe) — plataforma VTEX.

Endpoint verificado en vivo:
    https://www.oechsle.pe/api/catalog_system/pub/products/search
    → HTTP 206 con JSON de productos, acepta O=OrderByBestDiscountDESC.
"""
from __future__ import annotations

from .vtex import TiendaVTEX


class Oechsle(TiendaVTEX):
    nombre = "oechsle"
    dominio = "www.oechsle.pe"
    ordenar_por_descuento = True
