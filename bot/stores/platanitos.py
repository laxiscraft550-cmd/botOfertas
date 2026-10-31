"""Platanitos (platanitos.com/pe) — plataforma propia (tipo Magento).

Verificado en vivo (octubre 2026):
  - Los listados de categoría (/pe/productos/categoria/mujeres/ropa, ...)
    se renderizan en el servidor con tarjetas <div class="nd-ct__item">
    (48 productos por página).
  - Por tarjeta: data-product_url, data-gtm_item_id/_name/_price/_brand/
    _category, precios en .price-current / .price-old ("S/ 19.90") y badge
    de descuento en .nd-ct__label-porc ("-33%").
  - Paginación por OFFSET: ?sort=_score&start=N (N = (página-1)*48).
"""
from __future__ import annotations

import html as _html
import logging
import re

from ..models import Producto
from .base import Tienda, a_float

log = logging.getLogger("bot.tiendas")

_BASE = "https://platanitos.com"
_TARJETA = re.compile(r'<div class="nd-ct__item">')
_URL = re.compile(r'data-product_url="([^"]+)"')
_ID = re.compile(r'data-gtm_item_id="([^"]*)"')
_NOMBRE = re.compile(r'data-gtm_item_name="([^"]*)"')
_MARCA = re.compile(r'data-gtm_item_brand="([^"]*)"')
_CATEGORIA = re.compile(r'data-gtm_item_category="([^"]*)"')
_ACTUAL = re.compile(r'class="price-current[^"]*"[^>]*>\s*S/\s*([\d.,]+)')
_VIEJO = re.compile(r'class="price-old[^"]*"[^>]*>\s*S/\s*([\d.,]+)')
_IMAGEN = re.compile(r'<img[^>]*\ssrc="([^"]+)"')
_POR_PAGINA = 48


class Platanitos(Tienda):
    nombre = "platanitos"

    def buscar_productos(self) -> list[Producto]:
        productos: list[Producto] = []
        urls = self.urls_listado
        if not urls:
            log.warning("[%s] sin urls de listado en config", self.nombre)
            return productos

        for url_lista in urls:
            for pagina in range(1, self.max_paginas + 1):
                url = self._url_pagina(url_lista, pagina)
                respuesta = self.sesion.get(url)
                if respuesta.status_code != 200:
                    log.warning("[%s] HTTP %d en %s",
                                self.nombre, respuesta.status_code, url)
                    break
                n = self._parsear_pagina(respuesta.text, url_lista, pagina,
                                         productos)
                if n == 0:
                    break  # fin de listado

        return productos

    # ------------------------------------------------------------------
    @staticmethod
    def _url_pagina(base: str, pagina: int) -> str:
        """Paginación por offset con su patrón ?sort=_score&start=N."""
        sin_query = base.split("?")[0]
        offset = (pagina - 1) * _POR_PAGINA
        return f"{sin_query}?sort=_score&start={offset}"

    def _parsear_pagina(self, pagina_html: str, url_lista: str, pagina: int,
                        acumulado: list[Producto]) -> int:
        fragmentos = _TARJETA.split(pagina_html)
        if len(fragmentos) <= 1:
            log.info("[%s] sin productos en %s", self.nombre, url_lista)
            return 0

        for fragmento in fragmentos[1:]:  # el [0] es el encabezado de página
            url_m = _URL.search(fragmento)
            nombre_m = _NOMBRE.search(fragmento)
            actual_m = _ACTUAL.search(fragmento)
            if not (url_m and nombre_m and actual_m):
                continue

            actual = a_float(actual_m.group(1))
            if not actual or actual <= 0:
                continue
            viejo_m = _VIEJO.search(fragmento)
            original = a_float(viejo_m.group(1)) if viejo_m else None
            if original is not None and original <= actual:
                original = None

            relativa = _html.unescape(url_m.group(1))
            url = relativa if relativa.startswith("http") else f"{_BASE}/{relativa.lstrip('/')}"

            marca_m = _MARCA.search(fragmento)
            cat_m = _CATEGORIA.search(fragmento)
            imagen_m = _IMAGEN.search(fragmento)
            id_m = _ID.search(fragmento)

            acumulado.append(Producto(
                tienda=self.nombre,
                id=(id_m.group(1) if id_m and id_m.group(1)
                    else url.rsplit("/", 1)[-1][:60]),
                nombre=_html.unescape(nombre_m.group(1)).strip(),
                marca=_html.unescape(marca_m.group(1)).strip() if marca_m else "",
                precio_actual=actual,
                precio_original=original,
                url=url,
                imagen=imagen_m.group(1) if imagen_m else None,
                categoria=_html.unescape(cat_m.group(1))
                .replace("&gt;", ">").strip() if cat_m else None,
            ))

        n = len(fragmentos) - 1
        log.info("[%s] %s pág.%d: %d productos",
                 self.nombre, url_lista.rstrip("/").rsplit("/", 1)[-1][:40],
                 pagina, n)
        return n
