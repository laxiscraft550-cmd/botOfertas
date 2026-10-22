"""Scraper base para tiendas sobre la plataforma VTEX.

Tiendas VTEX exponen el endpoint público de catálogo:
    GET https://<dominio>/api/catalog_system/pub/products/search?_from=0&_to=49

Verificado en vivo (octubre 2026):
    - plazavea.com.pe  → HTTP 206, funciona y acepta O=OrderByBestDiscountDESC
    - oechsle.pe       → HTTP 206, funciona
    - carsa.pe         → HTTP 206, funciona (la tienda usa VTEX, no WooCommerce)

El parámetro O=OrderByBestDiscountDESC ordena por mayor descuento, así con
1-2 páginas de 50 productos cubrimos las mejores ofertas sin saturar al sitio.
"""
from __future__ import annotations

import logging

from ..models import Producto
from .base import Tienda

log = logging.getLogger("bot.tiendas")

_TAM_PAGINA = 50  # máximo clásico de VTEX por request en search


class TiendaVTEX(Tienda):
    """Implementación común para tiendas VTEX."""

    #: Dominio público de la tienda
    dominio: str = ""
    #: Ordenar por mayor descuento (recomendado: surfaces las mejores ofertas)
    ordenar_por_descuento: bool = True

    # ------------------------------------------------------------------
    def buscar_productos(self) -> list[Producto]:
        productos: list[Producto] = []
        for pagina in range(self.max_paginas):
            desde = pagina * _TAM_PAGINA
            params = {"_from": desde, "_to": desde + _TAM_PAGINA - 1}
            if self.ordenar_por_descuento:
                params["O"] = "OrderByBestDiscountDESC"

            url = f"https://{self.dominio}/api/catalog_system/pub/products/search"
            respuesta = self.sesion.get(url, params=params)

            if respuesta.status_code in (204, 400, 404):
                # 204 = sin más resultados; 400/404 = rango _from/_to inválido
                break
            if respuesta.status_code not in (200, 206):
                raise RuntimeError(f"HTTP {respuesta.status_code} en {url}")

            try:
                datos = respuesta.json()
            except ValueError as exc:
                raise RuntimeError(f"Respuesta no-JSON de {self.dominio}") from exc

            if not datos:
                break

            for crudo in datos:
                producto = self._parsear(crudo)
                if producto:
                    productos.append(producto)

            log.info("[%s] página %d: %d productos", self.nombre, pagina + 1, len(datos))

        return productos

    # ------------------------------------------------------------------
    def _parsear(self, crudo: dict) -> Producto | None:
        items = crudo.get("items") or []
        if not items:
            return None

        # Elegir la variante con stock; si ninguna, la primera
        item = next(
            (i for i in items if self._con_stock(i)),
            items[0],
        )
        vendedores = item.get("sellers") or [{}]
        oferta = (vendedores[0].get("commertialOffer") or {})

        precio_actual = float(oferta.get("Price") or 0)
        if precio_actual <= 0:
            return None  # producto sin precio publicado (basura para nuestro filtro)

        precio_lista = float(oferta.get("ListPrice") or 0)
        precio_original = precio_lista if precio_lista > precio_actual else None

        imagenes = item.get("images") or []
        imagen = imagenes[0].get("imageUrl") if imagenes else None

        categorias = crudo.get("categories") or []
        categoria = categorias[0].strip("/") if categorias else None

        return Producto(
            tienda=self.nombre,
            id=str(crudo.get("productId") or item.get("itemId") or ""),
            nombre=(crudo.get("productName") or "").strip(),
            marca=(crudo.get("brand") or "").strip(),
            precio_actual=precio_actual,
            precio_original=precio_original,
            url=crudo.get("link") or "",
            imagen=imagen,
            categoria=categoria,
        )

    @staticmethod
    def _con_stock(item: dict) -> bool:
        vendedores = item.get("sellers") or [{}]
        oferta = (vendedores[0].get("commertialOffer") or {})
        return int(oferta.get("AvailableQuantity") or 0) > 0
