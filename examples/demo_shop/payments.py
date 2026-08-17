"""Ödeme yöntemleri — Strategy ailesi."""

from abc import ABC, abstractmethod


class PaymentStrategy(ABC):
    """Tüm ödeme yöntemlerinin ortak arayüzü."""

    @abstractmethod
    def pay(self, amount: float) -> str:
        ...


class CreditCardPayment(PaymentStrategy):
    def __init__(self, number: str) -> None:
        self.number = number

    def pay(self, amount: float) -> str:
        return f"{amount} TL kredi kartından çekildi ({self.number[-4:]})"


class BankTransferPayment(PaymentStrategy):
    def __init__(self, iban: str) -> None:
        self.iban = iban

    def pay(self, amount: float) -> str:
        return f"{amount} TL havale ile alındı ({self.iban[:6]})"


class WalletPayment(PaymentStrategy):
    def __init__(self, wallet_id: str) -> None:
        self.wallet_id = wallet_id

    def pay(self, amount: float) -> str:
        return f"{amount} TL cüzdandan düşüldü"


class Checkout:
    """Bağlam sınıfı: stratejiyi dışarıdan alır."""

    def __init__(self, strategy: PaymentStrategy) -> None:
        self.strategy = strategy

    def complete(self, amount: float) -> str:
        return self.strategy.pay(amount)
