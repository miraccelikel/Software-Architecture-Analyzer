package com.shop;

public class CardPayment implements PaymentStrategy {
    private final String number;

    public CardPayment(String number) { this.number = number; }

    @Override
    public String pay(double amount) { return amount + " TL kart"; }
}
