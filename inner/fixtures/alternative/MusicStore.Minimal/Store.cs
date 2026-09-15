using System.Globalization;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace MusicStore.Minimal;

public sealed class Album
{
    public int AlbumId { get; set; }

    public string Title { get; set; }

    public int GenreId { get; set; }

    public string Genre { get; set; }

    public string Artist { get; set; }

    public decimal Price { get; set; }
}

public sealed class CartLine
{
    public int RecordId { get; set; }

    public int AlbumId { get; set; }

    public string Title { get; set; }

    public int Count { get; set; }

    public decimal Price { get; set; }
}

/// <summary>
/// 素の ADO.NET で SQLite を直接扱うデータ層。EF Core を使わない点が正例フィクスチャとの
/// 構造上の違いであり、要求（外部から観測できる振る舞い）だけを共有する。
/// 価格は丸め誤差を避けるため TEXT に invariant の "0.00" 形式で保存し、集計は C# 側で行う。
/// </summary>
public sealed class Store
{
    private readonly string connectionString;
    private readonly string catalogPath;

    public Store(string connectionString, string catalogPath)
    {
        this.connectionString = connectionString;
        this.catalogPath = catalogPath;
    }

    public List<string> Genres { get; } = new List<string>();

    public void Initialize()
    {
        using var connection = Open();
        Execute(connection, Schema);

        if (Scalar(connection, "SELECT COUNT(*) FROM Genres") == 0)
        {
            Seed(connection);
        }

        Genres.Clear();
        using (var command = connection.CreateCommand())
        {
            command.CommandText = "SELECT Name FROM Genres ORDER BY GenreId";
            using var reader = command.ExecuteReader();
            while (reader.Read())
            {
                Genres.Add(reader.GetString(0));
            }
        }
    }

    public Album FindAlbum(int albumId)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = AlbumSelect + " WHERE a.AlbumId = $id";
        command.Parameters.AddWithValue("$id", albumId);
        using var reader = command.ExecuteReader();
        return reader.Read() ? ReadAlbum(reader) : null;
    }

    public List<Album> AlbumsByGenre(string genre)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = AlbumSelect + " WHERE g.Name = $genre ORDER BY a.AlbumId";
        command.Parameters.AddWithValue("$genre", genre);
        using var reader = command.ExecuteReader();
        var albums = new List<Album>();
        while (reader.Read())
        {
            albums.Add(ReadAlbum(reader));
        }

        return albums;
    }

    public List<Album> NewestAlbums(int take)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = AlbumSelect + " ORDER BY a.AlbumId LIMIT $take";
        command.Parameters.AddWithValue("$take", take);
        using var reader = command.ExecuteReader();
        var albums = new List<Album>();
        while (reader.Read())
        {
            albums.Add(ReadAlbum(reader));
        }

        return albums;
    }

    public List<CartLine> CartLines(string cartId)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText =
            "SELECT c.RecordId, c.AlbumId, a.Title, c.Count, a.Price " +
            "FROM Carts c JOIN Albums a ON a.AlbumId = c.AlbumId " +
            "WHERE c.CartId = $cartId ORDER BY c.RecordId";
        command.Parameters.AddWithValue("$cartId", cartId);
        using var reader = command.ExecuteReader();
        var lines = new List<CartLine>();
        while (reader.Read())
        {
            lines.Add(new CartLine
            {
                RecordId = reader.GetInt32(0),
                AlbumId = reader.GetInt32(1),
                Title = reader.GetString(2),
                Count = reader.GetInt32(3),
                Price = ParsePrice(reader.GetString(4)),
            });
        }

        return lines;
    }

    public static decimal Total(IEnumerable<CartLine> lines) => lines.Sum(l => l.Count * l.Price);

    public static int Count(IEnumerable<CartLine> lines) => lines.Sum(l => l.Count);

    /// <summary>
    /// 同じアルバムを 2 回入れると既存明細の数量が増える（新しい明細を足さない）。
    /// </summary>
    public bool AddToCart(string cartId, int albumId)
    {
        using var connection = Open();
        using (var exists = connection.CreateCommand())
        {
            exists.CommandText = "SELECT COUNT(*) FROM Albums WHERE AlbumId = $albumId";
            exists.Parameters.AddWithValue("$albumId", albumId);
            if (Convert.ToInt64(exists.ExecuteScalar(), CultureInfo.InvariantCulture) == 0)
            {
                return false;
            }
        }

        using (var update = connection.CreateCommand())
        {
            update.CommandText = "UPDATE Carts SET Count = Count + 1 WHERE CartId = $cartId AND AlbumId = $albumId";
            update.Parameters.AddWithValue("$cartId", cartId);
            update.Parameters.AddWithValue("$albumId", albumId);
            if (update.ExecuteNonQuery() > 0)
            {
                return true;
            }
        }

        using (var insert = connection.CreateCommand())
        {
            insert.CommandText =
                "INSERT INTO Carts (AlbumId, CartId, Count, DateCreated) VALUES ($albumId, $cartId, 1, $now)";
            insert.Parameters.AddWithValue("$albumId", albumId);
            insert.Parameters.AddWithValue("$cartId", cartId);
            insert.Parameters.AddWithValue("$now", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture));
            insert.ExecuteNonQuery();
        }

        return true;
    }

    /// <summary>
    /// 明細の数量を 1 減らし、0 になったら削除する。戻り値は削除後の数量（旧実装の
    /// 「減算前の数量を返す」癖は移行契約に含まれないため引き継がない）。
    /// </summary>
    public int RemoveFromCart(string cartId, int recordId)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT Count FROM Carts WHERE RecordId = $id AND CartId = $cartId";
        command.Parameters.AddWithValue("$id", recordId);
        command.Parameters.AddWithValue("$cartId", cartId);
        var value = command.ExecuteScalar();
        if (value == null || value == DBNull.Value)
        {
            return 0;
        }

        var count = Convert.ToInt32(value, CultureInfo.InvariantCulture);
        if (count > 1)
        {
            command.CommandText = "UPDATE Carts SET Count = Count - 1 WHERE RecordId = $id AND CartId = $cartId";
            command.ExecuteNonQuery();
            return count - 1;
        }

        command.CommandText = "DELETE FROM Carts WHERE RecordId = $id AND CartId = $cartId";
        command.ExecuteNonQuery();
        return 0;
    }

    public void EmptyCart(string cartId)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = "DELETE FROM Carts WHERE CartId = $cartId";
        command.Parameters.AddWithValue("$cartId", cartId);
        command.ExecuteNonQuery();
    }

    public int CreateOrder(string cartId, IDictionary<string, string> fields)
    {
        using var connection = Open();
        var lines = CartLines(connection, cartId);
        var total = Total(lines);

        using (var command = connection.CreateCommand())
        {
            command.CommandText =
                "INSERT INTO Orders (OrderDate, Username, FirstName, LastName, Address, City, State, PostalCode, Country, Phone, Email, Total) " +
                "VALUES ($date, $user, $first, $last, $address, $city, $state, $postal, $country, $phone, $email, $total)";
            command.Parameters.AddWithValue("$date", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture));
            command.Parameters.AddWithValue("$user", cartId);
            command.Parameters.AddWithValue("$first", Field(fields, "FirstName"));
            command.Parameters.AddWithValue("$last", Field(fields, "LastName"));
            command.Parameters.AddWithValue("$address", Field(fields, "Address"));
            command.Parameters.AddWithValue("$city", Field(fields, "City"));
            command.Parameters.AddWithValue("$state", Field(fields, "State"));
            command.Parameters.AddWithValue("$postal", Field(fields, "PostalCode"));
            command.Parameters.AddWithValue("$country", Field(fields, "Country"));
            command.Parameters.AddWithValue("$phone", Field(fields, "Phone"));
            command.Parameters.AddWithValue("$email", Field(fields, "Email"));
            command.Parameters.AddWithValue("$total", Money(total));
            command.ExecuteNonQuery();
        }

        var orderId = (int)Scalar(connection, "SELECT last_insert_rowid()");

        using (var command = connection.CreateCommand())
        {
            command.CommandText =
                "INSERT INTO OrderDetails (OrderId, AlbumId, Quantity, UnitPrice) VALUES ($orderId, $albumId, $quantity, $unitPrice)";
            foreach (var line in lines)
            {
                command.Parameters.Clear();
                command.Parameters.AddWithValue("$orderId", orderId);
                command.Parameters.AddWithValue("$albumId", line.AlbumId);
                command.Parameters.AddWithValue("$quantity", line.Count);
                command.Parameters.AddWithValue("$unitPrice", Money(line.Price));
                command.ExecuteNonQuery();
            }
        }

        EmptyCart(cartId);
        return orderId;
    }

    public bool OwnsOrder(string cartId, int orderId)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT COUNT(*) FROM Orders WHERE OrderId = $id AND Username = $cartId";
        command.Parameters.AddWithValue("$id", orderId);
        command.Parameters.AddWithValue("$cartId", cartId);
        return Convert.ToInt32(command.ExecuteScalar(), CultureInfo.InvariantCulture) > 0;
    }

    public static string Money(decimal value) => value.ToString("0.00", CultureInfo.InvariantCulture);

    private static decimal ParsePrice(string text) =>
        decimal.Parse(text, NumberStyles.Number, CultureInfo.InvariantCulture);

    private static string Field(IDictionary<string, string> fields, string name) =>
        fields.TryGetValue(name, out var value) ? (value ?? string.Empty) : string.Empty;

    private const string AlbumSelect =
        "SELECT a.AlbumId, a.Title, a.GenreId, g.Name, ar.Name, a.Price " +
        "FROM Albums a JOIN Genres g ON g.GenreId = a.GenreId JOIN Artists ar ON ar.ArtistId = a.ArtistId";

    private static Album ReadAlbum(SqliteDataReader reader) => new Album
    {
        AlbumId = reader.GetInt32(0),
        Title = reader.GetString(1),
        GenreId = reader.GetInt32(2),
        Genre = reader.GetString(3),
        Artist = reader.GetString(4),
        Price = ParsePrice(reader.GetString(5)),
    };

    private SqliteConnection Open()
    {
        var connection = new SqliteConnection(connectionString);
        connection.Open();
        using var pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 10000;";
        pragma.ExecuteNonQuery();
        return connection;
    }

    private static List<CartLine> CartLines(SqliteConnection connection, string cartId)
    {
        using var command = connection.CreateCommand();
        command.CommandText =
            "SELECT c.RecordId, c.AlbumId, a.Title, c.Count, a.Price " +
            "FROM Carts c JOIN Albums a ON a.AlbumId = c.AlbumId " +
            "WHERE c.CartId = $cartId ORDER BY c.RecordId";
        command.Parameters.AddWithValue("$cartId", cartId);
        using var reader = command.ExecuteReader();
        var lines = new List<CartLine>();
        while (reader.Read())
        {
            lines.Add(new CartLine
            {
                RecordId = reader.GetInt32(0),
                AlbumId = reader.GetInt32(1),
                Title = reader.GetString(2),
                Count = reader.GetInt32(3),
                Price = ParsePrice(reader.GetString(4)),
            });
        }

        return lines;
    }

    private static void Execute(SqliteConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }

    private static long Scalar(SqliteConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        var value = command.ExecuteScalar();
        return value == null || value == DBNull.Value ? 0L : Convert.ToInt64(value, CultureInfo.InvariantCulture);
    }

    private void Seed(SqliteConnection connection)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(catalogPath));
        var root = document.RootElement;

        var genreIds = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var genre in root.GetProperty("genres").EnumerateArray())
        {
            var name = genre.GetString();
            using var command = connection.CreateCommand();
            command.CommandText = "INSERT INTO Genres (Name, Description) VALUES ($name, $name)";
            command.Parameters.AddWithValue("$name", name);
            command.ExecuteNonQuery();
            genreIds[name] = (int)Scalar(connection, "SELECT last_insert_rowid()");
        }

        var artistIds = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var artist in root.GetProperty("artists").EnumerateArray())
        {
            var name = artist.GetString();
            if (artistIds.ContainsKey(name))
            {
                continue;
            }

            using var command = connection.CreateCommand();
            command.CommandText = "INSERT INTO Artists (Name) VALUES ($name)";
            command.Parameters.AddWithValue("$name", name);
            command.ExecuteNonQuery();
            artistIds[name] = (int)Scalar(connection, "SELECT last_insert_rowid()");
        }

        foreach (var album in root.GetProperty("albums").EnumerateArray())
        {
            using var command = connection.CreateCommand();
            command.CommandText =
                "INSERT INTO Albums (Title, GenreId, ArtistId, Price, AlbumArtUrl) VALUES ($title, $genreId, $artistId, $price, $art)";
            command.Parameters.AddWithValue("$title", album.GetProperty("title").GetString());
            command.Parameters.AddWithValue("$genreId", genreIds[album.GetProperty("genre").GetString()]);
            command.Parameters.AddWithValue("$artistId", artistIds[album.GetProperty("artist").GetString()]);
            command.Parameters.AddWithValue("$price", Money(album.GetProperty("price").GetDecimal()));
            command.Parameters.AddWithValue("$art", album.GetProperty("albumArtUrl").GetString() ?? string.Empty);
            command.ExecuteNonQuery();
        }
    }

    private const string Schema = @"
CREATE TABLE IF NOT EXISTS Genres (
    GenreId INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL,
    Description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS Artists (
    ArtistId INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS Albums (
    AlbumId INTEGER PRIMARY KEY AUTOINCREMENT,
    Title TEXT NOT NULL,
    GenreId INTEGER NOT NULL REFERENCES Genres(GenreId),
    ArtistId INTEGER NOT NULL REFERENCES Artists(ArtistId),
    Price TEXT NOT NULL,
    AlbumArtUrl TEXT
);
CREATE TABLE IF NOT EXISTS Carts (
    RecordId INTEGER PRIMARY KEY AUTOINCREMENT,
    AlbumId INTEGER NOT NULL REFERENCES Albums(AlbumId),
    CartId TEXT NOT NULL,
    Count INTEGER NOT NULL,
    DateCreated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS Orders (
    OrderId INTEGER PRIMARY KEY AUTOINCREMENT,
    OrderDate TEXT,
    Username TEXT,
    FirstName TEXT,
    LastName TEXT,
    Address TEXT,
    City TEXT,
    State TEXT,
    PostalCode TEXT,
    Country TEXT,
    Phone TEXT,
    Email TEXT,
    Total TEXT
);
CREATE TABLE IF NOT EXISTS OrderDetails (
    OrderDetailId INTEGER PRIMARY KEY AUTOINCREMENT,
    OrderId INTEGER NOT NULL REFERENCES Orders(OrderId),
    AlbumId INTEGER NOT NULL REFERENCES Albums(AlbumId),
    Quantity INTEGER NOT NULL,
    UnitPrice TEXT NOT NULL
);
";
}
