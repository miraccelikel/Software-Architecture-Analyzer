package com.shop;

public class WalletPayment implements PaymentStrategy {
    private final String walletId;

    public WalletPayment(String walletId) { this.walletId = walletId; }

    @Override
    public String pay(double amount) { return amount + " TL cüzdan"; }
}
