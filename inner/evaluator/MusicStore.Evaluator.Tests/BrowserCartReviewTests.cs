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
        using var navigation = new Fixture();
        navigation.Receipt.Removals[0].After = navigation.Capture("redirect.json", Cart(1, "8.99"), true, url: "http://review.localhost/ShoppingCart/Index");
        check("application navigation to a valid cart is allowed", navigation.Load().For("C-015").Pass);
        navigation.Receipt.Removals[0].After = navigation.Capture("json-page.json", "<pre>{\"itemCount\":1}</pre>", true,
            url: "http://review.localhost/ShoppingCart/RemoveFromCart");
        check("application navigation to JSON is an observed product failure", !navigation.Load().For("C-015").Pass);
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
        CheckComposition(check);
        CheckUnperformed(check);
    }

    static void CheckUnperformed(Action<string, bool> check)
    {
        foreach (var reason in new[] { "control_absent", "control_disabled" })
        {
            using var f = new Fixture();
            f.Receipt.SchemaVersion = 2;
            f.Receipt.Removals[0].Action = "observe-unavailable";
            f.Receipt.Removals[0].Reason = reason;
            var review = f.Load();
            check(reason + " is assessed product failure without a click", review.Complete
                && !review.For("C-015").Pass && review.For("C-015").Status == "unavailable");
        }
        using var unsupported = new Fixture();
        unsupported.Receipt.SchemaVersion = 2;
        unsupported.Receipt.Removals[0].Action = "not-run-unsupported";
        unsupported.Receipt.Removals[0].Reason = "selector_ambiguous_or_unsupported";
        check("unknown selector is incomplete, not an established product failure", !unsupported.Load().Complete
            && !unsupported.Load().For("C-015").Complete && unsupported.Load().ProductFailures.Count == 0);
        using var quantity = new Fixture();
        quantity.Receipt.SchemaVersion = 2;
        var r = quantity.Receipt.Removals[0];
        r.Action = "not-run-precondition"; r.Reason = "quantity_after_two_adds"; r.AddCount = 2;
        r.Before = quantity.Capture("quantity.json", Cart(3, "26.97"), false);
        r.SetupBefore = quantity.Capture("empty.json", Cart(0, "0.00"), false);
        r.SetupScreenshot = quantity.File("empty.png", "synthetic empty screenshot");
        var partial = quantity.Load();
        check("two-add product failure survives unperformed removal", !partial.Complete
            && partial.ProductFailures.ContainsKey("C-013") && partial.For("C-015").Status == "not_run_precondition");
        r.AddCount = 1;
        var rejected = false;
        try { quantity.Load(); } catch (InvalidDataException) { rejected = true; }
        check("quantity claim without two additions is rejected", rejected);
        using var launch = new Fixture();
        launch.Receipt.SchemaVersion = 2; launch.Receipt.Removals.Clear(); launch.Receipt.Faults.Add("launch failed");
        check("launch failure carries no product judgement", !launch.Load().Complete
            && launch.Load().ProductFailures.Count == 0 && launch.Load().Faults.Count == 1);
    }

    static void CheckComposition(Action<string, bool> check)
    {
        using var f = new Fixture(Cart(1, "17.98"), Cart(0, "8.99"));
        var artifact = Path.Combine(f.Root, "artifact"); Directory.CreateDirectory(artifact);
        var baseline = Path.Combine(f.Root, "baseline"); Directory.CreateDirectory(baseline);
        var spec = Path.Combine(f.Root, "spec.json");
        var ledger = new Ledger { TaskId = "MS1-001", SpecVersion = "1.2.0", Requirements = new()
        {
            new() { Id = "R-014", Severity = "major", Checks = new() { new() { Id = "C-015" } } },
            new() { Id = "R-015", Severity = "major", Checks = new() { new() { Id = "C-016" } } },
            new() { Id = "R-029", Severity = "major", Checks = new() { new() { Id = "C-030" } } },
        } };
        System.IO.File.WriteAllText(spec, JsonSerializer.Serialize(ledger));
        var catalog = Path.Combine(f.Root, "catalog.json"); System.IO.File.WriteAllText(catalog, JsonSerializer.Serialize(Catalog));
        var ah = MusicStore.Evaluator.Program.Sha256Directory(artifact);
        var sh = MusicStore.Evaluator.Program.Sha256File(spec);
        f.Receipt.ArtifactSha256 = ah; f.Receipt.SpecSha256 = sh;
        var receipt = Path.Combine(f.Root, "receipt.json"); System.IO.File.WriteAllText(receipt, JsonSerializer.Serialize(f.Receipt));
        var before = new EvaluationOutput { TaskId = "MS1-001", SpecVersion = "1.2.0", EvaluationVersion = "1.2.0",
            ArtifactSha256 = ah, SpecSha256 = sh, Verdict = "pass", Quality = 100,
            Requirements = ledger.Requirements.Select(r => new RequirementOutcome { Id = r.Id, Judgement = "pass" }).ToList() };
        var baselineJson = Path.Combine(baseline, "evaluation.json");
        void SaveBaseline() => System.IO.File.WriteAllText(baselineJson, JsonSerializer.Serialize(before));
        SaveBaseline();
        var resultLines = ledger.Requirements.Select(r => JsonSerializer.Serialize(new CheckResult
            { RequirementId = r.Id, CheckId = r.Checks[0].Id, Judgement = "pass", Observation = "saved HTTP" })).ToArray();
        var resultsPath = Path.Combine(baseline, "results.jsonl"); System.IO.File.WriteAllLines(resultsPath, resultLines);
        (int Code, EvaluationOutput Value) Run(string name, string evidence = null)
        {
            var output = Path.Combine(f.Root, name);
            var code = MusicStore.Evaluator.Program.Main(new[] { "--artifact", artifact, "--out", output, "--spec", spec,
                "--catalog", catalog, "--evaluation-version", "1.2.0", "--browser-cart-baseline", baseline,
                "--browser-cart-evidence", evidence ?? receipt, "--review-run-instance-id", Instance });
            var value = JsonSerializer.Deserialize<EvaluationOutput>(System.IO.File.ReadAllText(Path.Combine(output, "evaluation.json")),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            return (code, value);
        }
        var corrected = Run("corrected");
        check("composition retains corrected R-029 and vetoes exactly two HTTP passes", corrected.Code == 0
            && corrected.Value.ResearchStatus == "complete" && corrected.Value.FailedCount == 2
            && corrected.Value.Requirements.Single(r => r.Id == "R-029").Judgement == "pass");
        check("composition does not execute any application scenario", !Directory.Exists(Path.Combine(f.Root, "corrected", "work")));
        var missing = Run("missing", Path.Combine(f.Root, "absent.json"));
        check("missing browser evidence is evaluator fault, never HTTP fallback", missing.Code == 2
            && missing.Value.Verdict == "error" && missing.Value.Quality == null && missing.Value.ResearchStatus == "incomplete");
        before.Verdict = "fail"; before.Quality = 66.67;
        before.Requirements.Single(r => r.Id == "R-029").Judgement = "fail";
        var failedLines = resultLines.ToArray();
        failedLines[2] = JsonSerializer.Serialize(new CheckResult { RequirementId = "R-029", CheckId = "C-030", Judgement = "fail" });
        System.IO.File.WriteAllLines(resultsPath, failedLines); SaveBaseline();
        var failedMissing = Run("failed-missing", Path.Combine(f.Root, "absent.json"));
        check("HTTP failure remains fail alongside missing browser evidence", failedMissing.Code == 2
            && failedMissing.Value.Verdict == "fail" && failedMissing.Value.Quality == null
            && failedMissing.Value.ResearchStatus == "incomplete" && failedMissing.Value.EvaluatorFaults.Count > 0
            && failedMissing.Value.Requirements.Single(r => r.Id == "R-029").Judgement == "fail");
        before.Verdict = "pass"; before.Quality = 100;
        before.Requirements.Single(r => r.Id == "R-029").Judgement = "pass";
        System.IO.File.WriteAllLines(resultsPath, resultLines); SaveBaseline();
        before.ArtifactSha256 = "other"; SaveBaseline();
        check("composition rejects other target baseline", Run("other").Code == 2);
        before.ArtifactSha256 = ah; before.Quality = 0; SaveBaseline();
        check("composition rejects inconsistent baseline scores", Run("inconsistent").Code == 2);
        before.Quality = 100; SaveBaseline();
        System.IO.File.WriteAllLines(resultsPath, resultLines.Take(2));
        check("composition rejects missing baseline check instead of assuming pass", Run("omitted").Code == 2);
        System.IO.File.WriteAllLines(resultsPath, resultLines);
        f.Receipt.RunInstanceId = "other"; System.IO.File.WriteAllText(receipt, JsonSerializer.Serialize(f.Receipt));
        check("composition rejects evidence from another Run", Run("other-receipt").Code == 2);
    }
}
