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
    private static AngleSharp.Dom.IDocument Document(string html)
    {
        var doc = new AngleSharp.Html.Parser.HtmlParser().ParseDocument(html ?? string.Empty);
        foreach (var node in doc.QuerySelectorAll("script,style,template")) node.Remove();
        return doc;
    }

    private static int? Number(string value) => int.TryParse(value, NumberStyles.None,
        CultureInfo.InvariantCulture, out var number) ? number : null;

    private static int? Album(AngleSharp.Dom.IElement link)
    {
        var href = link?.GetAttribute("href");
        if (href == null || !Uri.TryCreate(new Uri("http://localhost"), href, out var uri)) return null;
        var match = Regex.Match(uri.AbsolutePath, @"^/Store/Details/(?<id>[0-9]+)$", RegexOptions.IgnoreCase);
        return match.Success ? Number(match.Groups["id"].Value) : null;
    }

    public static int? OrderNumber(string html)
    {
        var match = Regex.Match(Text(html), @"order number is:\s*(?<id>[0-9]+)", RegexOptions.IgnoreCase);
        return match.Success ? Number(match.Groups["id"].Value) : null;
    }

    public static int? MarkedOrderNumber(string html)
    {
        var nodes = Document(html).QuerySelectorAll("[id='order-number']");
        return nodes.Length == 1 ? Number(nodes[0].TextContent.Trim()) : null;
    }

    public static bool HasOrderMarker(string html) => Document(html).QuerySelector("[id='order-number']") != null;

    public static bool HasCheckoutForm(string html) => Document(html).QuerySelectorAll("form input")
        .Any(e => string.Equals(e.GetAttribute("name"), "PromoCode", StringComparison.OrdinalIgnoreCase));

    public static bool SameCart(string before, string after)
    {
        var a = CartLines(before).Select(x => (x.AlbumId, x.Count)).OrderBy(x => x).ToArray();
        var b = CartLines(after).Select(x => (x.AlbumId, x.Count)).OrderBy(x => x).ToArray();
        var total = Money(before);
        return a.Length > 0 && a.SequenceEqual(b) && total.HasValue && total == Money(after);
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
        foreach (var row in Document(html).QuerySelectorAll("tr[id^='row-']"))
        {
            var record = Number(row.Id.Substring(4));
            var album = row.QuerySelectorAll("a[href]").Select(Album).FirstOrDefault(x => x.HasValue);
            var count = record.HasValue ? Number(row.QuerySelector($"[id='item-count-{record}']")?.TextContent.Trim()) : null;
            if (record.HasValue && album.HasValue && count.HasValue)
                lines.Add(new CartLine { RecordId = record.Value, AlbumId = album.Value, Count = count.Value });
        }
        return lines;
    }

    public static List<int> AlbumIds(string html) => Document(html).QuerySelectorAll("a[href]")
        .Select(Album).Where(x => x.HasValue).Select(x => x.Value).ToList();

    public static int? CartCount(string html)
    {
        var text = Document(html).GetElementById("cart-status")?.TextContent ?? string.Empty;
        var match = Regex.Match(text, @"\((?<n>\d+)\)");
        return match.Success ? Number(match.Groups["n"].Value) : null;
    }

    public static decimal? Money(string html) => ParseMoney(Document(html).GetElementById("cart-total")?.TextContent);
    public static decimal? ParseMoney(string text)
    {
        if (string.IsNullOrWhiteSpace(text)) return null;
        return decimal.TryParse(text.Trim().Replace(",", string.Empty), NumberStyles.Number,
            CultureInfo.InvariantCulture, out var value) ? value : null;
    }
    public static string Money2(decimal value) => value.ToString("0.00", CultureInfo.InvariantCulture);
    public static string Text(string html) => Document(html).Body?.TextContent ?? string.Empty;
    public static bool Contains(string html, string needle) => Text(html).Contains(needle, StringComparison.OrdinalIgnoreCase)
        || Document(html).QuerySelectorAll("input").Any(e => e.GetAttribute("name") == needle);
}
