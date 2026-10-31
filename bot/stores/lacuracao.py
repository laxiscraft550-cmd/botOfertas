"""La Curacao Perú (lacuracao.pe) — Magento 2.

Verificado en vivo (octubre 2026):
  - Los listados (/tecnologia/televisores.html, ...) se renderizan en el
    servidor con el HTML clásico de Magento 2: ~24 productos por página.
  - Por producto aparece <div class="product details product-item-details">
    con <a class="product-item-link" href=...>nombre</a>, precios en
    data-price-amount / data-price-type="finalPrice"|"oldPrice" y marca en
    <span class="brand-name">.
  - La imagen vive ANTES del bloque de detalles, en
    <img class="product-image-photo" src="...">.
  - Paginación estándar de Magento: ?p=N.
"""
from __future__ import annotations

import html as _html
import logging
import re

from ..models import Producto
from .base import Tienda, a_float, url_con_pagina

log = logging.getLogger("bot.tiendas")

_DETALLES = re.compile(
    r'<div class="product details product-item-details">'
)
_ENLACE = re.compile(
    r'<a class="product-item-link"\s+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_FINAL = re.compile(r'data-price-amount="([\d.]+)"\s+data-price-type="finalPrice"')
_VIEJO = re.compile(r'data-price-amount="([\d.]+)"\s+data-price-type="oldPrice"')
_MARCA = re.compile(r'class="brand-name">([^<]+)<')
_PRODUCTO_ID = re.compile(r'data-product-id="(\d+)"')
_IMAGEN = re.compile(
    r'<img[^>]*class="[^"]*product-image-photo[^"]*"\s+src="([^"]+)"'
)
_ETIQUETAS = re.compile(r"<[^>]+>")


def _limpiar(texto: str) -> str:
    return _html.unescape(_ETIQUETAS.sub(" ", texto or "")).strip()


class LaCuracao(Tienda):
    nombre = "lacuracao"

    def buscar_productos(self) -> list[Producto]:
        productos: list[Producto] = []
        urls = self.urls_listado
        if not urls:
            log.warning("[%s] sin urls de listado en config", self.nombre)
            return productos

        for url_lista in urls:
            for pagina in range(1, self.max_paginas + 1):
                url = url_con_pagina(url_lista, pagina, param="p")
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
    def _parsear_pagina(self, pagina_html: str, url_lista: str, pagina: int,
                        acumulado: list[Producto]) -> int:
        cortes = [m.start() for m in _DETALLES.finditer(pagina_html)]
        if not cortes:
            log.info("[%s] sin productos en %s", self.nombre, url_lista)
            return 0

        # Imágenes de producto con su posición; la del producto i-ésimo es la
        # última anterior a su bloque de detalles.
        imagenes = [(m.start(), _html.unescape(m.group(1)).split("?")[0])
                    for m in _IMAGEN.finditer(pagina_html)]

        for i, inicio in enumerate(cortes):
            fin = cortes[i + 1] if i + 1 < len(cortes) else inicio + 4000
            bloque = pagina_html[inicio:fin]

            enlace = _ENLACE.search(bloque)
            if not enlace:
                continue
            url_cruda = _html.unescape(enlace.group(1)).split("?")[0]
            nombre = _limpiar(enlace.group(2))
            if not nombre or not url_cruda:
                continue

            final_m = _FINAL.search(bloque)
            actual = a_float(final_m.group(1)) if final_m else None
            viejo_m = _VIEJO.search(bloque)
            original = a_float(viejo_m.group(1)) if viejo_m else None
            if not actual or actual <= 0:
                continue
            if original is not None and original <= actual:
                original = None  # el "antes" no supera al actual: inútil

            marca_m = _MARCA.search(bloque)
            id_m = _PRODUCTO_ID.search(bloque)

            imagen = None
            for pos, src in reversed(imagenes):
                if pos < inicio:
                    imagen = src
                    break

            acumulado.append(Producto(
                tienda=self.nombre,
                id=(id_m.group(1) if id_m else url_cruda.rsplit("/", 1)[-1][:60]),
                nombre=nombre,
                marca=marca_m.group(1).strip() if marca_m else "",
                precio_actual=actual,
                precio_original=original,
                url=url_cruda,
                imagen=imagen,
                categoria=self._categoria_desde_url(url_lista),
            ))

        log.info("[%s] %s pág.%d: %d productos",
                 self.nombre, url_lista.rstrip("/").rsplit("/", 1)[-1][:40],
                 pagina, len(cortes))
        return len(cortes)

    @staticmethod
    def _categoria_desde_url(url: str) -> str:
        # https://www.lacuracao.pe/tecnologia/televisores.html → televisores
        nombre = url.rstrip("/").rsplit("/", 1)[-1]
        return nombre.replace(".html", "").replace("-", " ").title()
