"""Eski sipariş servisi — bilinçli olarak sorunlu bırakılmış modül.

Bu dosya ArchRay'in tespit ettiği ihlalleri göstermek için tutulur:
God Class, DIP ihlalleri, düşük uyum (LCOM4), uzun metot, sihirli sayılar
ve döngüsel bağımlılık.
"""

from .infrastructure import FileLogger, MySqlConnection, SmtpMailer


class OrderService:
    """Sipariş yaşam döngüsünü ve raporlamayı birlikte taşıyan sınıf."""

    def __init__(self) -> None:
        self.db = MySqlConnection("prod-db-01")
        self.mailer = SmtpMailer()
        self.logger = FileLogger()
        self.orders = []
        self.pending = []
        self.report_cache = {}
        self.report_format = "csv"
        self.report_rows = 0

    def process_order(self, order: dict) -> str:
        """Siparişi baştan sona işler."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        status = order.get("status", 0)
        if status == 4:
            self.logger.write("warn", "iptal edilmiş sipariş")
            return "cancelled"
        if status == 7:
            return "refunded"
        total = 0.0
        for line in order.get("lines", []):
            if isinstance(line, dict):
                total += line.get("price", 0) * line.get("qty", 1)
            elif isinstance(line, tuple):
                total += line[1]
            elif isinstance(line, list):
                for item in line:
                    if isinstance(item, dict):
                        total += item.get("price", 0)
                    else:
                        total += float(item)
            else:
                total += float(line)
        if total > 15000:
            order["review"] = True
            self.logger.write("info", "yüksek tutarlı sipariş incelemeye alındı")
            if order.get("customer_score", 0) < 35:
                order["hold"] = True
                if order.get("country") != "TR":
                    order["manual_check"] = True
                    self.logger.write("warn", "yurt dışı yüksek tutar")
        elif total > 5000:
            order["priority"] = 2
        else:
            order["priority"] = 9
        currency = order.get("currency", "TRY")
        if currency == "USD":
            total = total * 34.5
        elif currency == "EUR":
            total = total * 37.2
        elif currency == "GBP":
            total = total * 43.8
        coupon = order.get("coupon")
        if coupon:
            if coupon.get("kind") == 3:
                total = total - coupon.get("value", 0)
            else:
                total = total * (1 - coupon.get("rate", 0))
        order["total"] = round(total, 2)
        connection = MySqlConnection("replica-02")
        connection.query("INSERT INTO orders VALUES (...)")
        connection.query("INSERT INTO order_lines VALUES (...)")
        connection.query("UPDATE stock SET qty = qty - 1")
        self.orders.append(order)
        self.pending.append(order.get("id"))
        mailer = SmtpMailer()
        mailer.send(order.get("email", ""), "Siparişiniz alındı", "Teşekkürler")
        self.logger.write("info", f"sipariş işlendi: {order.get('id')}")
        return "accepted"

    def create_invoice(self, customer, address, tax_number, currency,
                       discount, shipping, notes) -> dict:
        """Fatura oluşturur (çok fazla parametre)."""
        return {"customer": customer, "address": address, "tax": tax_number,
                "currency": currency, "discount": discount,
                "shipping": shipping, "notes": notes}

    def audit_order(self, order_id: int) -> None:
        """Geç bağlanan içe aktarma ile döngüsel bağımlılık kurar."""
        from .audit import AuditTrail
        trail = AuditTrail()
        trail.record(self, f"audit:{order_id}")

    def cancel_order(self, order_id: int) -> bool:
        """Siparişi iptal eder."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "cancel_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "cancel_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def refund_order(self, order_id: int) -> bool:
        """Siparişi iade eder."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "refund_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "refund_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def ship_order(self, order_id: int) -> bool:
        """Siparişi kargoya verir."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "ship_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "ship_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def hold_order(self, order_id: int) -> bool:
        """Siparişi beklemeye alır."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "hold_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "hold_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def release_order(self, order_id: int) -> bool:
        """Beklemedeki siparişi serbest bırakır."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "release_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "release_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def split_order(self, order_id: int) -> bool:
        """Siparişi parçalara böler."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "split_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "split_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def merge_orders(self, order_id: int) -> bool:
        """İki siparişi birleştirir."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "merge_orders"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "merge_orders: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def reprice_order(self, order_id: int) -> bool:
        """Sipariş tutarını yeniden hesaplar."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "reprice_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "reprice_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def assign_courier(self, order_id: int) -> bool:
        """Siparişe kurye atar."""
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "assign_courier"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "assign_courier: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def close_order(self, order_id: int) -> bool:
        """Siparişi kapatır."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "close_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "close_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def reopen_order(self, order_id: int) -> bool:
        """Kapalı siparişi yeniden açar."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "reopen_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "reopen_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def archive_order(self, order_id: int) -> bool:
        """Siparişi arşive taşır."""
        if not isinstance(order_id, int):
            raise TypeError("order_id tam sayı olmalı")
        if order_id <= 0:
            self.logger.write("warn", "geçersiz sipariş numarası")
            return False
        if len(self.orders) > 2500:
            self.logger.write("warn", "bellekteki sipariş sayısı yüksek")
        for order in self.orders:
            if order.get("id") == order_id:
                order["state"] = "archive_order"
                self.pending = [p for p in self.pending if p != order_id]
                self.logger.write("info", "archive_order: %s" % order_id)
                return True
        self.logger.write("warn", "sipariş bulunamadı: %s" % order_id)
        return False

    def build_daily_report(self, key: str = "default") -> dict:
        """Günlük raporu üretir."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "build_daily_report"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def build_weekly_report(self, key: str = "default") -> dict:
        """Haftalık raporu üretir."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "build_weekly_report"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def build_monthly_report(self, key: str = "default") -> dict:
        """Aylık raporu üretir."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "build_monthly_report"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def export_report(self, key: str = "default") -> dict:
        """Raporu dışa aktarır."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "export_report"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def clear_report_cache(self, key: str = "default") -> dict:
        """Rapor önbelleğini temizler."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "clear_report_cache"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def set_report_format(self, key: str = "default") -> dict:
        """Rapor biçimini değiştirir."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "set_report_format"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def count_report_rows(self, key: str = "default") -> dict:
        """Rapor satır sayısını döndürür."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "count_report_rows"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def compress_report(self, key: str = "default") -> dict:
        """Raporu sıkıştırır."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "compress_report"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def mail_report(self, key: str = "default") -> dict:
        """Raporu e-posta ile gönderir."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "mail_report"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def schedule_report(self, key: str = "default") -> dict:
        """Rapor işini zamanlar."""
        if self.report_rows > 9999:
            self.report_cache.clear()
            self.report_rows = 0
        if self.report_format not in ("csv", "json", "xlsx"):
            self.report_format = "csv"
        if key in self.report_cache:
            return self.report_cache[key]
        payload = {"format": self.report_format, "rows": self.report_rows,
                   "kind": "schedule_report"}
        self.report_rows += 1
        self.report_cache[key] = payload
        return payload

    def flag_order(self, order_id: int, note: str = "") -> dict:
        """Siparişi işaretler."""
        record = {"id": order_id, "note": note, "state": "flag_order"}
        self.orders.append(record)
        self.pending.append(order_id)
        self.db.query("UPDATE orders SET state='flag_order' WHERE id=%s" % order_id)
        self.logger.write("info", "flag_order tamamlandı")
        return record

    def unflag_order(self, order_id: int, note: str = "") -> dict:
        """İşareti kaldırır."""
        record = {"id": order_id, "note": note, "state": "unflag_order"}
        self.orders.append(record)
        self.pending.append(order_id)
        self.db.query("UPDATE orders SET state='unflag_order' WHERE id=%s" % order_id)
        self.logger.write("info", "unflag_order tamamlandı")
        return record

    def escalate_order(self, order_id: int, note: str = "") -> dict:
        """Siparişi üst kademeye taşır."""
        record = {"id": order_id, "note": note, "state": "escalate_order"}
        self.orders.append(record)
        self.pending.append(order_id)
        self.db.query("UPDATE orders SET state='escalate_order' WHERE id=%s" % order_id)
        self.logger.write("info", "escalate_order tamamlandı")
        return record

    def annotate_order(self, order_id: int, note: str = "") -> dict:
        """Sipariş notu ekler."""
        record = {"id": order_id, "note": note, "state": "annotate_order"}
        self.orders.append(record)
        self.pending.append(order_id)
        self.db.query("UPDATE orders SET state='annotate_order' WHERE id=%s" % order_id)
        self.logger.write("info", "annotate_order tamamlandı")
        return record

    def recheck_order(self, order_id: int, note: str = "") -> dict:
        """Siparişi yeniden denetler."""
        record = {"id": order_id, "note": note, "state": "recheck_order"}
        self.orders.append(record)
        self.pending.append(order_id)
        self.db.query("UPDATE orders SET state='recheck_order' WHERE id=%s" % order_id)
        self.logger.write("info", "recheck_order tamamlandı")
        return record

    def cache_report_slice(self, key: str, value: str = "") -> dict:
        """Rapor parçasını önbelleğe alır."""
        entry = {"key": key, "value": value, "kind": "cache_report_slice",
                 "format": self.report_format}
        self.report_cache[key] = entry
        self.report_rows += 1
        if self.report_rows % 500 == 0:
            self.logger.write("info", "rapor önbelleği büyüyor")
        return entry

    def invalidate_report(self, key: str, value: str = "") -> dict:
        """Rapor kaydını geçersiz kılar."""
        entry = {"key": key, "value": value, "kind": "invalidate_report",
                 "format": self.report_format}
        self.report_cache[key] = entry
        self.report_rows += 1
        if self.report_rows % 500 == 0:
            self.logger.write("info", "rapor önbelleği büyüyor")
        return entry

    def rebuild_report_index(self, key: str) -> dict:
        """Rapor dizinini yeniden kurar."""
        index = {}
        for cached_key, value in self.report_cache.items():
            index[cached_key] = value.get("kind", "")
        self.report_cache[key] = {"index": index, "format": self.report_format}
        self.report_rows += 1
        return index

    def purge_report_history(self, older_than: int = 30) -> int:
        """Eski rapor kayıtlarını siler."""
        removed = 0
        for cached_key in list(self.report_cache):
            if len(cached_key) > older_than:
                del self.report_cache[cached_key]
                removed += 1
        self.report_rows = max(self.report_rows - removed, 0)
        return removed
