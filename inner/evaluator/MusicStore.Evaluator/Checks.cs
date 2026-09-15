using System.Globalization;
using System.Text.RegularExpressions;

namespace MusicStore.Evaluator;

/// <summary>
/// 台帳の検査 ID と 1 対 1 で対応する検査の実装。
/// 実装されていない検査 ID が台帳にあれば、評価全体を error（評価側の障害）にする。
/// </summary>
public static class Checks
{
    public static readonly Dictionary<string, Func<RunState, CheckResult>> Registry =
        new Dictionary<string, Func<RunState, CheckResult>>(StringComparer.Ordinal)
        {
            ["C-001"] = C001,
            ["C-002"] = C002,
            ["C-003"] = C003,
            ["C-004"] = C004,
            ["C-005"] = C005,
            ["C-006"] = C006,
            ["C-007"] = C007,
            ["C-008"] = C008,
            ["C-009"] = C009,
            ["C-010"] = C010,
            ["C-011"] = C011,
            ["C-012"] = C012,
            ["C-013"] = C013,
            ["C-014"] = C014,
            ["C-015"] = C015,
            ["C-016"] = C016,
            ["C-017"] = C017,
            ["C-018"] = C018,
            ["C-019"] = C019,
            ["C-020"] = C020,
            ["C-021"] = C021,
            ["C-022"] = C022,
            ["C-023"] = C023,
            ["C-024"] = C024,
            ["C-025"] = C025,
            ["C-026"] = C026,
            ["C-027"] = C027,
            ["C-028"] = C028,
            ["C-029"] = C029,
            ["C-030"] = C030,
        };

    private static CheckResult Make(RunState state, string requirementId, string checkId, string input, string judgement, string observed, string evidence)
    {
        var requirement = state.Ledger.Requirements.First(r => r.Id == requirementId);
        return new CheckResult
        {
            RequirementId = requirementId,
            CheckId = checkId,
            Input = input,
            Expectation = requirement.Expectation,
            Observation = observed,
            Judgement = judgement,
            Evidence = evidence,
        };
    }

    private static CheckResult Pass(RunState state, string requirementId, string checkId, string input, string observed, string evidence = "") =>
        Make(state, requirementId, checkId, input, Judgement.Pass, observed, evidence);

    private static CheckResult Fail(RunState state, string requirementId, string checkId, string input, string observed, string evidence = "") =>
        Make(state, requirementId, checkId, input, Judgement.Fail, observed, evidence);

    private static CheckResult Verdict(RunState state, string requirementId, string checkId, string input, bool ok, string observed, string evidence = "") =>
        ok ? Pass(state, requirementId, checkId, input, observed, evidence) : Fail(state, requirementId, checkId, input, observed, evidence);

    private static CheckResult Fault(RunState state, string requirementId, string checkId, string input, ScenarioResult scenario, string evidence = "")
    {
        if (scenario.Fault == Judgement.Blocked)
        {
            return Make(state, requirementId, checkId, input, Judgement.Blocked, "未評価: " + scenario.FaultDetail, evidence);
        }

        return Make(state, requirementId, checkId, input, Judgement.Error, "評価側の障害: " + scenario.FaultDetail, evidence);
    }

    private static CheckResult Precondition(RunState state, string requirementId, string checkId, string input)
    {
        if (state.EvaluatorFault != null)
        {
            return Make(state, requirementId, checkId, input, Judgement.Error, "評価側の障害: " + state.EvaluatorFault, string.Empty);
        }

        if (!state.AppReady)
        {
            return Make(state, requirementId, checkId, input, Judgement.Blocked, "未評価: " + state.AppStartDetail, string.Empty);
        }

        return null;
    }

    private static CheckResult C001(RunState state)
    {
        const string input = "成果物ディレクトリを dotnet publish する";
        if (state.EvaluatorFault != null)
        {
            return Make(state, "R-001", "C-001", input, Judgement.Error, "評価側の障害: " + state.EvaluatorFault, string.Empty);
        }

        if (!state.WebProjectFound)
        {
            return Fail(state, "R-001", "C-001", input, "Microsoft.NET.Sdk.Web を使う Web プロジェクトが見つかりません。", state.PublishDetail);
        }

        if (!state.PublishOk)
        {
            return Fail(state, "R-001", "C-001", input, $"dotnet publish が終了コード {state.PublishExitCode} で失敗しました。", state.PublishDetail);
        }

        if (!state.EntryAssemblyFound)
        {
            return Fail(state, "R-001", "C-001", input, "公開出力に実行アセンブリが見つかりません。", state.PublishDetail);
        }

        return Pass(state, "R-001", "C-001", input, "dotnet publish が成功し、公開出力に実行アセンブリが存在します。", state.PublishDetail);
    }

    private static CheckResult C002(RunState state)
    {
        const string input = "GET /";
        if (state.EvaluatorFault != null)
        {
            return Make(state, "R-001", "C-002", input, Judgement.Error, "評価側の障害: " + state.EvaluatorFault, string.Empty);
        }

        if (!state.AppReady)
        {
            return Fail(state, "R-001", "C-002", input, "アプリが HTTP で応答しませんでした。", state.AppStartDetail);
        }

        return Verdict(state, "R-001", "C-002", input, state.RootStatus == 200, $"GET / が {state.RootStatus} を返しました。", AppHost.Tail(state.RootBody, 400));
    }

    private static CheckResult C003(RunState state)
    {
        var pre = Precondition(state, "R-002", "C-003", "GET /Store");
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-002", "C-003", "GET /Store", scenario, state.Transcript("browse"));
        }

        var text = Html.Text(scenario.Store.Body);
        var missing = state.Catalog.Genres.Where(g => !text.Contains(g, StringComparison.OrdinalIgnoreCase)).ToList();
        var ok = scenario.Store.Status == 200 && missing.Count == 0;
        return Verdict(
            state,
            "R-002",
            "C-003",
            "GET /Store",
            ok,
            $"GET /Store が {scenario.Store.Status} を返し、ジャンル名の出現は {state.Catalog.Genres.Count - missing.Count}/{state.Catalog.Genres.Count} 件でした。" + (missing.Count > 0 ? $" 欠落: {string.Join(", ", missing)}" : string.Empty),
            state.Transcript("browse"));
    }

    private static CheckResult C004(RunState state)
    {
        const string input = "GET /Store/Browse?genre={10 ジャンル}";
        var pre = Precondition(state, "R-003", "C-004", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-003", "C-004", input, scenario, state.Transcript("browse"));
        }

        var mismatches = new List<string>();
        var observed = new List<string>();
        foreach (var genre in state.Catalog.Genres)
        {
            var expected = state.Catalog.CountByGenre(genre);
            var actual = scenario.GenreCounts.TryGetValue(genre, out var value) ? value : -1;
            observed.Add($"{genre}={actual}(期待 {expected})");
            if (actual != expected)
            {
                mismatches.Add($"{genre}: 実測 {actual} / 期待 {expected}");
            }
        }

        return Verdict(
            state,
            "R-003",
            "C-004",
            input,
            mismatches.Count == 0,
            "実測 " + string.Join(", ", observed),
            string.Join(" | ", mismatches));
    }

    private static CheckResult C005(RunState state)
    {
        const string input = "GET /Store/Details/1";
        var pre = Precondition(state, "R-004", "C-005", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-004", "C-005", input, scenario, state.Transcript("browse"));
        }

        var album = state.Catalog.ById(1);
        var text = Html.Text(scenario.Details1.Body);
        var ok = scenario.Details1.Status == 200 && text.Contains(album.Title, StringComparison.Ordinal);
        return Verdict(
            state,
            "R-004",
            "C-005",
            input,
            ok,
            $"GET /Store/Details/1 が {scenario.Details1.Status} を返し、タイトル '{album.Title}' の出現は {text.Contains(album.Title, StringComparison.Ordinal)} でした。",
            state.Transcript("browse"));
    }

    private static CheckResult C006(RunState state)
    {
        const string input = "プロセスを再起動し、同じ DB で /Store と注文識別子を観測する";
        var pre = Precondition(state, "R-005", "C-006", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Restart;
        if (!scenario.Ok)
        {
            return Fault(state, "R-005", "C-006", input, scenario, state.Transcript("restart"));
        }

        var genreOk = scenario.GenreCount == state.Catalog.Genres.Count;
        var rockOk = scenario.RockCount == state.Catalog.CountByGenre("Rock");
        var orderOk = scenario.OrderIdBefore.HasValue && scenario.OrderIdAfter.HasValue && scenario.OrderIdBefore.Value != scenario.OrderIdAfter.Value;
        var ok = genreOk && rockOk && orderOk;

        var observed =
            $"再起動後: ジャンル {scenario.GenreCount}/{state.Catalog.Genres.Count}、Rock のアルバム {scenario.RockCount}/{state.Catalog.CountByGenre("Rock")}。" +
            $"再起動前の注文番号 {Describe(scenario.OrderIdBefore)}、再起動後の注文番号 {Describe(scenario.OrderIdAfter)}。" +
            $"再起動: {scenario.RestartDetail}";

        return Verdict(state, "R-005", "C-006", input, ok, observed, state.Transcript("restart"));
    }

    private static CheckResult C007(RunState state)
    {
        const string input = "GET /Store/Browse?genre=Rock";
        var pre = Precondition(state, "R-006", "C-007", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-006", "C-007", input, scenario, state.Transcript("browse"));
        }

        var response = scenario.GenreBrowses["Rock"];
        var text = Html.Text(response.Body);
        var rockTitle = state.Catalog.ById(1).Title;
        var otherTitle = state.Catalog.ById(2).Title;
        var hasRock = text.Contains(rockTitle, StringComparison.Ordinal);
        var hasOther = text.Contains(otherTitle, StringComparison.Ordinal);
        var ok = response.Status == 200 && hasRock && !hasOther;

        return Verdict(
            state,
            "R-006",
            "C-007",
            input,
            ok,
            $"GET /Store/Browse?genre=Rock が {response.Status} を返し、Rock 固有 '{rockTitle}' の出現 {hasRock}、他ジャンル '{otherTitle}' の出現 {hasOther} でした。",
            state.Transcript("browse"));
    }

    private static CheckResult C008(RunState state)
    {
        const string input = "GET /Store/Browse?genre=NoSuchGenreAtAll";
        var pre = Precondition(state, "R-007", "C-008", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-007", "C-008", input, scenario, state.Transcript("browse"));
        }

        return Verdict(state, "R-007", "C-008", input, scenario.BrowseUnknown.Status == 404, $"HTTP {scenario.BrowseUnknown.Status} を返しました。", state.Transcript("browse"));
    }

    private static CheckResult C009(RunState state)
    {
        const string input = "GET /Store/Details/2";
        var pre = Precondition(state, "R-008", "C-009", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-008", "C-009", input, scenario, state.Transcript("browse"));
        }

        var album = state.Catalog.ById(2);
        var text = Html.Text(scenario.Details2.Body);
        var price = Html.Money2(album.Price);
        var hasTitle = text.Contains(album.Title, StringComparison.Ordinal);
        var hasGenre = text.Contains(album.Genre, StringComparison.OrdinalIgnoreCase);
        var hasArtist = text.Contains(album.Artist, StringComparison.OrdinalIgnoreCase);
        var hasPrice = text.Contains(price, StringComparison.Ordinal);
        var ok = scenario.Details2.Status == 200 && hasTitle && hasGenre && hasArtist && hasPrice;

        return Verdict(
            state,
            "R-008",
            "C-009",
            input,
            ok,
            $"GET /Store/Details/2 が {scenario.Details2.Status} を返し、タイトル {hasTitle} / ジャンル '{album.Genre}' {hasGenre} / アーティスト {hasArtist} / 価格 '{price}' {hasPrice} でした。",
            state.Transcript("browse"));
    }

    private static CheckResult C010(RunState state)
    {
        const string input = "GET /Store/Details/99999";
        var pre = Precondition(state, "R-009", "C-010", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-009", "C-010", input, scenario, state.Transcript("browse"));
        }

        return Verdict(state, "R-009", "C-010", input, scenario.DetailsMissing.Status == 404, $"HTTP {scenario.DetailsMissing.Status} を返しました。", state.Transcript("browse"));
    }

    private static CheckResult C011(RunState state)
    {
        const string input = "GET /";
        var pre = Precondition(state, "R-010", "C-011", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-010", "C-011", input, scenario, state.Transcript("browse"));
        }

        var text = Html.Text(scenario.Root.Body);
        var missing = state.Catalog.Genres.Where(g => !text.Contains(g, StringComparison.OrdinalIgnoreCase)).ToList();
        var cartCount = scenario.CartCountOnRoot;
        var ok = scenario.Root.Status == 200 && missing.Count == 0 && cartCount == 0;

        return Verdict(
            state,
            "R-010",
            "C-011",
            input,
            ok,
            $"GET / が {scenario.Root.Status} を返し、ジャンル名の欠落 {missing.Count} 件、'Cart (N)' の件数表示は {(cartCount.HasValue ? cartCount.Value.ToString(CultureInfo.InvariantCulture) : "未検出")} でした。",
            state.Transcript("browse"));
    }

    private static CheckResult C012(RunState state)
    {
        const string input = "GET /ShoppingCart/AddToCart/1";
        var pre = Precondition(state, "R-011", "C-012", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Browse;
        if (!scenario.Ok)
        {
            return Fault(state, "R-011", "C-012", input, scenario, state.Transcript("redirect"));
        }

        var response = scenario.AddToCartRedirect;
        var ok = response.Status >= 300 && response.Status < 400 && (response.Location ?? string.Empty).Contains("/ShoppingCart", StringComparison.OrdinalIgnoreCase);
        return Verdict(state, "R-011", "C-012", input, ok, response.Summary(), state.Transcript("redirect"));
    }

    private static CheckResult C013(RunState state)
    {
        const string input = "GET /ShoppingCart/AddToCart/1 を 2 回 → GET /ShoppingCart";
        var pre = Precondition(state, "R-012", "C-013", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Cart;
        if (!scenario.Ok)
        {
            return Fault(state, "R-012", "C-013", input, scenario, state.Transcript("cart"));
        }

        var ok = scenario.LinesAfterTwoAdds.Count == 1 && scenario.LinesAfterTwoAdds[0].Count == 2;
        return Verdict(state, "R-012", "C-013", input, ok, Scenarios.DescribeCart(scenario.LinesAfterTwoAdds) + $", 合計 {Scenarios.DescribeMoney(scenario.TotalAfterTwoAdds)}", state.Transcript("cart"));
    }

    private static CheckResult C014(RunState state)
    {
        const string input = "GET /ShoppingCart/AddToCart/1 を 3 回 → GET /ShoppingCart";
        var pre = Precondition(state, "R-013", "C-014", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Cart;
        if (!scenario.Ok)
        {
            return Fault(state, "R-013", "C-014", input, scenario, state.Transcript("cart"));
        }

        var expected = 3 * state.Catalog.ById(1).Price;
        var ok = scenario.TotalAfterThreeAdds == expected;
        return Verdict(
            state,
            "R-013",
            "C-014",
            input,
            ok,
            $"{Scenarios.DescribeCart(scenario.LinesAfterThreeAdds)}、合計の実測 {Scenarios.DescribeMoney(scenario.TotalAfterThreeAdds)} / 期待 {Html.Money2(expected)}",
            state.Transcript("cart"));
    }

    private static CheckResult C015(RunState state)
    {
        const string input = "数量 2 の明細に POST /ShoppingCart/RemoveFromCart";
        var pre = Precondition(state, "R-014", "C-015", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Cart;
        if (!scenario.Ok)
        {
            return Fault(state, "R-014", "C-015", input, scenario, state.Transcript("cart"));
        }

        var itemCount = ExtractItemCount(scenario.RemoveFromTwo.Body);
        var expected = state.Catalog.ById(1).Price;
        var ok = itemCount == 1
            && scenario.LinesAfterRemoveFromTwo.Count == 1
            && scenario.LinesAfterRemoveFromTwo[0].Count == 1
            && scenario.TotalAfterRemoveFromTwo == expected;

        return Verdict(
            state,
            "R-014",
            "C-015",
            input,
            ok,
            $"応答 {Scenarios.JsonSummary(scenario.RemoveFromTwo.Body)}（ItemCount={Describe(itemCount)}）、{Scenarios.DescribeCart(scenario.LinesAfterRemoveFromTwo)}、合計 {Scenarios.DescribeMoney(scenario.TotalAfterRemoveFromTwo)} / 期待 {Html.Money2(expected)}",
            state.Transcript("cart"));
    }

    private static CheckResult C016(RunState state)
    {
        const string input = "数量 1 の明細に POST /ShoppingCart/RemoveFromCart";
        var pre = Precondition(state, "R-015", "C-016", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Cart;
        if (!scenario.Ok)
        {
            return Fault(state, "R-015", "C-016", input, scenario, state.Transcript("cart"));
        }

        var itemCount = ExtractItemCount(scenario.RemoveFromOne.Body);
        var ok = itemCount == 0
            && scenario.LinesAfterRemoveFromOne.Count == 0
            && scenario.TotalAfterRemoveFromOne == 0m;

        return Verdict(
            state,
            "R-015",
            "C-016",
            input,
            ok,
            $"応答 {Scenarios.JsonSummary(scenario.RemoveFromOne.Body)}（ItemCount={Describe(itemCount)}）、{Scenarios.DescribeCart(scenario.LinesAfterRemoveFromOne)}、合計 {Scenarios.DescribeMoney(scenario.TotalAfterRemoveFromOne)} / 期待 0.00",
            state.Transcript("cart"));
    }

    private static CheckResult C017(RunState state)
    {
        const string input = "AddToCart/1 を 2 回、AddToCart/2 を 1 回 → GET /ShoppingCart";
        var pre = Precondition(state, "R-016", "C-017", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Order;
        if (!scenario.Ok)
        {
            return Fault(state, "R-016", "C-017", input, scenario, state.Transcript("order"));
        }

        var expected = 2 * state.Catalog.ById(1).Price + state.Catalog.ById(2).Price;
        var ok = scenario.LinesBeforeCheckout.Count == 2
            && scenario.LinesBeforeCheckout.Sum(l => l.Count) == 3
            && scenario.TotalBeforeCheckout == expected;

        return Verdict(
            state,
            "R-016",
            "C-017",
            input,
            ok,
            $"{Scenarios.DescribeCart(scenario.LinesBeforeCheckout)}、合計 {Scenarios.DescribeMoney(scenario.TotalBeforeCheckout)} / 期待 {Html.Money2(expected)}",
            state.Transcript("order"));
    }

    private static CheckResult C018(RunState state)
    {
        const string input = "セッション A で AddToCart/1 → セッション B で GET /ShoppingCart";
        var pre = Precondition(state, "R-017", "C-018", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Isolation;
        if (!scenario.Ok)
        {
            return Fault(state, "R-017", "C-018", input, scenario, state.Transcript("isolation-b"));
        }

        var ok = scenario.LinesInSessionA.Count == 1 && scenario.LinesInSessionB.Count == 0 && scenario.TotalInSessionB == 0m;
        return Verdict(
            state,
            "R-017",
            "C-018",
            input,
            ok,
            $"セッション A: {Scenarios.DescribeCart(scenario.LinesInSessionA)} 合計 {Scenarios.DescribeMoney(scenario.TotalInSessionA)}。セッション B: {Scenarios.DescribeCart(scenario.LinesInSessionB)} 合計 {Scenarios.DescribeMoney(scenario.TotalInSessionB)}",
            state.Transcript("isolation-b"));
    }

    private static CheckResult C019(RunState state)
    {
        const string input = "POST /Checkout/AddressAndPayment（promoCode=FREE、かご 2 行）";
        var pre = Precondition(state, "R-018", "C-019", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Order;
        if (!scenario.Ok)
        {
            return Fault(state, "R-018", "C-019", input, scenario, state.Transcript("order"));
        }

        var response = scenario.CheckoutPost;
        var ok = response.Status >= 300 && response.Status < 400
            && (response.Location ?? string.Empty).Contains("/Checkout/Complete/", StringComparison.OrdinalIgnoreCase)
            && scenario.OrderId.HasValue;

        return Verdict(state, "R-018", "C-019", input, ok, response.Summary() + $", 注文番号 {Describe(scenario.OrderId)}", state.Transcript("order"));
    }

    private static CheckResult C020(RunState state)
    {
        const string input = "注文確定後に同じセッションで AddToCart/2 → POST /Checkout/AddressAndPayment";
        var pre = Precondition(state, "R-019", "C-020", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Order;
        if (!scenario.Ok)
        {
            return Fault(state, "R-019", "C-020", input, scenario, state.Transcript("order"));
        }

        var ok = scenario.SecondOrderId.HasValue
            && scenario.OrderId.HasValue
            && scenario.SecondOrderId.Value != scenario.OrderId.Value;

        return Verdict(
            state,
            "R-019",
            "C-020",
            input,
            ok,
            $"1 回目の注文番号 {Describe(scenario.OrderId)}、2 回目の注文番号 {Describe(scenario.SecondOrderId)}。応答 {scenario.SecondCheckoutPost?.Summary()}",
            state.Transcript("order"));
    }

    private static CheckResult C021(RunState state)
    {
        const string input = "注文確定後に GET /ShoppingCart";
        var pre = Precondition(state, "R-020", "C-021", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Order;
        if (!scenario.Ok)
        {
            return Fault(state, "R-020", "C-021", input, scenario, state.Transcript("order"));
        }

        var ok = scenario.LinesAfterOrder.Count == 0 && scenario.TotalAfterOrder == 0m;
        return Verdict(state, "R-020", "C-021", input, ok, $"{Scenarios.DescribeCart(scenario.LinesAfterOrder)}、合計 {Scenarios.DescribeMoney(scenario.TotalAfterOrder)}", state.Transcript("order"));
    }

    private static CheckResult C022(RunState state)
    {
        const string input = "GET /Checkout/Complete/{注文番号}（注文したセッション）";
        var pre = Precondition(state, "R-021", "C-022", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Order;
        if (!scenario.Ok)
        {
            return Fault(state, "R-021", "C-022", input, scenario, state.Transcript("order"));
        }

        if (scenario.Complete == null)
        {
            return Fail(state, "R-021", "C-022", input, "注文番号が得られず、完了画面を要求できませんでした。", state.Transcript("order"));
        }

        var shown = Html.OrderNumber(scenario.Complete.Body);
        var ok = scenario.Complete.Status == 200 && shown.HasValue && shown.Value == scenario.OrderId;
        return Verdict(state, "R-021", "C-022", input, ok, $"HTTP {scenario.Complete.Status}、表示された注文番号 {Describe(shown)} / 期待 {Describe(scenario.OrderId)}", state.Transcript("order"));
    }

    private static CheckResult C023(RunState state)
    {
        const string input = "GET /Checkout/Complete/{注文番号}（別セッション）";
        var pre = Precondition(state, "R-022", "C-023", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Order;
        if (!scenario.Ok)
        {
            return Fault(state, "R-022", "C-023", input, scenario, state.Transcript("other"));
        }

        if (scenario.OtherSessionComplete == null || !scenario.OrderId.HasValue)
        {
            return Fail(state, "R-022", "C-023", input, "注文番号が得られず、別セッションの完了画面を判定できませんでした。", state.Transcript("other"));
        }

        var shown = Html.OrderNumber(scenario.OtherSessionComplete.Body);
        var ok = !shown.HasValue || shown.Value != scenario.OrderId.Value;
        return Verdict(state, "R-022", "C-023", input, ok, $"HTTP {scenario.OtherSessionComplete.Status}、別セッションで表示された注文番号 {Describe(shown)} / 他人の注文番号 {Describe(scenario.OrderId)}", state.Transcript("other"));
    }

    private static CheckResult C024(RunState state)
    {
        const string input = "POST /Checkout/AddressAndPayment（promoCode=NOT_FREE）";
        var pre = Precondition(state, "R-023", "C-024", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.InvalidCheckout;
        if (!scenario.Ok)
        {
            return Fault(state, "R-023", "C-024", input, scenario, state.Transcript("invalid"));
        }

        if (scenario.LinesBefore.Count == 0)
        {
            // かごに入れられない成果物では「かごが変わらないこと」を観測できない。
            // 前提が成立しないので不合格ではなく未評価（blocked）とする。
            return Make(state, "R-023", "C-024", input, Judgement.Blocked, "未評価: かごに明細を入れられないため、プロモコード不一致の挙動を観測できません。", state.Transcript("invalid"));
        }

        var showsForm = Html.Contains(scenario.WrongPromo.Body, "PromoCode");
        var ok = scenario.WrongPromo.Status == 200 && showsForm && scenario.LinesAfterWrongPromo.Count == scenario.LinesBefore.Count && scenario.LinesAfterWrongPromo.Count > 0;
        return Verdict(
            state,
            "R-023",
            "C-024",
            input,
            ok,
            $"HTTP {scenario.WrongPromo.Status}（リダイレクトなし）、入力フォームの再表示 {showsForm}、かごは {Scenarios.DescribeCart(scenario.LinesAfterWrongPromo)}（直前 {Scenarios.DescribeCart(scenario.LinesBefore)}）",
            state.Transcript("invalid"));
    }

    private static CheckResult C025(RunState state)
    {
        const string input = "POST /Checkout/AddressAndPayment（FirstName 空、promoCode=FREE）";
        var pre = Precondition(state, "R-024", "C-025", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.InvalidCheckout;
        if (!scenario.Ok)
        {
            return Fault(state, "R-024", "C-025", input, scenario, state.Transcript("invalid"));
        }

        if (scenario.LinesBefore.Count == 0)
        {
            return Make(state, "R-024", "C-025", input, Judgement.Blocked, "未評価: かごに明細を入れられないため、必須項目欠落の挙動を観測できません。", state.Transcript("invalid"));
        }

        var ok = scenario.MissingField.Status == 200
            && scenario.LinesAfterMissingField.Count == scenario.LinesBefore.Count
            && scenario.LinesAfterMissingField.Count > 0;
        return Verdict(
            state,
            "R-024",
            "C-025",
            input,
            ok,
            $"HTTP {scenario.MissingField.Status}（リダイレクトなし）、かごは {Scenarios.DescribeCart(scenario.LinesAfterMissingField)}（直前 {Scenarios.DescribeCart(scenario.LinesBefore)}）",
            state.Transcript("invalid"));
    }

    private static CheckResult C026(RunState state)
    {
        const string input = "ログインせずに GET /Checkout/AddressAndPayment と POST /Checkout/AddressAndPayment";
        var pre = Precondition(state, "R-025", "C-026", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Order;
        if (!scenario.Ok)
        {
            return Fault(state, "R-025", "C-026", input, scenario, state.Transcript("order"));
        }

        var formStatus = scenario.CheckoutFormGet?.Status ?? -1;
        var ok = formStatus == 200 && scenario.OrderId.HasValue;
        return Verdict(
            state,
            "R-025",
            "C-026",
            input,
            ok,
            $"認証情報を送らずに GET /Checkout/AddressAndPayment が {formStatus}、注文は {Describe(scenario.OrderId)} で成立しました。",
            state.Transcript("order"));
    }

    private static CheckResult C027(RunState state)
    {
        const string input = "起動対象プロジェクトの csproj を読む";
        var scenario = state.Static;
        if (!scenario.Ok)
        {
            return Fault(state, "R-026", "C-027", input, scenario);
        }

        var version = ParseNetVersion(scenario.TargetFramework);
        var ok = string.Equals(scenario.Sdk, "Microsoft.NET.Sdk.Web", StringComparison.OrdinalIgnoreCase)
            && version.HasValue
            && version.Value >= 8;

        return Verdict(
            state,
            "R-026",
            "C-027",
            input,
            ok,
            $"プロジェクト {Path.GetFileName(scenario.ProjectFile)}: Sdk='{scenario.Sdk}'、TargetFramework='{scenario.TargetFramework}'",
            scenario.ProjectText);
    }

    private static CheckResult C028(RunState state)
    {
        const string input = "起動対象プロジェクトの csproj に System.Web 参照がないこと";
        var scenario = state.Static;
        if (!scenario.Ok)
        {
            return Fault(state, "R-027", "C-028", input, scenario);
        }

        var version = ParseNetVersion(scenario.TargetFramework);
        var isFramework = (scenario.TargetFramework ?? string.Empty).StartsWith("net4", StringComparison.OrdinalIgnoreCase)
            || !version.HasValue;
        var ok = !scenario.HasSystemWeb && !isFramework;

        return Verdict(
            state,
            "R-027",
            "C-028",
            input,
            ok,
            $"System.Web の出現 {scenario.HasSystemWeb}、TargetFramework='{scenario.TargetFramework}'（.NET Framework 判定 {isFramework}）",
            scenario.ProjectText);
    }

    private static CheckResult C029(RunState state)
    {
        const string input = "ConnectionStrings__MusicStoreEntities で指定したパスの SQLite ファイル";
        var pre = Precondition(state, "R-028", "C-029", input);
        if (pre != null)
        {
            return pre;
        }

        var scenario = state.Static;
        if (!scenario.Ok)
        {
            return Fault(state, "R-028", "C-029", input, scenario);
        }

        return Verdict(
            state,
            "R-028",
            "C-029",
            input,
            scenario.DatabaseFileExists,
            $"指定パス {scenario.DatabasePath} のファイル存在: {scenario.DatabaseFileExists}",
            string.Empty);
    }

    private static CheckResult C030(RunState state)
    {
        const string input = "成果物ツリーを静的に走査する";
        var scenario = state.Static;
        if (!scenario.Ok)
        {
            return Fault(state, "R-029", "C-030", input, scenario);
        }

        var ok = scenario.LegacyReferences.Count == 0;
        return Verdict(
            state,
            "R-029",
            "C-030",
            input,
            ok,
            ok
                ? "成果物ツリーに MvcMusicStore / iisexpress / System.Web の記述は見つかりませんでした。"
                : $"旧実装を示す記述が {scenario.LegacyReferences.Count} 件見つかりました: {string.Join(", ", scenario.LegacyReferences.Take(10))}",
            string.Join(Environment.NewLine, scenario.LegacyReferences));
    }

    private static int? ExtractItemCount(string jsonBody)
    {
        var match = Regex.Match(jsonBody ?? string.Empty, "\"itemCount\"\\s*:\\s*(?<n>-?[0-9]+)", RegexOptions.IgnoreCase);
        return match.Success ? int.Parse(match.Groups["n"].Value, CultureInfo.InvariantCulture) : (int?)null;
    }

    private static int? ParseNetVersion(string targetFramework)
    {
        if (string.IsNullOrEmpty(targetFramework))
        {
            return null;
        }

        var match = Regex.Match(targetFramework, "^net(?<major>[0-9]+)\\.[0-9]+$", RegexOptions.IgnoreCase);
        if (match.Success)
        {
            return int.Parse(match.Groups["major"].Value, CultureInfo.InvariantCulture);
        }

        var legacy = Regex.Match(targetFramework, "^net(?<major>[0-9]+)$", RegexOptions.IgnoreCase);
        return legacy.Success ? int.Parse(legacy.Groups["major"].Value, CultureInfo.InvariantCulture) : (int?)null;
    }

    private static string Describe(int? value) => value.HasValue ? value.Value.ToString(CultureInfo.InvariantCulture) : "未取得";
}
