"""Cálculo de descuentos, niveles y filtros configurables."""
from __future__ import annotations

import logging

from .models import Producto

log = logging.getLogger("bot.filtros")


def calcular_descuento(precio_actual: float, precio_original: float | None) -> float:
    """(original - actual) / original * 100.

    Se calcula SIEMPRE nosotros; nunca confiamos en el % de la tienda.
    Devuelve 0 si no hay precio original válido.
    """
    if not precio_original or precio_original <= 0 or precio_actual <= 0:
        return 0.0
    if precio_original <= precio_actual:
        return 0.0
    return (precio_original - precio_actual) / precio_original * 100.0


#: (umbral_mínimo, emoji, etiqueta) de mayor a menor — cubre los rangos de
#: chat: 🟡 40-49 · 🔵 50-59 · 🟢 60-69 · 🟠 70-79 · 🔴 80-89 · 💀 90+
_NIVELES = (
    (90, "💀", "90%+"),
    (80, "🔴", "80-89%"),
    (70, "🟠", "70-79%"),
    (60, "🟢", "60-69%"),
    (50, "🔵", "50-59%"),
    (40, "🟡", "40-49%"),
)


def nivel_descuento(descuento_pct: float) -> tuple[str, str]:
    """(emoji, etiqueta) según el nivel del descuento."""
    for umbral, emoji, etiqueta in _NIVELES:
        if descuento_pct >= umbral:
            return emoji, etiqueta
    return "⚪", f"{descuento_pct:.0f}%"


def rango_clave(descuento_pct: float, rangos: list[int]) -> str:
    """Clave del rango al que pertenece un % de descuento, p. ej. con
    rangos=[40,50,60,70,80,90] → '40-50', '50-60', ..., '90+'."""
    if not rangos:
        return "todos"
    for i in range(len(rangos) - 1):
        if descuento_pct < rangos[i + 1]:
            return f"{rangos[i]}-{rangos[i + 1]}"
    return f"{rangos[-1]}+"


def aplicar_descuento(producto: Producto) -> None:
    """Calcula y asigna el descuento real del producto."""
    producto.descuento_pct = calcular_descuento(
        producto.precio_actual, producto.precio_original
    )


def cumple_filtros(producto: Producto, filtros: dict) -> tuple[bool, str]:
    """Aplica los filtros de config. Devuelve (¿pasa?, motivo).

    El descuento mínimo puede variar por tienda con
    filtros.descuento_minimo_tiendas (p. ej. Falabella/Ripley a 50%).
    """
    minimos_tienda = filtros.get("descuento_minimo_tiendas") or {}
    minimo = float(minimos_tienda.get(producto.tienda) or filtros.get("descuento_minimo", 70))
    if producto.descuento_pct < minimo:
        return False, f"descuento {producto.descuento_pct:.0f}% < {minimo:.0f}%"

    pmin = float(filtros.get("precio_minimo") or 0)
    if producto.precio_actual < pmin:
        return False, f"precio S/{producto.precio_actual:.2f} < mínimo S/{pmin:.2f}"

    pmax = filtros.get("precio_maximo")
    if pmax is not None and producto.precio_actual > float(pmax):
        return False, f"precio S/{producto.precio_actual:.2f} > máximo S/{float(pmax):.2f}"

    texto = f"{producto.nombre} {producto.categoria or ''}".lower()

    excluidas = [p.lower() for p in (filtros.get("excluir_palabras") or [])]
    for palabra in excluidas:
        if palabra in texto:
            return False, f"palabra excluida '{palabra}'"

    palabras_clave = [p.lower() for p in (filtros.get("palabras_clave") or [])]
    if palabras_clave and not any(p in texto for p in palabras_clave):
        return False, "sin palabras clave coincidentes"

    return True, "ok"


def normalizar_nombre(nombre: str) -> str:
    """Versión canónica del nombre para detectar el MISMO producto aunque
    aparezca en varias tiendas o con variantes (mayúsculas/acentos/símbolos)."""
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", nombre or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def ahorro_soles(producto: Producto) -> float:
    """Ahorro absoluto en soles (lo que ahorras vs. el precio original)."""
    if producto.precio_original and producto.precio_original > producto.precio_actual:
        return producto.precio_original - producto.precio_actual
    return 0.0


def precio_original_inflado(producto: Producto, razon_max: float) -> bool:
    """Anti-inflado #1: si el "precio original" es muchísimas veces el precio
    actual (ej. audífonos de S/29 "antes S/5,619" = 194×), el descuento es
    falso. 15× equivale a un descuento máximo creíble de ~93%.

    Se evalúa DESPUÉS del filtro de repetidos (el contador de repetidos debe
    ver los precios originales aunque la razón sea absurda).
    """
    if razon_max <= 0 or not producto.precio_original or producto.precio_actual <= 0:
        return False
    return (producto.precio_original / producto.precio_actual) > razon_max


def filtrar_originales_repetidos(
    productos: list[Producto], min_repeticiones: int
) -> list[Producto]:
    """Anti-inflado #2: si el MISMO «precio original» aparece en varios
    productos distintos de una tienda, es una señal clásica de ListPrice
    inflado (ej. S/5,619 repetido en audífonos, parlantes y lentes).

    Devuelve la lista de productos descartados (ya con su advertencia).
    """
    if min_repeticiones <= 0 or not productos:
        return []
    conteo: dict[float, int] = {}
    for p in productos:
        if p.precio_original:
            conteo[p.precio_original] = conteo.get(p.precio_original, 0) + 1

    descartados: list[Producto] = []
    afectados = 0
    for p in productos:
        if not p.precio_original:
            continue
        veces = conteo[p.precio_original]
        if veces >= min_repeticiones:
            p.advertencias.append(
                f"⚠️ El precio original S/{p.precio_original:,.2f} aparece en "
                f"{veces} productos distintos: probablemente inflado"
            )
            descartados.append(p)
            afectados += 1
    if afectados:
        log.info(
            "Anti-inflado: descartados %d productos con precios 'originales' repetidos",
            afectados,
        )
    return descartados

