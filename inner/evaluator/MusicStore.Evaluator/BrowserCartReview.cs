using System.Text.Json;
using AngleSharp.Html.Parser;

namespace MusicStore.Evaluator;

/// <summary>
/// Optional, independently collected browser observations for C-015/C-016.
/// This consumes real post-click DOM captures, not a later GET or JSON totals.
/// The collector/agent is trusted for action attribution; hashes establish byte
/// identity, not authenticity. Missing input must never imply browser coverage.
/// </summary>
public sealed class BrowserCartReview
{
    public sealed record Result(bool Pass, string Detail);
    public sealed class FileReference
    {
        public string Path { get; set; }
        public string Sha256 { get; set; }
    }
    public sealed class Removal
    {
        public string CheckId { get; set; }
        public string Action { get; set; }
        public FileReference Before { get; set; }
        public FileReference After { get; set; }
        public FileReference BeforeScreenshot { get; set; }
        public FileReference AfterScreenshot { get; set; }
    }
    public sealed class Receipt
    {
        public int SchemaVersion { get; set; }
        public string Actor { get; set; }
        public string RunInstanceId { get; set; }
        public string ArtifactSha256 { get; set; }
        public string SpecSha256 { get; set; }
        public List<Removal> Removals { get; set; }
    }

    private readonly Dictionary<string, Result> results = new();
    public string ReceiptSha256 { get; private set; }
    public string RunInstanceId { get; private set; }
    public Result For(string checkId) => results[checkId];

    public static BrowserCartReview Load(string path, string artifactHash, string specHash,
        string runInstanceId, Catalog catalog)
    {
        var receipt = JsonSerializer.Deserialize<Receipt>(File.ReadAllText(path),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        if (receipt?.SchemaVersion != 1 || receipt.Actor != "agent"
            || string.IsNullOrWhiteSpace(runInstanceId) || receipt.RunInstanceId != runInstanceId
            || receipt.ArtifactSha256 != artifactHash || receipt.SpecSha256 != specHash
            || receipt.Removals == null || receipt.Removals.Count != 2
            || !receipt.Removals.Select(r => r.CheckId).Order().SequenceEqual(new[] { "C-015", "C-016" }))
            throw new InvalidDataException("Browser review identity or check set mismatch.");

        var review = new BrowserCartReview
        {
            ReceiptSha256 = Program.Sha256File(path),
            RunInstanceId = runInstanceId,
        };
        var root = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(path));
        foreach (var removal in receipt.Removals)
        {
            if (removal.Action != "click-remove")
                throw new InvalidDataException("Browser removal must be an observed UI click.");
            using var before = JsonDocument.Parse(ReadVerified(root, removal.Before));
            using var after = JsonDocument.Parse(ReadVerified(root, removal.After));
            ReadVerified(root, removal.BeforeScreenshot);
            ReadVerified(root, removal.AfterScreenshot);
            var b = before.RootElement;
            var a = after.RootElement;
            var beforeUrl = new Uri(b.GetProperty("page").GetProperty("url").GetString());
            var afterUrl = new Uri(a.GetProperty("page").GetProperty("url").GetString());
            if (string.IsNullOrWhiteSpace(b.GetProperty("tabId").GetString())
                || b.GetProperty("tabId").GetString() != a.GetProperty("tabId").GetString()
                || beforeUrl.GetLeftPart(UriPartial.Authority) != afterUrl.GetLeftPart(UriPartial.Authority)
                || beforeUrl.AbsolutePath.TrimEnd('/') != "/ShoppingCart"
                || b.GetProperty("at").GetDateTimeOffset() >= a.GetProperty("at").GetDateTimeOffset())
                throw new InvalidDataException("Browser before/after session, route or time mismatch.");
            var beforeHtml = ObservedHtml(b);
            var afterHtml = ObservedHtml(a);
            var lines = Html.CartLines(beforeHtml);
            var countBefore = removal.CheckId == "C-015" ? 2 : 1;
            var album = lines.Count == 1 ? catalog.ById(lines[0].AlbumId) : null;
            if (album == null || lines[0].Count != countBefore
                || !WellFormedCart(beforeHtml) || Html.Money(beforeHtml) != countBefore * album.Price)
                throw new InvalidDataException("Browser removal lacks its populated precondition.");

            var remaining = Html.CartLines(afterHtml);
            var countAfter = countBefore - 1;
            var linesOk = countAfter == 0 ? remaining.Count == 0
                : remaining.Count == 1 && remaining[0].AlbumId == album.AlbumId && remaining[0].Count == 1;
            var total = Html.Money(afterHtml);
            var pass = WellFormedCart(afterHtml) && linesOk && total == countAfter * album.Price;
            review.results[removal.CheckId] = new Result(pass,
                $"Agent browser click: {Scenarios.DescribeCart(remaining)}, displayed total {Scenarios.DescribeMoney(total)}; "
                + $"expected quantity {countAfter}, total {Html.Money2(countAfter * album.Price)}. "
                + $"Before={removal.Before.Path}; after={removal.After.Path}; receipt SHA-256={review.ReceiptSha256}.");
        }
        return review;
    }

    private static string ObservedHtml(JsonElement capture)
    {
        var page = capture.GetProperty("page");
        return (page.TryGetProperty("visibleCartHtml", out var visible) ? visible : page.GetProperty("html")).GetString();
    }

    private static bool WellFormedCart(string html)
    {
        var document = new HtmlParser().ParseDocument(html ?? "");
        var rows = document.QuerySelectorAll("tr[id^='row-']");
        return document.QuerySelectorAll("[id='cart-total']").Length == 1
            && rows.Length == Html.CartLines(html).Count
            && rows.Select(r => r.Id).Distinct().Count() == rows.Length;
    }

    private static byte[] ReadVerified(string root, FileReference reference)
    {
        if (reference == null || string.IsNullOrWhiteSpace(reference.Path)
            || System.IO.Path.IsPathRooted(reference.Path)
            || reference.Path.Replace('\\', '/').Split('/').Contains(".."))
            throw new InvalidDataException("Invalid browser evidence path.");
        var path = System.IO.Path.GetFullPath(System.IO.Path.Combine(root, reference.Path));
        if (!path.StartsWith(root + System.IO.Path.DirectorySeparatorChar, StringComparison.Ordinal)
            || Program.Sha256File(path) != reference.Sha256)
            throw new InvalidDataException("Browser evidence hash mismatch: " + reference.Path);
        return File.ReadAllBytes(path);
    }
}
