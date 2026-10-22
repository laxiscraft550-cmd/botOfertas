"""Estado persistente: productos notificados + historial de precios.

Se guarda en un JSON (data/estado.json) con escritura atómica para poder
hacer commit del archivo en GitHub Actions entre ejecuciones.

- notificados: clave → {precio, ts}. Solo se vuelve a avisar si el precio
  BAJA respecto de la última notificación.
- historial:   clave → [{ts, precio}, ...]. Sirve para detectar
  "descuentos falsos" (precio original inflado o descuento permanente).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Producto

log = logging.getLogger("bot.estado")


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Estado:
    def __init__(
        self,
        ruta: str = "data/estado.json",
        historial_max_por_producto: int = 30,
        historial_max_productos: int = 5000,
        dias_retencion_notificados: int = 90,
    ) -> None:
        self.ruta = Path(ruta)
        self.max_hist = int(historial_max_por_producto)
        self.max_productos = int(historial_max_productos)
        self.retencion = timedelta(days=int(dias_retencion_notificados))
        self.datos: dict = {"notificados": {}, "historial": {}}
        self._cargar()

    # ------------------------------------------------------------------
    # Carga / guardado
    # ------------------------------------------------------------------
    def _cargar(self) -> None:
        if not self.ruta.exists():
            log.info("Estado nuevo: %s no existe todavía", self.ruta)
            return
        try:
            crudo = json.loads(self.ruta.read_text(encoding="utf-8"))
            if isinstance(crudo, dict):
                self.datos["notificados"] = crudo.get("notificados") or {}
                self.datos["historial"] = crudo.get("historial") or {}
            log.info(
                "Estado cargado: %d notificados, %d con historial",
                len(self.datos["notificados"]), len(self.datos["historial"]),
            )
        except (json.JSONDecodeError, OSError) as exc:
            # Estado corrupto: no fatal. Se preserva una copia y se empieza de cero.
            respaldo = self.ruta.with_suffix(".corrupto.json")
            try:
                os.replace(self.ruta, respaldo)
                log.error("Estado corrupto (%s). Copia guardada en %s", exc, respaldo)
            except OSError:
                log.error("Estado corrupto (%s) y no se pudo respaldar", exc)

    def guardar(self) -> None:
        """Escritura atómica: tempfile + os.replace (nunca un JSON a medias)."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = json.dumps(self.datos, ensure_ascii=False, indent=1, sort_keys=True)
        descriptor, ruta_tmp = tempfile.mkstemp(
            dir=self.ruta.parent, prefix=".estado_", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
                archivo.write(contenido)
            os.replace(ruta_tmp, self.ruta)
        except BaseException:
            if os.path.exists(ruta_tmp):
                os.unlink(ruta_tmp)
            raise
        log.info("Estado guardado en %s", self.ruta)

    # ------------------------------------------------------------------
    # Historial de precios
    # ------------------------------------------------------------------
    def observar(self, clave: str, precio: float) -> None:
        """Registra una observación de precio (para todo producto visto)."""
        historial = self.datos["historial"]
        entradas = historial.get(clave) or []
        entradas.append({"ts": _ahora_iso(), "precio": round(float(precio), 2)})
        if len(entradas) > self.max_hist:
            entradas = entradas[-self.max_hist:]
        historial[clave] = entradas
        self._podar_historial()

    def _podar_historial(self) -> None:
        historial = self.datos["historial"]
        if len(historial) <= self.max_productos:
            return
        # Podar los menos recientemente observados (lista = orden de inserción)
        excedente = len(historial) - self.max_productos
        claves = list(historial.keys())
        for clave in claves[:excedente]:
            del historial[clave]

    # ------------------------------------------------------------------
    # Deduplicación de notificaciones
    # ------------------------------------------------------------------
    def debe_notificar(self, clave: str, precio_actual: float) -> tuple[bool, str]:
        """¿Corresponde avisar? Solo si es nuevo o si el precio BAJÓ."""
        registro = self.datos["notificados"].get(clave)
        if not registro:
            return True, "nueva oferta"
        precio_previo = float(registro.get("precio") or 0)
        if precio_previo > 0 and precio_actual < precio_previo * 0.995:
            return True, f"bajó de S/{precio_previo:.2f}"
        return False, "ya notificada sin cambio de precio"

    def marcar_notificado(self, clave: str, precio: float) -> None:
        self.datos["notificados"][clave] = {
            "precio": round(float(precio), 2),
            "ts": _ahora_iso(),
        }
        self._podar_notificados()

    def _podar_notificados(self) -> None:
        limite = datetime.now(timezone.utc) - self.retencion
        notificados = self.datos["notificados"]
        for clave in list(notificados):
            try:
                ts = datetime.strptime(notificados[clave]["ts"], "%Y-%m-%dT%H:%M:%SZ")
                ts = ts.replace(tzinfo=timezone.utc)
                if ts < limite:
                    del notificados[clave]
            except (KeyError, ValueError):
                del notificados[clave]

    # ------------------------------------------------------------------
    # Detección de descuentos falsos
    # ------------------------------------------------------------------
    def precio_permanente(self, clave: str, precio_actual: float, minimo_obs: int = 2) -> bool:
        """Anti-inflado #3: ¿el precio actual no cambió en observaciones
        previas? (el «descuento» es permanente, no es una oferta real).

        Se miran solo las observaciones ANTES de la de esta corrida.
        minimo_obs=2 → se descarta a partir de la 3ª corrida consecutiva
        con el mismo precio.
        """
        entradas = self.datos["historial"].get(clave) or []
        precios = [e.get("precio") for e in entradas if e.get("precio")]
        previos = precios[:-1]  # sin la observación de esta corrida
        if len(previos) < minimo_obs:
            return False
        return all(abs(p - precio_actual) < 0.01 for p in previos[-minimo_obs:])

    def advertencias(self, producto: Producto) -> list[str]:
        """Compara el 'precio original' y el precio actual con el historial."""
        avisos: list[str] = []
        entradas = self.datos["historial"].get(producto.clave) or []
        precios = [e.get("precio") for e in entradas if e.get("precio")]

        if len(precios) >= 3:
            max_historico = max(precios)

            # 1) El "precio original" es mayor a cualquier precio que
            #    hayamos visto: probablemente esté inflado.
            if (
                producto.precio_original
                and producto.precio_original > max_historico * 1.10
            ):
                avisos.append(
                    "⚠️ El «precio original» supera lo que se ha visto en el "
                    "historial: podría estar inflado"
                )

            # 2) El precio actual no cambió en observaciones previas:
            #    el «descuento» es permanente (falso descuento).
            vistos_antes = precios[:-1]
            if vistos_antes and all(
                abs(p - producto.precio_actual) < 0.01 for p in vistos_antes[-3:]
            ):
                avisos.append(
                    "⚠️ El precio no ha cambiado en observaciones anteriores: "
                    "el descuento parece permanente"
                )

        return avisos
