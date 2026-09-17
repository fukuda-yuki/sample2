using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;

namespace MusicStore.Evaluator;

public sealed class WebResponse
{
    public string Method { get; set; }

    public string Url { get; set; }

    public int Status { get; set; }

    public string Location { get; set; }

    public string Body { get; set; }

    public string RequestBody { get; set; }

    public string Summary() =>
        $"{Method} {Url} -> {Status}" + (string.IsNullOrEmpty(Location) ? string.Empty : $" (Location: {Location})");
}

/// <summary>
/// クッキーコンテナを分けた独立した HTTP セッション。リダイレクトは追跡せず、
/// 302 と Location をそのまま観測する。
/// </summary>
public sealed class WebSession : IDisposable
{
    private readonly HttpClient client;
    private readonly List<WebResponse> transcript = new List<WebResponse>();

    public WebSession(string baseUrl)
    {
        BaseUrl = baseUrl;
        var handler = new HttpClientHandler
        {
            CookieContainer = new CookieContainer(),
            UseCookies = true,
            AllowAutoRedirect = false,
        };
        client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(30) };
    }

    public string BaseUrl { get; }

    public IReadOnlyList<WebResponse> Transcript => transcript;

    public WebResponse Get(string path)
    {
        var url = BaseUrl + path;
        using var response = client.GetAsync(url).GetAwaiter().GetResult();
        var result = new WebResponse
        {
            Method = "GET",
            Url = path,
            Status = (int)response.StatusCode,
            Location = response.Headers.Location?.ToString(),
            Body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult(),
        };
        transcript.Add(result);
        return result;
    }

    public WebResponse PostForm(string path, IEnumerable<KeyValuePair<string, string>> fields)
    {
        var list = fields.ToList();
        var url = BaseUrl + path;
        using var content = new FormUrlEncodedContent(list);
        using var response = client.PostAsync(url, content).GetAwaiter().GetResult();
        var result = new WebResponse
        {
            Method = "POST",
            Url = path,
            Status = (int)response.StatusCode,
            Location = response.Headers.Location?.ToString(),
            Body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult(),
            RequestBody = string.Join("&", list.Select(f => f.Key + "=" + f.Value)),
        };
        transcript.Add(result);
        return result;
    }

    public string Dump()
    {
        var builder = new StringBuilder();
        foreach (var entry in transcript)
        {
            builder.AppendLine("---- " + entry.Summary());
            if (!string.IsNullOrEmpty(entry.RequestBody))
            {
                builder.AppendLine("  form: " + entry.RequestBody);
            }

            var body = entry.Body ?? string.Empty;
            builder.AppendLine("  body[" + body.Length + "]: " + AppHost.Tail(body, 1500));
        }

        return builder.ToString();
    }

    public void Dispose() => client.Dispose();
}

public static class Html
{
    // 属性値の引用符は " と ' のどちらも等価な HTML である（docs/quality-spec.md §4.6）。
    // 契約は識別子と値であり、引用符の種類は判定に影響させない。
    public static readonly Regex CartRowRegex = new Regex(
        "<tr[^>]*id=[\"']row-(?<recordId>\\d+)[\"'][^>]*>(?<inner>.*?)</tr>",
        RegexOptions.Singleline | RegexOptions.IgnoreCase);

    public static readonly Regex AlbumLinkRegex = new Regex(
        "href=[\"'](?:[^\"']*?)?/Store/Details/(?<albumId>\\d+)[\"']",
        RegexOptions.IgnoreCase);

    public static readonly Regex ItemCountRegex = new Regex(
        "id=[\"']item-count-(?<recordId>\\d+)[\"'][^>]*>\\s*(?<count>\\d+)\\s*<",
        RegexOptions.IgnoreCase);

    public static readonly Regex CartTotalRegex = new Regex(
        "id=[\"']cart-total[\"'][^>]*>\\s*(?<total>-?[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*<",
        RegexOptions.IgnoreCase);

    public static readonly Regex CartStatusRegex = new Regex(
        "id=[\"']cart-status[\"'][^>]*>(?<text>[^<]*)<",
        RegexOptions.IgnoreCase);

    public static readonly Regex OrderNumberRegex = new Regex(
        "order number is:\\s*(?<id>[0-9]+)",
        RegexOptions.IgnoreCase);

    /// <summary>
    /// 完了画面が示す注文番号。旧 Views/Checkout/Complete.cshtml の文言
    /// 「Your order number is: @Model」を外部契約として維持する。
    /// </summary>
    public static int? OrderNumber(string html)
    {
        var match = OrderNumberRegex.Match(Text(html));
        return match.Success ? int.Parse(match.Groups["id"].Value, CultureInfo.InvariantCulture) : (int?)null;
    }

    public sealed class CartLine
    {
        public int RecordId { get; set; }

        public int AlbumId { get; set; }

        public int Count { get; set; }
    }

    public static List<CartLine> CartLines(string html)
    {
        var lines = new List<CartLine>();
        foreach (Match match in CartRowRegex.Matches(html ?? string.Empty))
        {
            var inner = match.Groups["inner"].Value;
            var album = AlbumLinkRegex.Match(inner);
            var count = ItemCountRegex.Match(inner);
            if (!album.Success || !count.Success)
            {
                continue;
            }

            lines.Add(new CartLine
            {
                RecordId = int.Parse(match.Groups["recordId"].Value, CultureInfo.InvariantCulture),
                AlbumId = int.Parse(album.Groups["albumId"].Value, CultureInfo.InvariantCulture),
                Count = int.Parse(count.Groups["count"].Value, CultureInfo.InvariantCulture),
            });
        }

        return lines;
    }

    public static List<int> AlbumIds(string html) =>
        AlbumLinkRegex.Matches(html ?? string.Empty)
            .Select(m => int.Parse(m.Groups["albumId"].Value, CultureInfo.InvariantCulture))
            .ToList();

    public static int? CartCount(string html)
    {
        var match = CartStatusRegex.Match(html ?? string.Empty);
        if (!match.Success)
        {
            return null;
        }

        var digits = Regex.Match(match.Groups["text"].Value, "\\((?<n>\\d+)\\)");
        return digits.Success ? int.Parse(digits.Groups["n"].Value, CultureInfo.InvariantCulture) : (int?)null;
    }

    public static decimal? Money(string html)
    {
        var match = CartTotalRegex.Match(html ?? string.Empty);
        if (!match.Success)
        {
            return null;
        }

        return ParseMoney(match.Groups["total"].Value);
    }

    public static decimal? ParseMoney(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        var normalized = text.Trim().Replace(",", string.Empty);
        return decimal.TryParse(normalized, NumberStyles.Number, CultureInfo.InvariantCulture, out var value) ? value : (decimal?)null;
    }

    public static string Money2(decimal value) => value.ToString("0.00", CultureInfo.InvariantCulture);

    public static string Text(string html) =>
        WebUtility.HtmlDecode(Regex.Replace(html ?? string.Empty, "<[^>]*>", " "));

    public static bool Contains(string html, string needle) =>
        (html ?? string.Empty).Contains(needle, StringComparison.OrdinalIgnoreCase);
}
