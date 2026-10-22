"""Carsa (carsa.pe) — plataforma VTEX (¡no WordPress!).

Investigación: carsa.pe carga assets de "carsaperupoc.vtexassets.com", así que
usamos el mismo endpoint público VTEX. Verificado en vivo:
    https://www.carsa.pe/api/catalog_system/pub/products/search
    → HTTP 206 con JSON de productos.

AVISO: Carsa publica ListPrices claramente inflados en algunos productos
(p. ej. audífonos de S/29 "antes S/5,619"), por eso el módulo de historial
marca esos casos con la advertencia de posible descuento falso.
"""
from __future__ import annotations

from .vtex import TiendaVTEX


class Carsa(TiendaVTEX):
    nombre = "carsa"
    dominio = "www.carsa.pe"
    ordenar_por_descuento = True
