using System;

namespace Shop.Payments
{
    /// <summary>Strategy ailesinin ortak sözleşmesi.</summary>
    public interface IPaymentStrategy
    {
        string Pay(decimal amount);
    }

    public class CardPayment : IPaymentStrategy
    {
        private readonly string _number;

        public CardPayment(string number) { _number = number; }

        public string Pay(decimal amount) => $"{amount} TL kart: {_number}";
    }

    public class WalletPayment : IPaymentStrategy
    {
        private readonly string _wallet;

        public WalletPayment(string wallet) { _wallet = wallet; }

        public string Pay(decimal amount) => $"{amount} TL cüzdan: {_wallet}";
    }

    /// <summary>Bağlam sınıfı: stratejiyi dışarıdan alır.</summary>
    public class Checkout
    {
        private readonly IPaymentStrategy _strategy;

        public Checkout(IPaymentStrategy strategy) { _strategy = strategy; }

        public string Complete(decimal amount) => _strategy.Pay(amount);
    }
}
