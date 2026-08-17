#ifndef SHOP_PAYMENT_H
#define SHOP_PAYMENT_H

#include <string>

namespace shop {

// Saf sanal arayüz: Strategy ailesinin ortak sözleşmesi
class PaymentStrategy {
 public:
  virtual ~PaymentStrategy() {}
  virtual std::string pay(double amount) = 0;
};

class CardPayment : public PaymentStrategy {
 public:
  explicit CardPayment(const std::string& number);
  std::string pay(double amount);

 private:
  std::string number_;
};

class WalletPayment : public PaymentStrategy {
 public:
  explicit WalletPayment(const std::string& wallet);
  std::string pay(double amount);

 private:
  std::string wallet_;
};

// Bağlam sınıfı: stratejiyi dışarıdan alır
class Checkout {
 public:
  explicit Checkout(PaymentStrategy* strategy);
  std::string complete(double amount);

 private:
  PaymentStrategy* strategy_;
};

}  // namespace shop

#endif
