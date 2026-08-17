namespace Shop.Infrastructure
{
    public class SqlConnection
    {
        private readonly string _host;

        public SqlConnection(string host) { _host = host; }

        public void Query(string sql) { }
    }

    public class FileLogger
    {
        public void Write(string level, string message) { }
    }
}
