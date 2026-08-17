"""Döngüsel bağımlılığın bir ucu."""

from .legacy_order_service import OrderService


class AuditTrail:
    def __init__(self) -> None:
        self.entries = []

    def record(self, service: OrderService, action: str) -> None:
        self.entries.append((action, len(service.orders)))
