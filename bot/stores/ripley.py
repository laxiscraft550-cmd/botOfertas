"""Ripley Perú (ripley.com.pe → simple.ripley.com.pe).

Investigación (octubre 2026):
- ripley.com.pe redirige a simple.ripley.com.pe, una plataforma Next.js
  con Cloudflare. Los listados renderizan en SSR:
      <script id="__NEXT_DATA__"> → props.pageProps.findabilityProps.data
      .products[]  con: sku, parentProductID, name, brand, primaryImage,
      priceNumber (actual), masterPriceNumber (antes), ripleyPriceNumber
      (precio Ripley, a veces menor), discount.
  Paginación por ?page=N (offset = (page-1)*limit), verificada.
- La URL del producto NO viene en products[], pero sí en
  data.structuredData["@graph"] → nodos @type=Product con "url"
  terminado en /<sku>: la mapeamos por SKU.
- orderBy=discount_desc NO existe (probado: no ordena), así que navegamos
  las primeras páginas de las categorías configuradas y calculamos nosotros
  el descuento real.
"""
from __future__ import annotations

import logging

from ..models import Producto
from .base import Tienda, a_float, extraer_next_data, url_con_pagina

log = logging.getLogger("bot.tiendas")


class Ripley(Tienda):
    nombre = "ripley"
    base = "https://simple.ripley.com.pe"

    # ------------------------------------------------------------------
    def buscar_productos(self) -> list[Producto]:
        productos: list[Producto] = []
        urls = self.urls_listado
        if not urls:
            log.warning("[%s] sin urls de listado en config", self.nombre)
            return productos

        for url_lista in urls:
            for pagina in range(1, self.max_paginas + 1):
                url = url_con_pagina(url_lista, pagina)
                respuesta = self.sesion.get(url)
                if respuesta.status_code != 200:
                    log.warning("[%s] HTTP %d en %s", self.nombre, respuesta.status_code, url)
                    break

                datos = extraer_next_data(respuesta.text)
                if datos is None:
                    log.warning("[%s] sin __NEXT_DATA__ en %s", self.nombre, url)
                    break

                page_props = (datos.get("props") or {}).get("pageProps") or {}
                find = page_props.get("findabilityProps") or {}
                data = find.get("data") or {}
                crudos = data.get("products") or []
                if not crudos:
                    log.info("[%s] sin productos en %s (fin)", self.nombre, url)
                    break

                mapa_urls = self._mapa_urls_producto(data.get("structuredData"))
                categoria = self._categoria_desde_url(url_lista)

                for crudo in crudos:
                    producto = self._parsear(crudo, mapa_urls, categoria)
                    if producto:
                        productos.append(producto)

                log.info("[%s] pág.%d: %d productos", self.nombre, pagina, len(crudos))

                limite = int(data.get("limit") or 48)
                desplazamiento = int(data.get("offset") or 0)
                total = int(data.get("total") or 0)
                if total and desplazamiento + limite >= total:
                    break  # última página alcanzada

        return productos

    # ------------------------------------------------------------------
    def _parsear(self, crudo: dict, mapa_urls: dict[str, str], categoria: str) -> Producto | None:
        precio_lista = a_float(crudo.get("masterPriceNumber"))
        precio_ripley = a_float(crudo.get("ripleyPriceNumber"))
        precio_publico = a_float(crudo.get("priceNumber"))

        candidatos = [p for p in (precio_publico, precio_ripley) if p and p > 0]
        if not candidatos:
            return None
        precio_actual = min(candidatos)          # el mejor precio vigente
        precio_original = (
            precio_lista if precio_lista and precio_lista > precio_actual else None
        )

        sku = str(crudo.get("sku") or crudo.get("parentProductID") or "").rstrip("Pp")
        url = mapa_urls.get(sku) or mapa_urls.get(str(crudo.get("sku") or "")) or ""

        return Producto(
            tienda=self.nombre,
            id=sku or str(crudo.get("code") or ""),
            nombre=(crudo.get("name") or "").strip(),
            marca=(crudo.get("brand") or "").strip(),
            precio_actual=precio_actual,
            precio_original=precio_original,
            url=url,
            imagen=crudo.get("primaryImage") or None,
            categoria=categoria,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _mapa_urls_producto(structured: dict | None) -> dict[str, str]:
        """sku → url del producto, desde structuredData['@graph']."""
        mapa: dict[str, str] = {}
        for nodo in (structured or {}).get("@graph") or []:
            if nodo.get("@type") == "Product" and nodo.get("url"):
                url = nodo["url"]
                sku = url.rstrip("/").rsplit("/", 1)[-1]
                mapa[sku] = url
                mapa[sku.upper()] = url
        return mapa

    @staticmethod
    def _categoria_desde_url(url: str) -> str:
        # https://simple.ripley.com.pe/tecnologia/computacion/laptops → laptops
        partes = [p for p in url.rstrip("/").split("/") if p]
        return partes[-1] if partes else None
