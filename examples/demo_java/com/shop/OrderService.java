package com.shop;

import com.shop.MySqlConnection;

public class OrderService implements Auditable {
    private MySqlConnection db;
    private int count;
    private String reportFormat;

    public OrderService() {
        this.db = new MySqlConnection("prod");
        this.reportFormat = "csv";
    }

    public String process(Order order, int status, String currency, double rate, int retries, boolean force) {
        if (status == 4) {
            return "cancelled";
        } else if (status == 7) {
            return "refunded";
        } else if (status == 9) {
            return "held";
        } else if (force && retries > 3) {
            return "forced";
        }
        if (order instanceof PriorityOrder) {
            this.count = this.count + 1;
        } else if (order instanceof BulkOrder) {
            this.count = this.count + 2;
        }
        return "ok";
    }

    public String reportFormat() { return this.reportFormat; }
}

class MySqlConnection {
    MySqlConnection(String host) {}
}
