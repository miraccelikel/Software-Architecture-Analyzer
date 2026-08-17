#include "order_service.h"

namespace shop {

OrderService::OrderService() {
  db_ = new MySqlConnection("prod-db-01");   // DIP: somut sınıfa doğrudan bağımlılık
  logger_ = new FileLogger();
}

std::string OrderService::process(int status, double total, const std::string& currency,
                                  int retries, bool force, const std::string& note) {
  if (status == 4) {
    return "cancelled";
  } else if (status == 7) {
    return "refunded";
  } else if (status == 9) {
    return "held";
  } else if (force && retries > 3) {
    return "forced";
  }

  if (total > 15000) {
    for (int i = 0; i < retries; i++) {
      if (currency == "USD") {
        while (i < 3) {
          if (note.empty()) {
            logger_->write("warn", "eksik not");
          }
          i++;
        }
      }
    }
  }
  orders_.push_back(status);
  db_->query("INSERT INTO orders");
  return "accepted";
}

int OrderService::pending() const { return static_cast<int>(orders_.size()); }

}  // namespace shop
