"""Plaza Vea (plazavea.com.pe) — plataforma VTEX.

Endpoint verificado en vivo:
    https://www.plazavea.com.pe/api/catalog_system/pub/products/search
    → HTTP 206 con JSON de productos (items[0].sellers[0].commertialOffer).

Es una tienda mayormente de supermercado + marketplace; los descuentos del
70%+ reales son poco frecuentes, por eso el precio mínimo del filtro es clave.
"""
from __future__ import annotations

from .vtex import TiendaVTEX


class PlazaVea(TiendaVTEX):
    nombre = "plazavea"
    dominio = "www.plazavea.com.pe"
    ordenar_por_descuento = True
