package com.shop;

public class InvoiceBuilder {
    private String customer;
    private String currency = "TRY";
    private double total;

    public InvoiceBuilder forCustomer(String name) { this.customer = name; return this; }

    public InvoiceBuilder addLine(double amount) { this.total = this.total + amount; return this; }

    public InvoiceBuilder inCurrency(String code) { this.currency = code; return this; }

    public String build() { return this.customer + " " + this.total + " " + this.currency; }
}
