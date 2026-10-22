"""Falabella Perú (falabella.com.pe).

Plataforma Next.js SSR con __NEXT_DATA__ en cada listado.
Ver bot/stores/falabella.py para los detalles de la API encontrada.
"""
from __future__ import annotations

from .falabella import TiendaPlataformaFalabella


class FalabellaPe(TiendaPlataformaFalabella):
    nombre = "falabella"
    base = "https://www.falabella.com.pe"
