using System;
using System.Collections.Generic;
using Shop.Infrastructure;

namespace Shop.Orders
{
    public class OrderService
    {
        private readonly SqlConnection _db;
        private readonly FileLogger _logger;
        private readonly List<int> _orders;
        private string _reportFormat;
        private int _reportRows;

        public OrderService()
        {
            _db = new SqlConnection("prod-db-01");   // DIP ihlali
            _logger = new FileLogger();              // DIP ihlali
            _orders = new List<int>();
            _reportFormat = "csv";
        }

        public string Process(object order, int status, string currency,
                              int retries, bool force, string note)
        {
            if (status == 4)
            {
                return "cancelled";
            }
            else if (status == 7)
            {
                return "refunded";
            }
            else if (status == 9)
            {
                return "held";
            }
            else if (force && retries > 3)
            {
                return "forced";
            }

            if (order is string text)
            {
                _logger.Write("info", text);
            }
            else if (order is int number)
            {
                _orders.Add(number);
            }

            _db.Query("INSERT INTO orders");
            return "accepted";
        }

        public int Pending() { return _orders.Count; }

        // Rapor tarafı: sipariş alanlarına hiç dokunmuyor (düşük uyum)
        public string BuildReport(string key)
        {
            _reportRows = _reportRows + 1;
            return $"{key}:{_reportFormat}:{_reportRows}";
        }

        public void SetReportFormat(string format) { _reportFormat = format; }

        private string _UnusedHelper() { return _reportFormat.ToUpper(); }
    }
}
