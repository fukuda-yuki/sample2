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
        CheckProductHttp(check);
        CheckProductComposition(check);
        CheckRemovalPrerequisites(check);
        CheckUnknownRemovalComposition(check);
        CheckMoney16(check);
        CheckMarkers16(check);
    }

    static void CheckMarkers16(Action<string,bool> check)
    {
        BrowserCartReview Load(string version,string after=null,int record=7)
        {
            using var f=new Fixture();
            string Div(int count)=>Cart(count,Html.Money2(count*8.99m),record).Replace("<table>","<section>").Replace("</table>","</section>").Replace("<tr","<div").Replace("</tr>","</div>").Replace("<td","<span").Replace("</td>","</span>");
            var request=f.File("request.json",JsonSerializer.Serialize(new {baseUrl="http://127.0.0.1:43001",runInstanceId=Instance,artifactSha256=Artifact,specSha256=Spec,evaluationVersion=version}));
            f.Receipt.SchemaVersion=3;f.Receipt.BaseUrl="http://127.0.0.1:43001";f.Receipt.RequestSha256=request.Sha256;
            for(var i=0;i<2;i++)
            {
                var id=i==0?"C-015":"C-016";var b=i==0?2:1;var a=b-1;
                f.Receipt.Removals[i].Before=f.Capture(id+"-before.json",Div(b)+$"<b id='cart-status'>Cart ({b})</b>",false,url:"http://127.0.0.1:43001/ShoppingCart");
                f.Receipt.Removals[i].After=f.Capture(id+"-after.json",(i==1 && after!=null?after:Div(a))+$"<b id='cart-status'>Cart ({a})</b>",true,url:"http://127.0.0.1:43001/ShoppingCart");
            }
            var receipt=f.File("receipt.json",JsonSerializer.Serialize(f.Receipt));
            return BrowserCartReview.Load(Path.Combine(f.Root,receipt.Path),Artifact,Spec,Instance,Catalog,true,true,true,version);
        }
        var positive=Load("1.6.0");
        check("1.6 hash-bound DIV cart receipt independently passes both removals",positive.Complete && positive.For("C-015").Pass && positive.For("C-016").Pass);
        foreach(var version in new[]{"1.4.0","1.5.0"})check(version+" DIV receipt retains historical precondition rejection",!Load(version).Complete);
        var unsupported=Load("1.6.0","<div id='row-invalid'></div><b id='cart-total'>0.00</b>");
        check("1.6 malformed residual browser row cannot establish empty removal",!unsupported.Complete && !unsupported.ProductFailures.ContainsKey("C-016") && unsupported.Faults.Count==0);
        var missing=Load("1.6.0","<div id='row-7'><a href='/Store/Details/1'>Title</a></div><b id='cart-total'>0.00</b>");
        check("1.6 missing required browser quantity retains finite failure plus coverage gap",!missing.Complete && missing.ProductFailures.ContainsKey("C-016") && missing.Faults.Count==0);
        var orphan=Load("1.6.0","<b id='item-count-7'>1</b><b id='cart-total'>0.00</b>");
        check("1.6 orphan browser quantity cannot establish empty removal",!orphan.Complete && orphan.ProductFailures.ContainsKey("C-016") && orphan.Faults.Count==0);
        var zero=Load("1.6.0",record:0);
        check("1.6 zero browser row identity is an unestablished operation prerequisite",!zero.Complete && zero.ProductFailures.Count==0 && zero.Faults.Count==0);
    }

    static void CheckMoney16(Action<string,bool> check)
    {
        BrowserCartReview Load(string version,string finalAmount,string afterOne=null,string afterTwo=null)
        {
            using var f=new Fixture();
            var request=f.File("request.json",JsonSerializer.Serialize(new {baseUrl="http://127.0.0.1:43001",runInstanceId=Instance,artifactSha256=Artifact,specSha256=Spec,evaluationVersion=version}));
            f.Receipt.SchemaVersion=3;f.Receipt.BaseUrl="http://127.0.0.1:43001";f.Receipt.RequestSha256=request.Sha256;
            for(var i=0;i<2;i++)
            {
                var id=i==0?"C-015":"C-016";var b=i==0?2:1;var a=b-1;
                f.Receipt.Removals[i].Before=f.Capture(id+"-before.json",Cart(b,"$"+Html.Money2(b*8.99m))+$"<b id='cart-status'>Cart ({b})</b>",false,url:"http://127.0.0.1:43001/ShoppingCart");
                f.Receipt.Removals[i].After=f.Capture(id+"-after.json",(i==0 && afterTwo!=null?afterTwo:i==1 && afterOne!=null?afterOne:Cart(a,i==0?"$8.99":finalAmount))+$"<b id='cart-status'>Cart ({a})</b>",true,url:"http://127.0.0.1:43001/ShoppingCart");
            }
            var receipt=f.File("receipt.json",JsonSerializer.Serialize(f.Receipt));
            return BrowserCartReview.Load(Path.Combine(f.Root,receipt.Path),Artifact,Spec,Instance,Catalog,true,true,true,version);
        }
        var pass=Load("1.6.0","$0.00");
        check("1.6 bound browser currency receipt passes both observed removals",pass.Complete && pass.For("C-015").Pass && pass.For("C-016").Pass);
        foreach(var old in new[]{"1.4.0","1.5.0"})check(old+" currency receipt retains historical precondition rejection",!Load(old,"$0.00").Complete);
        var precision=Load("1.6.0","$0");check("1.6 observed post-click wrong fraction is finite failure",precision.Complete && !precision.For("C-016").Pass);
        var ambiguous=Load("1.6.0","0.00 or 1.00");check("1.6 ambiguous browser money cannot become numeric quality",!ambiguous.Complete && !ambiguous.ProductFailures.ContainsKey("C-016"));
        var finite=Load("1.6.0","0.00 or 1.00",Cart(1,"0.00 or 1.00"));check("1.6 verified browser wrong quantity survives ambiguous money",!finite.Complete && finite.ProductFailures.ContainsKey("C-016"));
        var absent=Load("1.6.0","$0.00",afterTwo:"<b id='cart-total'>USD8.99</b>");check("1.6 decoded missing quantity-one row survives ambiguous browser money",!absent.Complete && absent.ProductFailures.ContainsKey("C-015") && absent.Faults.Count==0);
        var unsupported=Load("1.6.0","$0.00",afterTwo:"<div id='row-invalid'></div><b id='cart-total'>USD8.99</b>");check("1.6 unsupported residual row is not invented absent quantity-one row",!unsupported.Complete && !unsupported.ProductFailures.ContainsKey("C-015") && unsupported.Faults.Count==0);
    }

    static void CheckProductHttp(Action<string, bool> check)
    {
        // Synthetic collector receipts exercise binding and oracle routing only.
        using var f = new Fixture();
        var request = f.File("request.json", JsonSerializer.Serialize(new { baseUrl = "http://127.0.0.1:43001",
            runInstanceId = Instance, artifactSha256 = Artifact, specSha256 = Spec, evaluationVersion = "1.4.0" }));
        object Failure(string url = "http://127.0.0.1:43001/ShoppingCart/AddToCart/1", int status = 500,
            string checkId = "C-012", string operation = "cart-add", string method = "GET", bool clicked = false,
            string payload = null, bool mismatch = false, string bodyError = null)
        {
            var evidence = f.File("response-" + checkId + "-" + status + ".json", JsonSerializer.Serialize(new { caseId = "setup-" + checkId, checkId,
                operation, method, url, status = mismatch ? 200 : status, clickConfirmed = clicked,
                resourceType = "document", requestPayload = payload, responseBody = bodyError == null ? "synthetic generated app error" : null,
                bodyReadError = bodyError }));
            return new { caseId = "setup-" + checkId, checkId, operation, method, url, status, clickConfirmed = clicked, evidence };
        }
        BrowserCartReview Load(object failure, bool faults = false, string origin = "http://127.0.0.1:43001", string requestHash = null, bool invalidDom = false)
        {
            var receipt = f.File("receipt.json", JsonSerializer.Serialize(new { schemaVersion = 3, actor = "agent",
                runInstanceId = Instance, artifactSha256 = Artifact, specSha256 = Spec, baseUrl = origin,
                requestSha256 = requestHash ?? request.Sha256, removals = invalidDom ? f.Receipt.Removals.ToArray() : Array.Empty<BrowserCartReview.Removal>(),
                faults = faults ? new[] { "synthetic screenshot observer fault" } : Array.Empty<string>(),
                productFailures = failure == null ? Array.Empty<object>() : failure is object[] entries ? entries : new[] { failure } }));
            return BrowserCartReview.Load(Path.Combine(f.Root, receipt.Path), Artifact, Spec, Instance, Catalog, true, true, true);
        }
        var failed = Load(Failure(), true);
        check("owned add HTTP500 establishes C012 despite later observer fault", failed.ProductFailures.ContainsKey("C-012")
            && failed.Faults.Count == 1 && !failed.Complete && failed.For("C-015").Complete == false);
        var wrongVersionRejected = false;
        try { BrowserCartReview.Load(Path.Combine(f.Root, "receipt.json"), Artifact, Spec, Instance, Catalog); }
        catch (InvalidDataException) { wrongVersionRejected = true; }
        check("old contract cannot reinterpret schema3 response evidence", wrongVersionRejected);
        check("observer-only fault never establishes product failure", Load(null, true).ProductFailures.Count == 0);
        check("observed HTTP status survives response-body read failure", Load(Failure(bodyError: "synthetic bodyread fault")).ProductFailures.ContainsKey("C-012")
            && Load(Failure(bodyError: "synthetic bodyread fault")).Faults.Count > 0);
        var first = Failure();
        var badSecond = Failure(checkId: "C-015", operation: "cart-remove", method: "POST");
        var mixed = Load(new[] { first, badSecond });
        check("later invalid response cannot erase earlier bound product failure", mixed.ProductFailures.ContainsKey("C-012")
            && !mixed.ProductFailures.ContainsKey("C-015") && mixed.Faults.Count > 0 && !mixed.Complete);
        var invalidRef = f.Receipt.Removals[0].After;
        f.Receipt.Removals[0].After = new() { Path = "absent.json", Sha256 = "absent" };
        var badDom = Load(Failure(), invalidDom: true);
        check("later invalid DOM cannot erase earlier bound product failure", badDom.ProductFailures.ContainsKey("C-012") && badDom.Faults.Count > 0
            && badDom.For("C-015").Status == "observer_fault" && !badDom.Complete);
        f.Receipt.Removals[0].After = invalidRef;
        void Reject(string name, Func<BrowserCartReview> action)
        {
            var rejected = false; try { var r = action(); rejected = r.ProductFailures.Count == 0 && r.Faults.Count > 0 && !r.Complete; } catch (InvalidDataException) { rejected = true; }
            check(name, rejected);
        }
        Reject("foreign origin HTTP500 cannot establish product failure", () => Load(Failure("http://127.0.0.1:43002/ShoppingCart/AddToCart/1")));
        Reject("status label must match response evidence", () => Load(Failure(mismatch: true)));
        Reject("HTTP200 cannot establish server-error product failure", () => Load(Failure(status: 200)));
        Reject("unperformed operation cannot establish unrelated requirement", () => Load(Failure(checkId: "C-013")));
        Reject("off-route response cannot establish product failure", () => Load(Failure("http://127.0.0.1:43001/unrelated")));
        Reject("query-bearing response cannot establish product failure", () => Load(Failure("http://127.0.0.1:43001/ShoppingCart/AddToCart/1?other=1")));
        Reject("missing click cannot establish cart removal failure", () => Load(Failure("http://127.0.0.1:43001/ShoppingCart/RemoveFromCart", checkId: "C-015", operation: "cart-remove", method: "POST", payload: "id=7")));
        Reject("missing request payload cannot establish cart removal failure", () => Load(Failure("http://127.0.0.1:43001/ShoppingCart/RemoveFromCart", checkId: "C-015", operation: "cart-remove", method: "POST", clicked: true)));
        check("confirmed same-origin POST removal HTTP500 establishes finite failure", Load(Failure("http://127.0.0.1:43001/ShoppingCart/RemoveFromCart", status: 599, checkId: "C-015", operation: "cart-remove", method: "POST", clicked: true, payload: "id=7")).ProductFailures.ContainsKey("C-015"));
        Reject("receipt request hash must bind the observation request", () => Load(Failure(), requestHash: "other"));
        Reject("non-loopback owned origin is rejected", () => Load(Failure(), origin: "https://example.com"));
        var restore = Load(Failure());
        System.IO.File.AppendAllText(Path.Combine(f.Root, "response-C-012-500.json"), " ");
        Reject("changed response bytes cannot preserve a product failure", () => BrowserCartReview.Load(Path.Combine(f.Root, "receipt.json"), Artifact, Spec, Instance, Catalog, true, true, true));
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

    static void CheckProductComposition(Action<string, bool> check)
    {
        using var f = new Fixture();
        var artifact = Path.Combine(f.Root, "artifact"); Directory.CreateDirectory(artifact);
        var baseline = Path.Combine(f.Root, "baseline"); Directory.CreateDirectory(baseline);
        var ledger = new Ledger { TaskId = "MS1-synthetic", SpecVersion = "1.4.0", MigrationContract = new(), Requirements = new()
        {
            new() { Id = "R-add", Severity = "critical", Checks = new() { new() { Id = "C-012" } } },
            new() { Id = "R-remove", Severity = "major", Checks = new() { new() { Id = "C-015" }, new() { Id = "C-016" } } },
        } };
        var spec = f.File("spec.json", JsonSerializer.Serialize(ledger));
        var catalog = f.File("catalog.json", JsonSerializer.Serialize(Catalog));
        var ah = MusicStore.Evaluator.Program.Sha256Directory(artifact);
        var request = f.File("request.json", JsonSerializer.Serialize(new { baseUrl = "http://127.0.0.1:43001",
            runInstanceId = Instance, artifactSha256 = ah, specSha256 = spec.Sha256, evaluationVersion = "1.4.0" }));
        var evidence = f.File("response.json", JsonSerializer.Serialize(new { caseId = "setup-add", checkId = "C-012", operation = "cart-add",
            method = "GET", url = "http://127.0.0.1:43001/ShoppingCart/AddToCart/1", status = 500, clickConfirmed = false,
            resourceType = "document", requestPayload = (string)null, bodyReadError = "synthetic body read fault" }));
        var receipt = f.File("receipt.json", JsonSerializer.Serialize(new { schemaVersion = 3, actor = "agent", runInstanceId = Instance,
            artifactSha256 = ah, specSha256 = spec.Sha256, baseUrl = "http://127.0.0.1:43001", requestSha256 = request.Sha256,
            removals = new object[0], faults = new[] { "synthetic trace cleanup fault" }, productFailures = new[] { new
            { caseId = "setup-add", checkId = "C-012", operation = "cart-add", method = "GET", url = "http://127.0.0.1:43001/ShoppingCart/AddToCart/1",
                status = 500, clickConfirmed = false, evidence } } }));
        var baselineFile = Path.Combine(baseline, "evaluation.json");
        var before = new EvaluationOutput { TaskId = ledger.TaskId, SpecVersion = "1.4.0", EvaluationVersion = "1.4.0",
            ArtifactSha256 = ah, SpecSha256 = spec.Sha256, Verdict = "blocked", Quality = null, ResearchStatus = "incomplete",
            Requirements = ledger.Requirements.Select(r => new RequirementOutcome { Id = r.Id, Judgement = "pass" }).ToList() };
        System.IO.File.WriteAllText(baselineFile, JsonSerializer.Serialize(before));
        var resultFile = Path.Combine(baseline, "results.jsonl");
        System.IO.File.WriteAllLines(resultFile, ledger.Requirements.SelectMany(r => r.Checks.Select(c =>
            JsonSerializer.Serialize(new CheckResult { RequirementId = r.Id, CheckId = c.Id, Judgement = "pass" }))));
        var beforeEval = MusicStore.Evaluator.Program.Sha256File(baselineFile);
        var beforeResults = MusicStore.Evaluator.Program.Sha256File(resultFile);
        var output = Path.Combine(f.Root, "reassessment");
        var code = MusicStore.Evaluator.Program.Main(new[] { "--artifact", artifact, "--out", output,
            "--spec", Path.Combine(f.Root, spec.Path), "--catalog", Path.Combine(f.Root, catalog.Path), "--evaluation-version", "1.4.0",
            "--browser-cart-baseline", baseline, "--browser-cart-evidence", Path.Combine(f.Root, receipt.Path), "--review-run-instance-id", Instance });
        var value = JsonSerializer.Deserialize<EvaluationOutput>(System.IO.File.ReadAllText(Path.Combine(output, "evaluation.json")), new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        check("new composition preserves bound HTTP500 plus observer faults with incomplete null quality", code == 2 && value.Verdict == "fail_critical"
            && value.Quality == null && value.ResearchStatus == "incomplete" && value.EvaluatorFaults.Count >= 2
            && value.Requirements.Single(r => r.Id == "R-add").Judgement == "fail"
            && value.Requirements.Single(r => r.Id == "R-remove").Judgement == "blocked");
        check("partial composition leaves first baseline bytes unchanged", beforeEval == MusicStore.Evaluator.Program.Sha256File(baselineFile)
            && beforeResults == MusicStore.Evaluator.Program.Sha256File(resultFile));
        check("new contract inherits explicit order rules", new RunState { EvaluationVersion = "1.4.0" }.ExplicitOrderContract);
    }

    static void CheckRemovalPrerequisites(Action<string, bool> check)
    {
        using var state = new RunState { AppReady = true, EvaluationVersion = "1.5.0", Catalog = Catalog,
            Ledger = new Ledger { Requirements = new() { new() { Id = "R-014" }, new() { Id = "R-015" } } },
            Cart = new CartResult { RemoveFromTwo = new WebResponse { Status = 404, Body = "" },
                RemoveFromOne = new WebResponse { Status = 404, Body = "" }, TotalAfterRemoveFromTwo = 0m, TotalAfterRemoveFromOne = 0m } };
        check("1.5 empty cart setup cannot prove quantity-two removal failure", Checks.Registry["C-015"](state).Judgement == Judgement.Blocked);
        check("1.5 empty cart setup cannot prove quantity-one removal failure", Checks.Registry["C-016"](state).Judgement == Judgement.Blocked);
        state.EvaluationVersion = "1.4.0";
        check("1.4 retains historical cascade labels for both empty-setup removals", Checks.Registry["C-015"](state).Judgement == Judgement.Fail
            && Checks.Registry["C-016"](state).Judgement == Judgement.Fail);
        state.EvaluationVersion = "1.5.0";
        state.Cart.LinesAfterTwoAdds = Html.CartLines(Cart(2,"17.98"));
        state.Cart.RecordId = 7;
        check("1.5 valid quantity-two prerequisite retains real HTTP removal failure", Checks.Registry["C-015"](state).Judgement == Judgement.Fail);
        state.Cart.LinesAfterRemoveFromTwo = Html.CartLines(Cart(1,"8.99",9));
        check("1.5 valid quantity-one prerequisite retains real HTTP removal failure", Checks.Registry["C-016"](state).Judgement == Judgement.Fail);
        state.Cart.RemoveFromTwo.Body = "{\"itemCount\":1}"; state.Cart.TotalAfterRemoveFromTwo = 8.99m;
        state.Cart.RemoveFromOne.Body = "{\"itemCount\":0}";
        check("1.5 valid independent HTTP removal observations can pass", Checks.Registry["C-015"](state).Judgement == Judgement.Pass
            && Checks.Registry["C-016"](state).Judgement == Judgement.Pass);
        state.Cart.RemoveFromTwo = null;
        check("1.5 absent request observation stays unknown despite populated cart", Checks.Registry["C-015"](state).Judgement == Judgement.Blocked);
        state.Cart.LinesAfterRemoveFromTwo = Html.CartLines(Cart(2,"17.98",9));
        check("1.5 failed decrement cannot satisfy following quantity-one prerequisite", Checks.Registry["C-016"](state).Judgement == Judgement.Blocked);
        state.Cart.LinesAfterRemoveFromTwo = Html.CartLines(Cart(1,"8.99",0));
        check("1.5 nonpositive record identity cannot satisfy removal prerequisite", Checks.Registry["C-016"](state).Judgement == Judgement.Blocked);
        var submitted = new List<int>();
        WebResponse Submit(int id) { submitted.Add(id); return new WebResponse { Body = "synthetic response" }; }
        check("1.5 dispatch performs no removal request when setup is empty", Scenarios.ObserveRemoval("1.5.0", new List<Html.CartLine>(), 2, 0, Submit) == null && submitted.Count == 0);
        Scenarios.ObserveRemoval("1.4.0", new List<Html.CartLine>(), 2, 0, Submit);
        check("1.4 dispatch retains historical id-zero request", submitted.SequenceEqual(new[] { 0 }));
        submitted.Clear();
        Scenarios.ObserveRemoval("1.5.0", Html.CartLines(Cart(1,"8.99",9)), 1, 7, Submit);
        check("1.5 dispatch uses current row identity after row replacement", submitted.SequenceEqual(new[] { 9 }));
        submitted.Clear();
        Scenarios.ObserveRemoval("1.5.0", Html.CartLines(Cart(2,"17.98",9)), 1, 7, Submit);
        check("1.5 dispatch performs no request at wrong quantity", submitted.Count == 0);
    }

    static void CheckUnknownRemovalComposition(Action<string, bool> check)
    {
        using var f = new Fixture();
        var artifact = Path.Combine(f.Root, "artifact"); Directory.CreateDirectory(artifact);
        var baseline = Path.Combine(f.Root, "baseline"); Directory.CreateDirectory(baseline);
        var ledger = new Ledger { TaskId = "MS1-synthetic-unknown", SpecVersion = "1.5.0", MigrationContract = new(), Requirements = new()
        {
            new() { Id = "R-014", Severity = "major", Checks = new() { new() { Id = "C-015" } } },
            new() { Id = "R-015", Severity = "major", Checks = new() { new() { Id = "C-016" } } },
        } };
        var spec = f.File("spec.json", JsonSerializer.Serialize(ledger));
        var catalog = f.File("catalog.json", JsonSerializer.Serialize(Catalog));
        var ah = MusicStore.Evaluator.Program.Sha256Directory(artifact);
        var request = f.File("request.json", JsonSerializer.Serialize(new { baseUrl = "http://127.0.0.1:43001", runInstanceId = Instance,
            artifactSha256 = ah, specSha256 = spec.Sha256, evaluationVersion = "1.5.0" }));
        f.Receipt.SchemaVersion = 3; f.Receipt.BaseUrl = "http://127.0.0.1:43001"; f.Receipt.RequestSha256 = request.Sha256;
        f.Receipt.ArtifactSha256 = ah; f.Receipt.SpecSha256 = spec.Sha256;
        var baseFile = Path.Combine(baseline,"evaluation.json"); var resultsFile = Path.Combine(baseline,"results.jsonl");
        (EvaluationOutput Value, List<CheckResult> Results) Run(string name, string judgement, bool browserFail)
        {
            var before = new EvaluationOutput { TaskId = ledger.TaskId, SpecVersion = "1.5.0", EvaluationVersion = "1.5.0",
                ArtifactSha256 = ah, SpecSha256 = spec.Sha256, Verdict = judgement == "error" ? "error" : judgement == "fail" ? "fail" : "blocked",
                Quality = null, ResearchStatus = "incomplete", Requirements = ledger.Requirements.Select(r =>
                    new RequirementOutcome { Id = r.Id, Judgement = judgement }).ToList() };
            System.IO.File.WriteAllText(baseFile,JsonSerializer.Serialize(before));
            System.IO.File.WriteAllLines(resultsFile,ledger.Requirements.Select(r => JsonSerializer.Serialize(new CheckResult {
                RequirementId = r.Id, CheckId = r.Checks[0].Id, Judgement = judgement,
                Observation = judgement == "error" ? "synthetic observer fault" : "synthetic HTTP prerequisite or result" })));
            for (var i = 0; i < 2; i++)
            {
                var id = i == 0 ? "C-015" : "C-016"; var b = i == 0 ? 2 : 1; var a = b-1;
                f.Receipt.Removals[i].Before = f.Capture(id+"-before.json", Cart(b,Html.Money2(b*8.99m))+ $"<b id='cart-status'>Cart ({b})</b>",false,url:"http://127.0.0.1:43001/ShoppingCart");
                f.Receipt.Removals[i].After = f.Capture(id+"-after.json", Cart(a,browserFail ? "99.00" : Html.Money2(a*8.99m))+$"<b id='cart-status'>Cart ({a})</b>",true,url:"http://127.0.0.1:43001/ShoppingCart");
            }
            var receipt = f.File("receipt.json",JsonSerializer.Serialize(f.Receipt));
            var oldBaseline = MusicStore.Evaluator.Program.Sha256File(baseFile); var oldResults = MusicStore.Evaluator.Program.Sha256File(resultsFile);
            var output = Path.Combine(f.Root,name);
            MusicStore.Evaluator.Program.Main(new[] {"--artifact",artifact,"--out",output,"--spec",Path.Combine(f.Root,spec.Path),
                "--catalog",Path.Combine(f.Root,catalog.Path),"--evaluation-version","1.5.0","--browser-cart-baseline",baseline,
                "--browser-cart-evidence",Path.Combine(f.Root,receipt.Path),"--review-run-instance-id",Instance});
            check(name+" leaves baseline bytes unchanged",oldBaseline==MusicStore.Evaluator.Program.Sha256File(baseFile) && oldResults==MusicStore.Evaluator.Program.Sha256File(resultsFile));
            var opts = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
            return (JsonSerializer.Deserialize<EvaluationOutput>(System.IO.File.ReadAllText(Path.Combine(output,"evaluation.json")),opts),
                System.IO.File.ReadLines(Path.Combine(output,"results.jsonl")).Select(t=>JsonSerializer.Deserialize<CheckResult>(t,opts)).ToList());
        }
        var finite = Run("unknown-browser-fail","blocked",true);
        check("1.5 independent browser failure cannot erase HTTP coverage gap",finite.Value.Verdict=="fail" && finite.Value.ResearchStatus=="incomplete"
            && finite.Value.Quality==null && finite.Value.FailedCount==2 && finite.Value.EvaluatorFaults.Count==0 && finite.Value.UncheckedScope.Count>=2);
        var pass = Run("unknown-browser-pass","blocked",false);
        check("1.5 browser pass cannot promote unknown HTTP JSON to pass",pass.Value.ResearchStatus=="incomplete" && pass.Value.Quality==null
            && pass.Value.Requirements.All(r=>r.Judgement=="blocked"));
        var fault = Run("fault-browser-fail","error",true);
        check("1.5 independent browser failure retains HTTP observer faults",fault.Value.Verdict=="fail" && fault.Value.ResearchStatus=="incomplete"
            && fault.Value.Quality==null && fault.Value.EvaluatorFaults.Count>0);
        var sticky = Run("failed-browser-pass","fail",false);
        check("1.5 established HTTP failure is not erased by another browser pass",sticky.Value.Requirements.All(r=>r.Judgement=="fail"));
    }
}
