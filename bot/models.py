"""Modelos de datos compartidos por todas las tiendas."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Producto:
    """Representación normalizada de un producto de cualquier tienda."""

    tienda: str
    id: str
    nombre: str
    precio_actual: float
    precio_original: float | None = None
    marca: str = ""
    url: str = ""
    imagen: str | None = None
    categoria: str | None = None
    # Se calcula SIEMPRE con (original - actual) / original * 100,
    # nunca confiando en el % que muestra la tienda.
    descuento_pct: float = 0.0
    advertencias: list[str] = field(default_factory=list)

    @property
    def clave(self) -> str:
        """Clave única para deduplicación e historial: 'tienda:id'."""
        return f"{self.tienda}:{self.id}"
