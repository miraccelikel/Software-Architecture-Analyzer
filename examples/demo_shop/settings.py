"""Uygulama ayarları — Singleton."""


class Settings:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.values = {}
        return cls._instance

    @classmethod
    def get_instance(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = Settings()
        return cls._instance

    def get(self, key: str, default=None):
        return self.values.get(key, default)
