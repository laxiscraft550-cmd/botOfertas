"""Envío de notificaciones por Telegram usando la Bot API oficial (https).

No dependemos de librerías pesadas: solo requests contra
https://api.telegram.org/bot<token>/<metodo>. El token y el chat_id
NUNCA van en el código: se leen de variables de entorno.
"""
from __future__ import annotations

import html
import json
import logging
import time

import requests

from .filters import nivel_descuento
from .models import Producto

log = logging.getLogger("bot.telegram")

API_BASE = "https://api.telegram.org"


def _esc(texto: str) -> str:
    return html.escape(str(texto or ""))


def _monto(valor: float) -> str:
    return f"S/ {valor:,.2f}"


class Notificador:
    def __init__(self, token: str, chat_id: str, reintentos: int = 3) -> None:
        self.api = f"{API_BASE}/bot{token}"
        self.chat_id = chat_id
        self.reintentos = max(1, int(reintentos))
        self._sesion = requests.Session()
        self._sesion.headers.update({"User-Agent": "ofertas-peru-bot/1.0"})

    # ------------------------------------------------------------------
    def _llamar(self, metodo: str, payload: dict) -> dict:
        """POST a la Bot API con reintentos y errores claros."""
        url = f"{self.api}/{metodo}"
        ultimo_error: Exception | None = None
        for intento in range(self.reintentos):
            try:
                respuesta = self._sesion.post(url, data=payload, timeout=30)
                datos = respuesta.json()
                if datos.get("ok"):
                    return datos
                descripcion = datos.get("description", "")
                # Errores permanentes (400): no reintentar…
                if respuesta.status_code == 400:
                    # …salvo URL de botón inválida: se reintenta SIN botón
                    # (un producto con URL rara no debe perderse ni tumbar la corrida)
                    if "BUTTON_URL_INVALID" in descripcion and "reply_markup" in payload:
                        log.warning("Telegram rechazó la URL del botón; reintento sin botón")
                        payload = {k: v for k, v in payload.items() if k != "reply_markup"}
                        continue
                    raise requests.HTTPError(f"Telegram 400: {descripcion}")
                raise requests.HTTPError(f"Telegram: {descripcion or datos}")
            except (requests.RequestException, ValueError) as exc:
                ultimo_error = exc
                if isinstance(exc, requests.HTTPError) and "400" in str(exc):
                    break
                if intento == self.reintentos - 1:
                    break
                espera = (2**intento) + 0.5
                log.warning("Telegram %s falló (%s), reintento en %.1fs", metodo, exc, espera)
                time.sleep(espera)
        raise RuntimeError(f"Telegram {metodo} falló: {ultimo_error}") from ultimo_error

    # ------------------------------------------------------------------
    def enviar_texto(self, texto: str) -> None:
        self._llamar(
            "sendMessage",
            {"chat_id": self.chat_id, "text": texto, "disable_web_page_preview": "true"},
        )

    def enviar_producto(self, producto: Producto) -> bool:
        """Envía foto + caption + botón. Devuelve False si hubo fallo."""
        emoji, etiqueta = nivel_descuento(producto.descuento_pct)
        lineas = [
            f"{emoji} <b>Descuento {etiqueta}</b> — <b>{producto.descuento_pct:.0f}%</b>",
            f"🛍️ <b>{_esc(producto.nombre[:180])}</b>",
            f"🏪 {_esc(producto.tienda.title())}"
            + (f" · {_esc(producto.marca)}" if producto.marca else ""),
        ]
        if producto.precio_original:
            ahorro = producto.precio_original - producto.precio_actual
            lineas.append(
                f"💰 Antes: <s>{_monto(producto.precio_original)}</s>  →  "
                f"Ahora: <b>{_monto(producto.precio_actual)}</b>  "
                f"(ahorras <b>{_monto(ahorro)}</b>)"
            )
        else:
            lineas.append(f"💰 Ahora: <b>{_monto(producto.precio_actual)}</b>")
        if producto.categoria:
            lineas.append(f"📂 {_esc(producto.categoria)}")
        for advertencia in producto.advertencias:
            lineas.append(f"{_esc(advertencia)}")

        caption = "\n".join(lineas)[:1024]  # límite de Telegram para captions

        teclado = None
        if producto.url and producto.url.startswith(("http://", "https://")):
            teclado = json.dumps(
                {"inline_keyboard": [[{"text": "🛍️ Ver oferta", "url": producto.url}]]}
            )

        # 1) Intento con foto
        if producto.imagen:
            try:
                self._llamar(
                    "sendPhoto",
                    {
                        "chat_id": self.chat_id,
                        "photo": producto.imagen,
                        "caption": caption,
                        "parse_mode": "HTML",
                        **({"reply_markup": teclado} if teclado else {}),
                    },
                )
                return True
            except RuntimeError as exc:
                log.warning("sendPhoto falló (%s); reintento como texto", exc)

        # 2) Fallback: solo texto
        try:
            self._llamar(
                "sendMessage",
                {
                    "chat_id": self.chat_id,
                    "text": f"{caption}\n🔗 {_esc(producto.url)}",
                    "parse_mode": "HTML",
                    **({"reply_markup": teclado} if teclado else {}),
                },
            )
            return True
        except RuntimeError as exc:
            log.error("No se pudo enviar %s: %s", producto.clave, exc)
            return False
