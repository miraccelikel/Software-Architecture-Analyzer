#include "payment.h"

namespace shop {

CardPayment::CardPayment(const std::string& number) : number_(number) {}

std::string CardPayment::pay(double amount) {
  return std::to_string(amount) + " TL kart: " + number_;
}

WalletPayment::WalletPayment(const std::string& wallet) : wallet_(wallet) {}

std::string WalletPayment::pay(double amount) {
  return std::to_string(amount) + " TL cüzdan: " + wallet_;
}

Checkout::Checkout(PaymentStrategy* strategy) : strategy_(strategy) {}

std::string Checkout::complete(double amount) { return strategy_->pay(amount); }

}  // namespace shop
