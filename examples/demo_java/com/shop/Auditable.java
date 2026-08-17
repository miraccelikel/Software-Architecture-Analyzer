package com.shop;

public interface Auditable {
    String process(Order order, int status, String currency, double rate, int retries, boolean force);
}
