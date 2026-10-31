"""Orquestador principal del bot.

Flujo:
  1. Carga config (config.yaml + defaults).
  2. Recolecta productos de cada tienda activa (un fallo no detiene a las demás).
  3. Calcula el descuento real, aplica filtros y registra historial.
  4. Deduplica contra el estado (solo avisa si es nuevo o bajó de precio).
  5. Ordena por mayor descuento, limita el número de mensajes y envía por
     Telegram (o imprime en consola con --dry-run).

Uso:
    python -m bot                  # corrida real (requiere env TELEGRAM_*)
    python -m bot --dry-run        # solo imprime, no envía ni marca notificados
    python -m bot --tiendas falabella,ripley --max-mensajes 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from .config import cargar_config
from .filters import (
    ahorro_soles,
    aplicar_descuento,
    cumple_filtros,
    filtrar_originales_repetidos,
    nivel_descuento,
    normalizar_nombre,
    precio_original_inflado,
    rango_clave,
)
from .http_client import SesionWeb
from .models import Producto
from .notifier import Notificador
from .state import Estado
from .stores import REGISTRO

log = logging.getLogger("bot")


def _parsear_cli(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bot", description="Vigila ofertas con descuentos grandes en tiendas peruanas"
    )
    parser.add_argument("--config", default="config.yaml", help="Ruta al config.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="No envía a Telegram; imprime las ofertas en consola")
    parser.add_argument("--tiendas", help="Lista separada por comas (p. ej. plazavea,falabella)")
    parser.add_argument("--max-mensajes", type=int, help="Cubre notificaciones.max_por_corrida")
    parser.add_argument("--verbose", action="store_true", help="Logging en nivel DEBUG")
    return parser.parse_args(argv)


def _recolectar(cfg: dict, solo_tiendas: set[str] | None) -> tuple[list[Producto], dict]:
    """Recolecta de todas las tiendas activas. Devuelve (ofertas, estadísticas)."""
    estado: Estado = cfg["_estado"]
    ofertas: list[Producto] = []
    stats: dict[str, dict] = {}

    for nombre, clase in REGISTRO.items():
        cfg_tienda = cfg["tiendas"].get(nombre)
        if cfg_tienda is None or not cfg_tienda.get("activa", True):
            log.info("[%s] desactivada; se omite", nombre)
            continue
        if solo_tiendas and nombre not in solo_tiendas:
            continue

        http = cfg["http"]
        sesion = SesionWeb(
            pausa_min_seg=http["pausa_min_seg"],
            pausa_max_seg=http["pausa_max_seg"],
            timeout_seg=http["timeout_seg"],
            reintentos=http["reintentos"],
            nombre=nombre,
        )
        log.info("[%s] revisando…", nombre)
        inicio = time.time()
        try:
            productos = clase(cfg_tienda, sesion).buscar_productos()
        except Exception as exc:  # una tienda caída NO detiene al bot
            log.error("[%s] ✖ falló la recolección: %s", nombre, exc, exc_info=True)
            stats[nombre] = {"error": str(exc)}
            continue

        vistos = nuevas = descartados = 0
        candidatas: list[Producto] = []
        for producto in productos:
            estado.observar(producto.clave, producto.precio_actual)
            # Backfill: notificaciones viejas no tienen nombre_norm; al ver el
            # producto se completa, para que el anti-repetición entre tiendas
            # cubra también lo avisado antes de existir esa función.
            estado.recordar_nombre(
                producto.clave, normalizar_nombre(producto.nombre)
            )
            aplicar_descuento(producto)
            vistos += 1

            ok, motivo = cumple_filtros(producto, cfg["filtros"])
            if not ok:
                descartados += 1
                log.debug("[%s] descartado %s: %s", nombre, producto.id, motivo)
                continue

            # Anti-inflado #3: el precio no cambió en observaciones previas
            if cfg["filtros"].get("descartar_descuentos_permanentes", True) and \
                    estado.precio_permanente(producto.clave, producto.precio_actual):
                descartados += 1
                log.debug("[%s] descartado %s: descuento permanente (precio sin cambios)",
                          nombre, producto.id)
                continue

            producto.advertencias = estado.advertencias(producto)

            # Anti-repetición #1: el MISMO producto (nombre normalizado) ya
            # avisado en CUALQUIER tienda o variante con otro id no se repite,
            # salvo que haya bajado del mínimo ya avisado (récord histórico).
            if cfg["filtros"].get("evitar_repetir_productos", True):
                visto = estado.ya_avisado_nombre(normalizar_nombre(producto.nombre))
                if visto and producto.precio_actual >= visto[1] * 0.995:
                    descartados += 1
                    log.debug("[%s] repetido %s: ya avisado en %s",
                              nombre, producto.id, visto[2])
                    continue

            avisar, razon = estado.debe_notificar(producto.clave, producto.precio_actual)
            if not avisar:
                descartados += 1
                log.debug("[%s] sin aviso %s: %s", nombre, producto.id, razon)
                continue

            candidatas.append(producto)

        # Anti-inflado #2: mismo «precio original» repetido en varios productos
        inflados = filtrar_originales_repetidos(
            candidatas, int(cfg["filtros"].get("precios_originales_repetidos") or 0)
        )
        claves_infladas = {p.clave for p in inflados}
        razon_max = float(cfg["filtros"].get("razon_original_maxima") or 0)
        for producto in candidatas:
            if producto.clave in claves_infladas:
                descartados += 1
                log.debug("[%s] descartado %s: precio original repetido/inflado",
                          nombre, producto.id)
                continue
            # Anti-inflado #1: razón precio original/precio actual absurda
            if precio_original_inflado(producto, razon_max):
                descartados += 1
                log.debug("[%s] descartado %s: precio original %.0fx el actual (inflado)",
                          nombre, producto.id,
                          producto.precio_original / producto.precio_actual)
                continue
            ofertas.append(producto)
            nuevas += 1

        stats[nombre] = {
            "vistos": vistos, "nuevas": nuevas, "descartados": descartados,
            "segundos": round(time.time() - inicio, 1),
        }
        log.info("[%s] ✓ %d productos vistos → %d ofertas nuevas (%.1fs)",
                 nombre, vistos, nuevas, stats[nombre]["segundos"])

    return ofertas, stats


def _imprimir_dry_run(ofertas: list[Producto], stats: dict,
                      elegidas: list[Producto], rangos: list[int]) -> None:
    print("\n" + "=" * 78)
    print("🔎 MODO DE PRUEBA (--dry-run): no se envió nada a Telegram")
    print("=" * 78)
    for nombre, dato in stats.items():
        if "error" in dato:
            print(f"  ✖ {nombre:<10} ERROR: {dato['error']}")
        else:
            print(f"  ✓ {nombre:<10} vistos={dato['vistos']:<5} "
                  f"nuevas={dato['nuevas']:<4} descartados={dato['descartados']} "
                  f"({dato['segundos']}s)")
    print("-" * 78)
    if not ofertas:
        print("Sin ofertas nuevas que cumplan los filtros en esta corrida.")
        print("=" * 78)
        return
    print(f"Ofertas nuevas: {len(ofertas)} | a enviar (por rango): {len(elegidas)}\n")
    for i, p in enumerate(elegidas, 1):
        emoji, etiqueta = nivel_descuento(p.descuento_pct)
        rango = rango_clave(p.descuento_pct, rangos)
        original = f"S/{p.precio_original:,.2f}" if p.precio_original else "—"
        print(f"{i:>2}. {emoji} [{etiqueta}] {rango:<6} {p.descuento_pct:5.1f}%  "
              f"{p.tienda.upper():<10} {p.nombre[:48]}")
        print(f"    antes {original} → ahora S/{p.precio_actual:,.2f} "
              f"(ahorras S/{ahorro_soles(p):,.2f})  {p.url[:60]}")
        for advertencia in p.advertencias:
            print(f"    {advertencia}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    args = _parsear_cli(argv)
    # Consolas de Windows (cp1252) no saben imprimir emojis: forzamos UTF-8
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = cargar_config(args.config)
    if args.max_mensajes:
        cfg["notificaciones"]["max_por_corrida"] = max(1, args.max_mensajes)
    solo_tiendas = (
        {t.strip().lower() for t in args.tiendas.split(",") if t.strip()}
        if args.tiendas else None
    )
    if solo_tiendas:
        desconocidas = solo_tiendas - set(REGISTRO)
        if desconocidas:
            log.error("Tiendas desconocidas: %s (disponibles: %s)",
                      ", ".join(desconocidas), ", ".join(REGISTRO))
            return 2

    est = cfg["estado"]
    cfg["_estado"] = Estado(
        ruta=est["ruta"],
        historial_max_por_producto=est["historial_max_por_producto"],
        historial_max_productos=est["historial_max_productos"],
        dias_retencion_notificados=est["dias_retencion_notificados"],
    )

    ofertas, stats = _recolectar(cfg, solo_tiendas)

    # Ordenar por mayor descuento y limitar mensajes (anti-spam)
    # Prioridad de tiendas: Falabella y Ripley primero. Dentro de cada grupo:
    # 1) nivel de descuento (un 90%+ raro de Falabella va al frente),
    # 2) mayor AHORRO en soles (productos caros con buenas ofertas),
    # 3) el % exacto como desempate final.
    prioridad = [t.strip().lower()
                 for t in (cfg["notificaciones"].get("prioridad_tiendas") or [])]

    def _clave_orden(p: Producto) -> tuple[int, int, float, float]:
        try:
            rango = prioridad.index(p.tienda)
        except ValueError:
            rango = len(prioridad)
        nivel = int(p.descuento_pct // 10)  # 90%+ → 9, 80-89% → 8, ...
        return (rango, -nivel, -ahorro_soles(p), -p.descuento_pct)

    ofertas.sort(key=_clave_orden)

    # Anti-repetición #2: dentro de la MISMA corrida no se envían dos copias
    # del mismo producto (gana la mejor rankeada; las copias con otro id de
    # otra tienda o variante se descartan aquí).
    if cfg["filtros"].get("evitar_repetir_productos", True):
        vistas: set[str] = set()
        unicas: list[Producto] = []
        for p in ofertas:
            nn = normalizar_nombre(p.nombre)
            if nn and nn in vistas:
                continue
            if nn:
                vistas.add(nn)
            unicas.append(p)
        ofertas = unicas

    # ---------------- Selección por rangos de descuento ----------------
    # Cada rango (40-50, 50-60, ..., 90+) tiene su propio tope de mensajes
    # (max_por_rango) y puede tener su propio chat de Telegram.
    rangos_cfg = [int(r) for r in
                  (cfg["notificaciones"].get("rangos") or [40, 50, 60, 70, 80, 90])]
    max_rango = int(cfg["notificaciones"].get("max_por_rango") or 12)
    limite = int(cfg["notificaciones"]["max_por_corrida"])

    por_rango: dict[str, list[Producto]] = {}
    for p in ofertas:
        por_rango.setdefault(rango_clave(p.descuento_pct, rangos_cfg), []).append(p)

    elegidas: list[Producto] = []
    # De mayor descuento a menor: si el tope global corta, se quedan los 90%+
    orden_rangos = sorted(por_rango, key=lambda k: -int(k.split("-")[0].rstrip("+")))
    for clave_r in orden_rangos:
        elegidas.extend(por_rango[clave_r][:max_rango])
    elegidas = elegidas[:limite]

    if args.dry_run:
        _imprimir_dry_run(ofertas, stats, elegidas, rangos_cfg)
        cfg["_estado"].guardar()   # historial sí se guarda; notificaciones NO
        return 0

    # ---------------------------- modo real ----------------------------
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.error(
            "Faltan variables de entorno TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID. "
            "Configúralas en GitHub Secrets o en tu shell. Usa --dry-run para probar sin Telegram."
        )
        return 2

    # Chats por rango (opcional): JSON {"50-60": "-100...", "90+": "-100..."}
    # en la variable TELEGRAM_CHATS_POR_RANGO. Los rangos sin chat asignado
    # van al chat base.
    chats_rango: dict[str, str] = {}
    crudo_chats = os.environ.get("TELEGRAM_CHATS_POR_RANGO", "").strip()
    if crudo_chats:
        try:
            datos_chats = json.loads(crudo_chats)
            chats_rango = {str(k): str(v) for k, v in datos_chats.items()}
            log.info("Chats por rango configurados: %s",
                     ", ".join(f"{k}→…{v[-6:]}" for k, v in chats_rango.items()))
        except ValueError as exc:
            log.error("TELEGRAM_CHATS_POR_RANGO no es JSON válido (%s); "
                      "todas las ofertas irán al chat base", exc)

    notificador = Notificador(token, chat_id,
                              chats_por_rango=chats_rango, rangos=rangos_cfg)

    # Responder comandos pendientes (/start, /help, /status) — ver bot/comandos.py
    try:
        from .comandos import procesar_comandos

        procesar_comandos(token, stats)
    except Exception as exc:  # los comandos nunca deben romper el envío de ofertas
        log.warning("No se pudieron procesar los comandos: %s", exc)

    ok_tiendas = sum(1 for s in stats.values() if "error" not in s)
    fallos_tiendas = [n for n, s in stats.items() if "error" in s]
    pausa = float(cfg["notificaciones"]["pausa_entre_mensajes_seg"])

    if cfg["notificaciones"].get("resumen", True):
        minimos_tienda = cfg["filtros"].get("descuento_minimo_tiendas") or {}
        detalle = ""
        if minimos_tienda:
            detalle = " (" + ", ".join(
                f"{t.title()} ≥{int(v)}%"
                for t, v in sorted(minimos_tienda.items())
            ) + ")"
        # Distribución por rango de descuento (cada rango = un chat)
        conteo_rangos: dict[str, int] = {}
        for p in elegidas:
            r = rango_clave(p.descuento_pct, rangos_cfg)
            conteo_rangos[r] = conteo_rangos.get(r, 0) + 1
        dist = " · ".join(
            f"{r}: {conteo_rangos[r]}"
            for r in sorted(conteo_rangos,
                            key=lambda k: -int(k.split("-")[0].rstrip("+")))
        )
        resumen = (
            "🔎 Revisión de ofertas — Perú\n"
            f"Tiendas OK: {ok_tiendas}/{len(stats)}"
            + (f"\n⚠️ Con errores: {', '.join(fallos_tiendas)}" if fallos_tiendas else "")
            + f"\nOfertas nuevas (≥{cfg['filtros']['descuento_minimo']}%{detalle}): {len(ofertas)}"
            + (f"\n📨 Enviando {len(elegidas)} por rango → {dist}" if elegidas else "")
            + ("\n\nLos chats configurados reciben solo su rango." if chats_rango else "")
        )
        try:
            notificador.enviar_texto(resumen)
        except RuntimeError as exc:
            log.error("No se pudo enviar el resumen: %s", exc)

    enviados = fallos = 0
    try:
        for producto in elegidas:
            destino = notificador.chat_para_producto(producto)
            r = rango_clave(producto.descuento_pct, rangos_cfg)
            log.debug("enviando %s (%.1f%%, rango %s) → chat …%s",
                      producto.clave, producto.descuento_pct, r, destino[-6:])
            if notificador.enviar_producto(producto, chat_id=destino):
                cfg["_estado"].marcar_notificado(
                    producto.clave, producto.precio_actual,
                    normalizar_nombre(producto.nombre),
                )
                enviados += 1
            else:
                fallos += 1
            time.sleep(pausa)
    finally:
        # El estado se guarda SIEMPRE (aunque algo falle a mitad de lote):
        # los productos ya enviados quedan registrados y no se repiten.
        cfg["_estado"].guardar()

    log.info("Corrida terminada: %d enviadas, %d fallos, %d ofertas en cola sin enviar",
             enviados, fallos, max(0, len(ofertas) - len(elegidas)))
    if fallos:
        # Un fallo de UN mensaje NO debe tumbar la corrida: si sale con
        # código ≠ 0, Actions salta el paso de "Guardar estado" y el bot
        # repite TODO en la siguiente corrida (bug que ya causó repeats).
        log.warning(
            "%d mensaje(s) fallaron (imagen/URL del producto); se reintentarán "
            "solos en la próxima corrida. Estado guardado correctamente.", fallos,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
