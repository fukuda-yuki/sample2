using System.Text.Json;
using MusicStore.Evaluator;

static class BrowserCartReviewTests
{
    // Synthetic observations exercise the adapter; they are not app/UI evidence.
    const string Artifact = "synthetic-artifact", Spec = "synthetic-spec", Instance = "synthetic-instance";
    static readonly Catalog Catalog = new() { Albums = new() { new() { AlbumId = 1, Price = 8.99m } } };
    static string Cart(int count, string total, int record = 7) => "<table>"
        + (count == 0 ? "" : $"<tr id='row-{record}'><td><a href='/Store/Details/1'>Title</a></td><td id='item-count-{record}'><b>{count}</b></td></tr>")
        + $"<tr><td id='cart-total'><span>{total}</span></td></tr></table>";

    sealed class Fixture : IDisposable
    {
        public readonly string Root = Path.Combine(Path.GetTempPath(), "sample2-browser-" + Guid.NewGuid().ToString("N"));
        public readonly BrowserCartReview.Receipt Receipt = new()
        {
            SchemaVersion = 1, Actor = "agent", RunInstanceId = Instance,
            ArtifactSha256 = Artifact, SpecSha256 = Spec, Removals = new(),
        };
        public Fixture(string afterTwo = null, string afterOne = null)
        {
            Directory.CreateDirectory(Root);
            Add("C-015", Cart(2, "17.98"), afterTwo ?? Cart(1, "8.99", 9));
            Add("C-016", Cart(1, "8.99"), afterOne ?? Cart(0, "0.00"));
        }
        public BrowserCartReview.FileReference File(string name, string value)
        {
            var path = Path.Combine(Root, name);
            System.IO.File.WriteAllText(path, value);
            return new() { Path = name, Sha256 = MusicStore.Evaluator.Program.Sha256File(path) };
        }
        public BrowserCartReview.FileReference Capture(string name, string html, bool after, string tab = "tab-A", string url = "http://review.localhost/ShoppingCart") =>
            File(name, JsonSerializer.Serialize(new { at = after ? "2026-09-19T01:01:00Z" : "2026-09-19T01:00:00Z", tabId = tab, page = new { url, html } }));
        void Add(string id, string before, string after) => Receipt.Removals.Add(new()
        {
            CheckId = id, Action = "click-remove",
            Before = Capture(id + "-before.json", before, false),
            After = Capture(id + "-after.json", after, true),
            BeforeScreenshot = File(id + "-before.png", "synthetic screenshot bytes before"),
            AfterScreenshot = File(id + "-after.png", "synthetic screenshot bytes after"),
        });
        public BrowserCartReview Load()
        {
            var path = Path.Combine(Root, "receipt.json");
            System.IO.File.WriteAllText(path, JsonSerializer.Serialize(Receipt));
            return BrowserCartReview.Load(path, Artifact, Spec, Instance, Catalog);
        }
        public void Dispose() => Directory.Delete(Root, true);
    }

    public static void Run(Action<string, bool> check)
    {
        using var valid = new Fixture();
        var browserPass = valid.Load();
        check("browser accepts DOM-equivalent text and changing record IDs", browserPass.For("C-015").Pass && browserPass.For("C-016").Pass);
        using var stale = new Fixture(Cart(1, "17.98"), Cart(0, "8.99"));
        var browserStale = stale.Load();
        check("browser catches stale total after 2 to 1", !browserStale.For("C-015").Pass);
        check("browser catches stale total after 1 to 0", !browserStale.For("C-016").Pass);
        using var dead = new Fixture(Cart(2, "17.98"), Cart(1, "8.99"));
        check("browser catches dead remove link with quantity two", !dead.Load().For("C-015").Pass);
        check("browser catches dead remove link with quantity one", !dead.Load().For("C-016").Pass);
        using var duplicate = new Fixture(Cart(1, "8.99") + "<b id='cart-total'>8.99</b>");
        check("browser rejects ambiguous duplicate total", !duplicate.Load().For("C-015").Pass);
        using var missing = new Fixture("<p>1 item, 8.99</p>");
        check("browser cannot pass from unstructured text", !missing.Load().For("C-015").Pass);

        void Reject(string name, Action<Fixture> change)
        {
            using var f = new Fixture();
            change(f);
            var rejected = false;
            try { f.Load(); } catch (InvalidDataException) { rejected = true; }
            check(name, rejected);
        }
        Reject("browser rejects wrong artifact", f => f.Receipt.ArtifactSha256 = "wrong");
        Reject("browser rejects wrong spec", f => f.Receipt.SpecSha256 = "wrong");
        Reject("browser rejects wrong Run instance", f => f.Receipt.RunInstanceId = "wrong");
        Reject("browser rejects human attribution", f => f.Receipt.Actor = "human");
        Reject("browser rejects HTTP attributed as click", f => f.Receipt.Removals[0].Action = "http-post");
        Reject("browser rejects duplicated check", f => f.Receipt.Removals[1].CheckId = "C-015");
        Reject("browser rejects omitted check", f => f.Receipt.Removals.RemoveAt(1));
        Reject("browser rejects empty precondition", f => f.Receipt.Removals[0].Before = f.Capture("empty.json", Cart(0, "0.00"), false));
        Reject("browser rejects wrong starting total", f => f.Receipt.Removals[0].Before = f.Capture("wrong.json", Cart(2, "8.99"), false));
        Reject("browser rejects changed DOM bytes", f => System.IO.File.AppendAllText(Path.Combine(f.Root, f.Receipt.Removals[0].After.Path), " "));
        Reject("browser rejects changed screenshot bytes", f => System.IO.File.AppendAllText(Path.Combine(f.Root, f.Receipt.Removals[0].AfterScreenshot.Path), " "));
        Reject("browser rejects path traversal", f => f.Receipt.Removals[0].After.Path = "../after.json");
        Reject("browser rejects different context", f => f.Receipt.Removals[0].After = f.Capture("other.json", Cart(1, "8.99"), true, "tab-B"));
        Reject("browser rejects different origin", f => f.Receipt.Removals[0].After = f.Capture("other.json", Cart(1, "8.99"), true, url: "http://other.localhost/ShoppingCart"));
        Reject("browser rejects non-cart route", f => f.Receipt.Removals[0].After = f.Capture("other.json", Cart(1, "8.99"), true, url: "http://review.localhost/"));
        Reject("browser rejects non-increasing timestamps", f => f.Receipt.Removals[0].After = f.Capture("other.json", Cart(1, "8.99"), false));
        var ledger = new Ledger { Requirements = new() { new() { Id = "R-014" }, new() { Id = "R-015" } } };
        using var state = new RunState { AppReady = true, Ledger = ledger, Catalog = Catalog, Cart = new()
        {
            RemoveFromTwo = new() { Body = "{\"itemCount\":1}" },
            LinesAfterRemoveFromTwo = Html.CartLines(Cart(1, "8.99")), TotalAfterRemoveFromTwo = 8.99m,
            RemoveFromOne = new() { Body = "{\"itemCount\":0}" }, TotalAfterRemoveFromOne = 0m,
        } };
        check("HTTP-only compatibility explicitly reports missing browser coverage", Checks.Registry["C-015"](state).Judgement == Judgement.Pass
            && Checks.Registry["C-015"](state).Observation.Contains("未観測"));
        state.BrowserCartReview = browserStale;
        check("browser failure overrides passing HTTP and reloaded cart", Checks.Registry["C-015"](state).Judgement == Judgement.Fail
            && Checks.Registry["C-016"](state).Judgement == Judgement.Fail);
        state.BrowserCartReview = browserPass;
        check("passing browser and HTTP remain passing", Checks.Registry["C-015"](state).Judgement == Judgement.Pass
            && Checks.Registry["C-016"](state).Judgement == Judgement.Pass);
        state.Cart.RemoveFromTwo.Body = "{\"itemCount\":0}";
        state.Cart.RemoveFromOne.Body = "{\"itemCount\":1}";
        check("browser pass cannot mask wrong server JSON", Checks.Registry["C-015"](state).Judgement == Judgement.Fail
            && Checks.Registry["C-016"](state).Judgement == Judgement.Fail);
        check("browser CLI requires instance pairing", CliOptions.Parse(new[] { "--artifact", ".", "--out", ".", "--browser-cart-evidence", "receipt.json" }) == null);
    }
}
