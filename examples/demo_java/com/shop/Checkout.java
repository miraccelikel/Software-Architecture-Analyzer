package com.shop;

public class Checkout {
    private PaymentStrategy strategy;

    public Checkout(PaymentStrategy strategy) { this.strategy = strategy; }

    public String complete(double amount) { return this.strategy.pay(amount); }
}
