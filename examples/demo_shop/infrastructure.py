"""Somut altyapı sınıfları — DIP ihlallerinin hedefi."""


class MySqlConnection:
    def __init__(self, host: str = "localhost") -> None:
        self.host = host

    def query(self, sql: str) -> list:
        return []


class SmtpMailer:
    def send(self, to: str, subject: str, body: str) -> bool:
        return True


class FileLogger:
    def write(self, level: str, message: str) -> None:
        pass
