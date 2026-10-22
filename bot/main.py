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
import logging
import os
import sys
import time

from .config import cargar_config
from .filters import aplicar_descuento, cumple_filtros, nivel_descuento
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
        for producto in productos:
            estado.observar(producto.clave, producto.precio_actual)
            aplicar_descuento(producto)
            vistos += 1

            ok, motivo = cumple_filtros(producto, cfg["filtros"])
            if not ok:
                descartados += 1
                log.debug("[%s] descartado %s: %s", nombre, producto.id, motivo)
                continue

            producto.advertencias = estado.advertencias(producto)
            avisar, razon = estado.debe_notificar(producto.clave, producto.precio_actual)
            if not avisar:
                descartados += 1
                log.debug("[%s] sin aviso %s: %s", nombre, producto.id, razon)
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


def _imprimir_dry_run(ofertas: list[Producto], stats: dict, limite: int) -> None:
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
    elegidas = ofertas[:limite]
    print(f"Ofertas nuevas: {len(ofertas)} | a mostrar (tope {limite}): {len(elegidas)}\n")
    for i, p in enumerate(elegidas, 1):
        emoji, etiqueta = nivel_descuento(p.descuento_pct)
        original = f"S/{p.precio_original:,.2f}" if p.precio_original else "—"
        print(f"{i:>2}. {emoji} [{etiqueta}] {p.descuento_pct:5.1f}%  "
              f"{p.tienda.upper():<10} {p.nombre[:52]}")
        print(f"    antes {original} → ahora S/{p.precio_actual:,.2f}  "
              f"id={p.id}  {p.url[:70]}")
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
    ofertas.sort(key=lambda p: p.descuento_pct, reverse=True)
    limite = int(cfg["notificaciones"]["max_por_corrida"])
    elegidas = ofertas[:limite]

    if args.dry_run:
        _imprimir_dry_run(ofertas, stats, limite)
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

    notificador = Notificador(token, chat_id)
    ok_tiendas = sum(1 for s in stats.values() if "error" not in s)
    fallos_tiendas = [n for n, s in stats.items() if "error" in s]
    pausa = float(cfg["notificaciones"]["pausa_entre_mensajes_seg"])

    if cfg["notificaciones"].get("resumen", True):
        resumen = (
            "🔎 Revisión de ofertas — Perú\n"
            f"Tiendas OK: {ok_tiendas}/{len(stats)}"
            + (f"\n⚠️ Con errores: {', '.join(fallos_tiendas)}" if fallos_tiendas else "")
            + f"\nOfertas nuevas (≥{cfg['filtros']['descuento_minimo']}%): {len(ofertas)}"
            + (f"\nEnviando las mejores {len(elegidas)}…" if elegidas else "")
        )
        try:
            notificador.enviar_texto(resumen)
        except RuntimeError as exc:
            log.error("No se pudo enviar el resumen: %s", exc)

    enviados = fallos = 0
    for producto in elegidas:
        if notificador.enviar_producto(producto):
            cfg["_estado"].marcar_notificado(producto.clave, producto.precio_actual)
            enviados += 1
        else:
            fallos += 1
        time.sleep(pausa)

    cfg["_estado"].guardar()
    log.info("Corrida terminada: %d enviadas, %d fallos, %d ofertas en cola sin enviar",
             enviados, fallos, max(0, len(ofertas) - len(elegidas)))
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
