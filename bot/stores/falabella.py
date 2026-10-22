"""Parser compartido para la plataforma Falabella (Next.js SSR).

Verificado en vivo (octubre 2026):
  - falabella.com.pe  → las páginas de listado traen <script id="__NEXT_DATA__">
    con props.pageProps.results = productos y props.pageProps.pagination
    (currentPage/perPage/count). La paginación funciona con ?page=N.
    Precios en results[i].prices[] con tipos: cmrPrice (tarjeta),
    eventPrice / internetPrice (precio actual) y normalPrice con
    crossed=true (precio "antes").
    Imágenes en mediaUrls[0] (media.falabella.com.pe/falabellaPE/<sku>_01/public).
  - tottus.com.pe/tottus-pe/lista/CATG... → MISMO motor
    (__NEXT_DATA__ con pageProps.results; el propio JSON declara
    "businessUnit": "falabella"). Se reutiliza este parser sin cambios.

Nota: ignoramos cmrPrice (requiere tarjeta CMR) y usamos el precio público.
"""
from __future__ import annotations

import logging

from ..models import Producto
from .base import Tienda, a_float, extraer_next_data, url_con_pagina

log = logging.getLogger("bot.tiendas")

# Tipos de precio que representan el precio actual público
_TIPOS_ACTUAL = ("eventprice", "internetprice", "normalprice")


class TiendaPlataformaFalabella(Tienda):
    """Listados SSR de la plataforma Falabella (Falabella Perú y Tottus)."""

    #: Base del sitio, p. ej. https://www.falabella.com.pe
    base: str = ""

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
                resultados = page_props.get("results") or []
                if not resultados:
                    log.info("[%s] sin resultados en %s (fin)", self.nombre, url)
                    break

                for crudo in resultados:
                    producto = self._parsear(crudo, url_lista)
                    if producto:
                        productos.append(producto)

                log.info("[%s] %s pág.%d: %d productos",
                         self.nombre, url.split("/")[-1][:40], pagina, len(resultados))

                pag = page_props.get("pagination") or {}
                actual = int(pag.get("currentPage") or pagina)
                per_page = int(pag.get("perPage") or len(resultados))
                total = int(pag.get("count") or 0)
                if total and actual * per_page >= total:
                    break  # última página alcanzada

        return productos

    # ------------------------------------------------------------------
    def _parsear(self, crudo: dict, url_listado: str) -> Producto | None:
        precio_actual, precio_original = self._extraer_precios(crudo.get("prices"))
        if not precio_actual or precio_actual <= 0:
            return None

        imagenes = crudo.get("mediaUrls") or []
        imagen = imagenes[0] if imagenes else None

        # La categoría la tomamos de la URL del listado configurada
        categoria = self._categoria_desde_url(url_listado)

        relativa = crudo.get("url") or ""
        url = relativa if relativa.startswith("http") else f"{self.base}{relativa}"

        return Producto(
            tienda=self.nombre,
            id=str(crudo.get("skuId") or crudo.get("productId") or ""),
            nombre=(crudo.get("displayName") or "").strip(),
            marca=(crudo.get("brand") or "").strip(),
            precio_actual=precio_actual,
            precio_original=precio_original,
            url=url,
            imagen=imagen,
            categoria=categoria,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _extraer_precios(precios: list | None) -> tuple[float | None, float | None]:
        """Devuelve (precio_actual, precio_original) a partir de prices[].

        - actual  = el menor entre eventPrice/internetPrice/normalPrice público
        - original = normalPrice con crossed=true (tachado)
        """
        actual: float | None = None
        original: float | None = None
        for precio in precios or []:
            tipo = (precio.get("type") or "").lower()
            valor = a_float((precio.get("price") or [None])[0])
            if valor is None or valor <= 0:
                continue
            if tipo == "normalprice":
                if precio.get("crossed"):
                    original = valor
                else:
                    actual = valor if actual is None else min(actual, valor)
            elif tipo in _TIPOS_ACTUAL:
                actual = valor if actual is None else min(actual, valor)
            # cmrPrice (tarjeta) y otros tipos se ignoran a propósito

        if original is not None and actual is not None and original <= actual:
            original = None  # el "antes" no es mayor: no sirve para el cálculo
        return actual, original

    @staticmethod
    def _categoria_desde_url(url: str) -> str:
        # https://.../category/cat40712/Laptops → Laptops
        # https://.../lista/CATG47976/Televisores → Televisores
        partes = url.rstrip("/").split("/")
        return partes[-1] if partes else None
