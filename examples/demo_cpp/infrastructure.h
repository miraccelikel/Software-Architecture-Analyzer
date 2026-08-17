#ifndef SHOP_INFRASTRUCTURE_H
#define SHOP_INFRASTRUCTURE_H

#include <string>

namespace shop {

class MySqlConnection {
 public:
  explicit MySqlConnection(const std::string& host) : host_(host) {}
  void query(const std::string& sql) { last_ = sql; }

 private:
  std::string host_;
  std::string last_;
};

class FileLogger {
 public:
  void write(const std::string& level, const std::string& message) { last_ = message; }

 private:
  std::string last_;
};

}  // namespace shop

#endif
