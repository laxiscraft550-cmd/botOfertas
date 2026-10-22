"""Tottus (tottus.com.pe).

Investigación: pese a ser una plataforma "distinta", el sitio redirige a
/tottus-pe y su __NEXT_DATA__ declara businessUnit="falabella" y
tenant="pe": usa el MISMO motor Next.js que Falabella Perú con rutas
/tottus-pe/lista/CATG<id>/<slug>?page=N. Se reutiliza el parser de
bot/stores/falabella.py tal cual (verificado en vivo: pageProps.results
con prices cmr/internet/normal).
"""
from __future__ import annotations

from .falabella import TiendaPlataformaFalabella


class Tottus(TiendaPlataformaFalabella):
    nombre = "tottus"
    base = "https://www.tottus.com.pe"
