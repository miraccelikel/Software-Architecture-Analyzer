"""Ödeme nesnelerini üreten fabrika (uzun dallanma zinciri ile)."""

from .payments import (BankTransferPayment, CreditCardPayment,
                       PaymentStrategy, WalletPayment)


class PaymentFactory:
    @staticmethod
    def create(kind: str, token: str) -> PaymentStrategy:
        if kind == "card":
            return CreditCardPayment(token)
        elif kind == "transfer":
            return BankTransferPayment(token)
        elif kind == "wallet":
            return WalletPayment(token)
        elif kind == "legacy_card":
            return CreditCardPayment(token)
        else:
            raise ValueError(f"bilinmeyen ödeme türü: {kind}")
