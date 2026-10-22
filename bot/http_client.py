"""Cliente HTTP con buenas prácticas de scraping responsable.

- User-Agent realista de un navegador común.
- Pausa aleatoria entre peticiones (por tienda).
- Reintentos con backoff exponencial + jitter ante 429/5xx y errores de red.
- Timeouts siempre definidos.
"""
from __future__ import annotations

import logging
import random
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("bot.http")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Códigos que vale la pena reintentar
_STATUS_REINTENTO = (429, 500, 502, 503, 504)


class ErrorTienda(RuntimeError):
    """Error irrecuperable de una tienda (no detiene al bot)."""


class SesionWeb:
    """Sesión HTTP por tienda: pausas, reintentos y timeouts."""

    def __init__(
        self,
        pausa_min_seg: float = 1.0,
        pausa_max_seg: float = 2.5,
        timeout_seg: float = 25,
        reintentos: int = 3,
        nombre: str = "",
    ) -> None:
        self.pausa_min = float(pausa_min_seg)
        self.pausa_max = float(pausa_max_seg)
        self.timeout = float(timeout_seg)
        self.reintentos = max(1, int(reintentos))
        self.nombre = nombre or "http"
        self._ultima_peticion = 0.0

        sesion = requests.Session()
        sesion.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
            }
        )
        # Capa de reintentos a nivel de adaptador (para códigos de estado)
        reintento = Retry(
            total=self.reintentos - 1,
            backoff_factor=1.2,
            status_forcelist=_STATUS_REINTENTO,
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adaptador = HTTPAdapter(max_retries=reintento)
        sesion.mount("https://", adaptador)
        sesion.mount("http://", adaptador)
        self._sesion = sesion

    # ------------------------------------------------------------------
    def get(self, url: str, params: dict | None = None) -> requests.Response:
        """GET con pausa aleatoria y reintentos propios ante fallos transitorios."""
        self._respetar_pausa()
        ultimo_error: Exception | None = None
        for intento in range(self.reintentos):
            try:
                respuesta = self._sesion.get(url, params=params, timeout=self.timeout)
                if respuesta.status_code in _STATUS_REINTENTO:
                    raise requests.HTTPError(f"HTTP {respuesta.status_code}")
                return respuesta
            except requests.RequestException as exc:
                ultimo_error = exc
                if intento == self.reintentos - 1:
                    break
                espera = (2**intento) + random.uniform(0, 1)
                log.warning(
                    "[%s] %s falló (%s). Reintento %d/%d en %.1fs",
                    self.nombre, url[:90], exc.__class__.__name__,
                    intento + 1, self.reintentos - 1, espera,
                )
                time.sleep(espera)
        raise ErrorTienda(f"{url[:90]}: {ultimo_error}") from ultimo_error

    # ------------------------------------------------------------------
    def _respetar_pausa(self) -> None:
        espera = random.uniform(self.pausa_min, self.pausa_max)
        transcurrido = time.time() - self._ultima_peticion
        if self._ultima_peticion and transcurrido < espera:
            time.sleep(espera - transcurrido)
        self._ultima_peticion = time.time()
