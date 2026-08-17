"""Ödeme davranışını sarmalayan dekoratör — Decorator."""

from .payments import CreditCardPayment, PaymentStrategy


class LoggedPayment(PaymentStrategy):
    def __init__(self, inner: PaymentStrategy, prefix: str = "[ödeme]") -> None:
        self.inner = inner
        self.prefix = prefix

    def pay(self, amount: float) -> str:
        result = self.inner.pay(amount)
        return f"{self.prefix} {result}"


class ReadOnlyPayment(CreditCardPayment):
    """LSP ihlali: üst türün çalışan davranışını iptal ediyor."""

    def pay(self, amount: float) -> str:
        raise NotImplementedError("bu ödeme yöntemi kapalı")
