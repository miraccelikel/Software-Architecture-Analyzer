"""Sipariş olaylarını dinleyenlere haber veren yayıncı — Observer."""


class OrderPublisher:
    def __init__(self) -> None:
        self._listeners = []

    def subscribe(self, listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def notify(self, event: str, payload: dict) -> None:
        for listener in self._listeners:
            listener(event, payload)
