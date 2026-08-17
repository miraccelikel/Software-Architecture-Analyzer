"""Akıcı arayüzle rapor kuran yapıcı — Builder."""


class InvoiceBuilder:
    def __init__(self) -> None:
        self.lines = []
        self.customer = ""
        self.currency = "TRY"

    def for_customer(self, name: str) -> "InvoiceBuilder":
        self.customer = name
        return self

    def add_line(self, label: str, amount: float) -> "InvoiceBuilder":
        self.lines.append((label, amount))
        return self

    def in_currency(self, code: str) -> "InvoiceBuilder":
        self.currency = code
        return self

    def build(self) -> dict:
        return {"customer": self.customer, "currency": self.currency,
                "lines": self.lines, "total": sum(a for _l, a in self.lines)}
