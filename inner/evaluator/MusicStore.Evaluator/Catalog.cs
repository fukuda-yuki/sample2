using System.Text.Json;

namespace MusicStore.Evaluator;

public sealed class CatalogAlbum
{
    public int AlbumId { get; set; }

    public string Title { get; set; }

    public string Genre { get; set; }

    public string Artist { get; set; }

    public decimal Price { get; set; }

    public string AlbumArtUrl { get; set; }
}

/// <summary>
/// 旧実装の SampleData.cs から抽出した初期カタログ。期待値の唯一のデータ源であり、
/// 旧実装のコードから独立に確認した事実（docs/quality-spec.md §3.1）である。
/// </summary>
public sealed class Catalog
{
    public List<string> Genres { get; set; } = new List<string>();

    public List<string> Artists { get; set; } = new List<string>();

    public List<CatalogAlbum> Albums { get; set; } = new List<CatalogAlbum>();

    private static readonly JsonSerializerOptions ReadOptions = new JsonSerializerOptions
    {
        PropertyNameCaseInsensitive = true,
    };

    public static Catalog Load(string path)
    {
        var catalog = JsonSerializer.Deserialize<Catalog>(File.ReadAllText(path), ReadOptions);
        if (catalog == null || catalog.Albums.Count == 0)
        {
            throw new InvalidOperationException($"初期カタログを読み込めません: {path}");
        }

        return catalog;
    }

    public int CountByGenre(string genre) => Albums.Count(a => a.Genre == genre);

    public CatalogAlbum ById(int albumId) => Albums.FirstOrDefault(a => a.AlbumId == albumId);

    public string GenreCountsText() =>
        string.Join(", ", Genres.Select(g => $"{g}={CountByGenre(g)}"));
}
