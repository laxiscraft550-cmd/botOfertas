"""Interfaz común de todas las tiendas."""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod

from ..http_client import SesionWeb
from ..models import Producto

log = logging.getLogger("bot.tiendas")

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


class Tienda(ABC):
    """Clase base: toda tienda recibe su config y una SesionWeb propia."""

    #: Identificador corto usado en logs, estado y mensajes ("plazavea", ...)
    nombre: str = ""

    def __init__(self, cfg: dict, sesion: SesionWeb) -> None:
        self.cfg = cfg or {}
        self.sesion = sesion

    @abstractmethod
    def buscar_productos(self) -> list[Producto]:
        """Devuelve la lista de productos del listado vigente."""

    # ------------------------------------------------------------------
    # Utilidades compartidas
    # ------------------------------------------------------------------
    @property
    def max_paginas(self) -> int:
        return max(1, int(self.cfg.get("max_paginas", 2)))

    @property
    def urls_listado(self) -> list[str]:
        urls = self.cfg.get("urls") or []
        return [u for u in urls if isinstance(u, str) and u.startswith("http")]


def url_con_pagina(base: str, pagina: int, param: str = "page") -> str:
    """Agrega <param>=N a una URL de listado respetando query string existente."""
    separador = "&" if "?" in base else "?"
    return f"{base}{separador}{param}={pagina}"


def extraer_next_data(html: str) -> dict | None:
    """Extrae el JSON __NEXT_DATA__ (Next.js SSR) de un HTML."""
    coincidencia = _NEXT_DATA.search(html)
    if not coincidencia:
        return None
    try:
        return json.loads(coincidencia.group(1))
    except (json.JSONDecodeError, ValueError) as exc:
        log.debug("__NEXT_DATA__ ilegible: %s", exc)
        return None


def a_float(valor) -> float | None:
    """Convierte 'S/ 3,599.00', 3599, '3599' → 3599.0 (None si no se puede)."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return None
    texto = texto.replace("S/", "").replace("S/ ", "").strip()
    texto = texto.replace(",", "")
    try:
        return float(texto)
    except ValueError:
        return None
