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
    public sealed record Result(bool Pass, string Detail, bool Complete = true, string Status = "observed");
    public sealed class FileReference
    {
        public string Path { get; set; }
        public string Sha256 { get; set; }
    }
    public sealed class Removal
    {
        public string CheckId { get; set; }
        public string Action { get; set; }
        public string Reason { get; set; }
        public int AddCount { get; set; }
        public FileReference SetupBefore { get; set; }
        public FileReference SetupScreenshot { get; set; }
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
        public List<string> Faults { get; set; } = new();
        public string BaseUrl { get; set; }
        public string RequestSha256 { get; set; }
        public List<ProductHttpFailure> ProductFailures { get; set; } = new();
    }

    public sealed class ProductHttpFailure
    {
        public string CaseId { get; set; }
        public string CheckId { get; set; }
        public string Operation { get; set; }
        public string Method { get; set; }
        public string Url { get; set; }
        public int Status { get; set; }
        public bool ClickConfirmed { get; set; }
        public FileReference Evidence { get; set; }
    }

    private readonly Dictionary<string, Result> results = new();
    public Dictionary<string, string> ProductFailures { get; } = new();
    public List<string> Faults { get; } = new();
    public bool Complete => results.Values.All(r => r.Complete) && Faults.Count == 0;
    public Dictionary<string, string> Cases => results.ToDictionary(r => r.Key, r => r.Value.Status);
    public string Coverage => !Complete ? "partial" : results.Values.All(r => r.Status == "observed")
        ? "agent_observed_C-015_C-016" : "agent_assessed_C-015_C-016";
    public string ReceiptSha256 { get; private set; }
    public string RunInstanceId { get; private set; }
    public Result For(string checkId) => results[checkId];

    public static BrowserCartReview Load(string path, string artifactHash, string specHash,
        string runInstanceId, Catalog catalog, bool requireCartStatus = false,
        bool structuralPrecondition = false, bool productHttpContract = false)
    {
        var receipt = JsonSerializer.Deserialize<Receipt>(File.ReadAllText(path),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        if (receipt == null || receipt.SchemaVersion is not (1 or 2 or 3) || receipt.Actor != "agent"
            || string.IsNullOrWhiteSpace(runInstanceId) || receipt.RunInstanceId != runInstanceId
            || receipt.ArtifactSha256 != artifactHash || receipt.SpecSha256 != specHash
            || receipt.Removals == null || receipt.Removals.Count > 2
            || receipt.Removals.Any(r => r.CheckId is not ("C-015" or "C-016"))
            || receipt.Removals.Select(r => r.CheckId).Distinct().Count() != receipt.Removals.Count
            || receipt.SchemaVersion == 1 && receipt.Removals.Count != 2
            || receipt.SchemaVersion == 3 && !productHttpContract
            || productHttpContract && receipt.SchemaVersion != 3
            || receipt.SchemaVersion != 3 && receipt.ProductFailures?.Count > 0)
            throw new InvalidDataException("Browser review identity or check set mismatch.");

        var review = new BrowserCartReview
        {
            ReceiptSha256 = Program.Sha256File(path),
            RunInstanceId = runInstanceId,
        };
        review.Faults.AddRange(receipt.Faults ?? new());
        foreach (var id in new[] { "C-015", "C-016" })
            review.results[id] = new Result(false, "Browser case not performed.", false, "not_run");
        var root = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(path));
        if (receipt.SchemaVersion == 3) ReadProductFailures(review, receipt, root, artifactHash, specHash, runInstanceId);
        foreach (var removal in receipt.Removals)
        {
            try
            {
                if (removal.Action != "click-remove" && (receipt.SchemaVersion < 2
                    || removal.Action is not ("observe-unavailable" or "not-run-precondition" or "not-run-unsupported")
                    || string.IsNullOrWhiteSpace(removal.Reason)))
                    throw new InvalidDataException("Unrecognized browser action or missing reason.");
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
                    || receipt.SchemaVersion == 3 && beforeUrl.GetLeftPart(UriPartial.Authority) != new Uri(receipt.BaseUrl).GetLeftPart(UriPartial.Authority)
                    || beforeUrl.AbsolutePath.TrimEnd('/') != "/ShoppingCart"
                    || b.GetProperty("at").GetDateTimeOffset() >= a.GetProperty("at").GetDateTimeOffset())
                    throw new InvalidDataException("Browser before/after session, route or time mismatch.");
                var beforeHtml = ObservedHtml(b);
                var afterHtml = ObservedHtml(a);
                var lines = Html.CartLines(beforeHtml);
                var countBefore = removal.CheckId == "C-015" ? 2 : 1;
                var album = lines.Count == 1 ? catalog.ById(lines[0].AlbumId) : null;
                if (removal.Action == "not-run-precondition")
                {
                    using var setup = JsonDocument.Parse(ReadVerified(root, removal.SetupBefore));
                    ReadVerified(root, removal.SetupScreenshot);
                    var s = setup.RootElement;
                    if (s.GetProperty("tabId").GetString() != b.GetProperty("tabId").GetString()
                        || s.GetProperty("page").GetProperty("url").GetString() != beforeUrl.ToString()
                        || s.GetProperty("at").GetDateTimeOffset() > b.GetProperty("at").GetDateTimeOffset())
                        throw new InvalidDataException("Browser setup identity mismatch.");
                    var empty = ObservedHtml(s);
                    if (removal.Reason == "quantity_after_two_adds")
                    {
                        if (removal.CheckId != "C-015" || removal.AddCount != 2 || !WellFormedCart(empty)
                            || Html.CartLines(empty).Count != 0 || Html.Money(empty) != 0
                            || !WellFormedCart(beforeHtml) || album?.AlbumId != 1 || lines[0].Count == 2)
                            throw new InvalidDataException("Quantity violation is not established by setup evidence.");
                        review.ProductFailures["C-013"] = "Browser: two public additions from an empty cart yielded "
                            + Scenarios.DescribeCart(lines) + "; removal itself was not performed.";
                    }
                    review.results[removal.CheckId] = new Result(false,
                        "Removal not performed: " + removal.Reason + "; evidence=" + removal.Before.Path, false, "not_run_precondition");
                    continue;
                }
                if (album == null || lines[0].Count != countBefore
                    || !WellFormedCart(beforeHtml) || !Html.Money(beforeHtml).HasValue
                    || !structuralPrecondition && Html.Money(beforeHtml) != countBefore * album.Price)
                    throw new InvalidDataException("Browser removal lacks its populated precondition.");

                if (removal.Action == "not-run-unsupported")
                {
                    review.results[removal.CheckId] = new Result(false,
                        "Removal not confirmed: " + removal.Reason + "; evidence=" + removal.Before.Path, false, "unsupported");
                    continue;
                }
                if (removal.Action == "observe-unavailable")
                {
                    if (removal.Reason is not ("control_absent" or "control_disabled"))
                        throw new InvalidDataException("Unrecognized product actionability observation.");
                    review.results[removal.CheckId] = new Result(false,
                        "Removal unavailable: " + removal.Reason + "; no click performed; DOM=" + removal.Before.Path
                        + "; screenshot=" + removal.BeforeScreenshot.Path, true, "unavailable");
                    continue;
                }

                var remaining = Html.CartLines(afterHtml);
                var countAfter = countBefore - 1;
                var linesOk = countAfter == 0 ? remaining.Count == 0
                    : remaining.Count == 1 && remaining[0].AlbumId == album.AlbumId && remaining[0].Count == 1;
                var total = Html.Money(afterHtml);
                var status = new HtmlParser().ParseDocument(afterHtml).QuerySelectorAll("[id='cart-status']");
                var statusOk = !requireCartStatus || status.Length == 1
                    && status[0].TextContent.Trim() == $"Cart ({countAfter})";
                var pass = WellFormedCart(afterHtml) && linesOk && total == countAfter * album.Price && statusOk;
                review.results[removal.CheckId] = new Result(pass,
                    $"Agent browser click: {Scenarios.DescribeCart(remaining)}, displayed total {Scenarios.DescribeMoney(total)}; "
                    + $"expected quantity {countAfter}, total {Html.Money2(countAfter * album.Price)}, cart summary match {statusOk}. "
                    + $"Before={removal.Before.Path}; after={removal.After.Path}; receipt SHA-256={review.ReceiptSha256}.");
            }
            catch (Exception ex) when (receipt.SchemaVersion == 3)
            {
                // An invalid DOM observation cannot erase an independently bound
                // application response. Keep this case unknown and record the fault.
                review.Faults.Add("Browser case " + removal.CheckId + ": " + ex.Message);
                review.results[removal.CheckId] = new Result(false, "Browser observation invalid.", false, "observer_fault");
            }
        }
        return review;
    }

    private static void ReadProductFailures(BrowserCartReview review, Receipt receipt, string root,
        string artifactHash, string specHash, string runInstanceId)
    {
        // A status seen at an allowlisted owned application endpoint is a finite
        // product fact. It does not imply that a later DOM observation completed.
        if (!Uri.TryCreate(receipt.BaseUrl, UriKind.Absolute, out var origin)
            || origin.Scheme != "http" || !origin.IsLoopback || origin.IsDefaultPort || origin.UserInfo.Length != 0
            || origin.AbsolutePath != "/" || origin.Query.Length != 0 || origin.Fragment.Length != 0)
            throw new InvalidDataException("Invalid owned application origin.");
        using var request = JsonDocument.Parse(ReadVerified(root, new FileReference { Path = "request.json", Sha256 = receipt.RequestSha256 }));
        var rq = request.RootElement;
        if (rq.GetProperty("artifactSha256").GetString() != artifactHash
            || rq.GetProperty("specSha256").GetString() != specHash
            || rq.GetProperty("runInstanceId").GetString() != runInstanceId
            || rq.GetProperty("baseUrl").GetString() != receipt.BaseUrl
            || rq.GetProperty("evaluationVersion").GetString() != "1.4.0")
            throw new InvalidDataException("Browser observation request binding mismatch.");
        var identities = new HashSet<string>(StringComparer.Ordinal);
        foreach (var failure in receipt.ProductFailures ?? new())
        {
            try
            {
                if (string.IsNullOrWhiteSpace(failure.CaseId) || !identities.Add(failure.CaseId)
                    || failure.Status < 500 || failure.Status > 599
                    || !Uri.TryCreate(failure.Url, UriKind.Absolute, out var url)
                    || url.GetLeftPart(UriPartial.Authority) != origin.GetLeftPart(UriPartial.Authority)
                    || url.UserInfo.Length != 0 || url.Query.Length != 0 || url.Fragment.Length != 0)
                    throw new InvalidDataException("Product response identity or status mismatch.");
                var add = failure.Operation == "cart-add" && failure.CheckId == "C-012"
                    && failure.Method == "GET" && !failure.ClickConfirmed
                    && System.Text.RegularExpressions.Regex.IsMatch(url.AbsolutePath, @"^/ShoppingCart/AddToCart/[1-9][0-9]*$");
                var remove = failure.Operation == "cart-remove" && failure.CheckId is "C-015" or "C-016"
                    && failure.Method == "POST" && failure.ClickConfirmed && url.AbsolutePath == "/ShoppingCart/RemoveFromCart";
                if (!add && !remove) throw new InvalidDataException("Product response has no corresponding requirement oracle.");
                using var evidence = JsonDocument.Parse(ReadVerified(root, failure.Evidence));
                var e = evidence.RootElement;
                if (e.GetProperty("caseId").GetString() != failure.CaseId || e.GetProperty("checkId").GetString() != failure.CheckId
                    || e.GetProperty("operation").GetString() != failure.Operation || e.GetProperty("method").GetString() != failure.Method
                    || e.GetProperty("url").GetString() != failure.Url || e.GetProperty("status").GetInt32() != failure.Status
                    || e.GetProperty("clickConfirmed").GetBoolean() != failure.ClickConfirmed
                    || e.GetProperty("resourceType").GetString() is not ("document" or "xhr" or "fetch")
                    || remove && (e.GetProperty("requestPayload").ValueKind != JsonValueKind.String
                        || string.IsNullOrWhiteSpace(e.GetProperty("requestPayload").GetString())))
                    throw new InvalidDataException("Product response evidence mismatch or missing action evidence.");
                review.ProductFailures[failure.CheckId] = $"Owned application {failure.Method} {failure.Url} returned HTTP {failure.Status}; "
                    + $"case={failure.CaseId}; response evidence={failure.Evidence.Path}; browser coverage remains independent.";
                if (e.TryGetProperty("bodyReadError", out var bodyError) && !string.IsNullOrEmpty(bodyError.GetString()))
                    review.Faults.Add("Response body observation: " + bodyError.GetString());
            }
            catch (Exception ex)
            {
                // Independent invalid evidence is unknown; it cannot erase an
                // already validated response or establish a new product failure.
                review.Faults.Add("Product response evidence: " + ex.Message);
            }
        }
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
        if (!path.StartsWith(root + System.IO.Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new InvalidDataException("Escaping browser evidence path.");
        for (var part = new FileInfo(path) as FileSystemInfo; part != null && part.FullName != root; part = part is FileInfo f ? f.Directory : ((DirectoryInfo)part).Parent)
            if ((part.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Linked browser evidence path.");
        if (Program.Sha256File(path) != reference.Sha256)
            throw new InvalidDataException("Browser evidence hash mismatch: " + reference.Path);
        return File.ReadAllBytes(path);
    }
}
