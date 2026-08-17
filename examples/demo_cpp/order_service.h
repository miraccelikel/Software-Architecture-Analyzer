#ifndef SHOP_ORDER_SERVICE_H
#define SHOP_ORDER_SERVICE_H

#include <string>
#include <vector>
#include "infrastructure.h"

namespace shop {

class OrderService {
 public:
  OrderService();
  std::string process(int status, double total, const std::string& currency,
                      int retries, bool force, const std::string& note);
  int pending() const;

 private:
  MySqlConnection* db_;
  FileLogger* logger_;
  std::vector<int> orders_;
};

}  // namespace shop

#endif
