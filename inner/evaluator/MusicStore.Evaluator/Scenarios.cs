using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace MusicStore.Evaluator;

public sealed class RunState : IDisposable
{
    private readonly Dictionary<string, WebSession> sessions = new Dictionary<string, WebSession>(StringComparer.Ordinal);

    public AppHost Host { get; set; }

    public Ledger Ledger { get; set; }

    public Catalog Catalog { get; set; }

    public string ArtifactPath { get; set; }

    public bool AppReady { get; set; }

    public string AppStartDetail { get; set; } = string.Empty;

    public string EvaluatorFault { get; set; }

    public bool DotnetAvailable { get; set; }

    public string DotnetVersion { get; set; } = string.Empty;

    public bool WebProjectFound { get; set; }

    public bool PublishOk { get; set; }

    public int PublishExitCode { get; set; }

    public string PublishDetail { get; set; } = string.Empty;

    public bool EntryAssemblyFound { get; set; }

    public int RootStatus { get; set; }

    public string RootBody { get; set; } = string.Empty;

    public BrowseResult Browse { get; set; }

    public CartResult Cart { get; set; }

    public OrderResult Order { get; set; }

    public RestartResult Restart { get; set; }

    public InvalidCheckoutResult InvalidCheckout { get; set; }

    public IsolationResult Isolation { get; set; }

    public StaticResult Static { get; set; }

    public List<string> Faults { get; } = new List<string>();

    public WebSession Session(string name)
    {
        if (!sessions.TryGetValue(name, out var session))
        {
            session = new WebSession(Host.BaseUrl);
            sessions[name] = session;
        }

        return session;
    }

    public string Transcript(string name) => sessions.TryGetValue(name, out var s) ? s.Dump() : string.Empty;

    public void Dispose()
    {
        foreach (var session in sessions.Values)
        {
            session.Dispose();
        }
    }
}

public abstract class ScenarioResult
{
    public string Fault { get; set; }

    public string FaultDetail { get; set; } = string.Empty;

    public bool Ok => Fault == null;
}

public sealed class BrowseResult : ScenarioResult
{
    public WebResponse Root { get; set; }

    public int? CartCountOnRoot { get; set; }

    public WebResponse Store { get; set; }

    public Dictionary<string, WebResponse> GenreBrowses { get; } = new Dictionary<string, WebResponse>(StringComparer.Ordinal);

    public Dictionary<string, int> GenreCounts { get; } = new Dictionary<string, int>(StringComparer.Ordinal);

    public WebResponse BrowseUnknown { get; set; }

    public WebResponse Details1 { get; set; }

    public WebResponse Details2 { get; set; }

    public WebResponse DetailsMissing { get; set; }

    public WebResponse AddToCartRedirect { get; set; }
}

public sealed class CartResult : ScenarioResult
{
    public WebResponse CartAfterTwoAdds { get; set; }

    public List<Html.CartLine> LinesAfterTwoAdds { get; set; } = new List<Html.CartLine>();

    public decimal? TotalAfterTwoAdds { get; set; }

    public int RecordId { get; set; }

    public WebResponse RemoveFromTwo { get; set; }

    public WebResponse CartAfterRemoveFromTwo { get; set; }

    public List<Html.CartLine> LinesAfterRemoveFromTwo { get; set; } = new List<Html.CartLine>();

    public decimal? TotalAfterRemoveFromTwo { get; set; }

    public WebResponse RemoveFromOne { get; set; }

    public WebResponse CartAfterRemoveFromOne { get; set; }

    public List<Html.CartLine> LinesAfterRemoveFromOne { get; set; } = new List<Html.CartLine>();

    public decimal? TotalAfterRemoveFromOne { get; set; }

    public WebResponse CartAfterThreeAdds { get; set; }

    public List<Html.CartLine> LinesAfterThreeAdds { get; set; } = new List<Html.CartLine>();

    public decimal? TotalAfterThreeAdds { get; set; }
}

public sealed class OrderResult : ScenarioResult
{
    public WebResponse CartBeforeCheckout { get; set; }

    public List<Html.CartLine> LinesBeforeCheckout { get; set; } = new List<Html.CartLine>();

    public decimal? TotalBeforeCheckout { get; set; }

    public WebResponse CheckoutFormGet { get; set; }

    public WebResponse CheckoutPost { get; set; }

    public int? OrderId { get; set; }

    public WebResponse Complete { get; set; }

    public WebResponse CartAfterOrder { get; set; }

    public List<Html.CartLine> LinesAfterOrder { get; set; } = new List<Html.CartLine>();

    public decimal? TotalAfterOrder { get; set; }

    public WebResponse OtherSessionComplete { get; set; }

    public WebResponse SecondCheckoutPost { get; set; }

    public int? SecondOrderId { get; set; }
}

public sealed class RestartResult : ScenarioResult
{
    public int? GenreCount { get; set; }

    public int? RockCount { get; set; }

    public int? OrderIdBefore { get; set; }

    public int? OrderIdAfter { get; set; }

    public WebResponse CheckoutPost { get; set; }

    public string RestartDetail { get; set; } = string.Empty;
}

public sealed class InvalidCheckoutResult : ScenarioResult
{
    public WebResponse CartBefore { get; set; }

    public List<Html.CartLine> LinesBefore { get; set; } = new List<Html.CartLine>();

    public WebResponse WrongPromo { get; set; }

    public WebResponse CartAfterWrongPromo { get; set; }

    public List<Html.CartLine> LinesAfterWrongPromo { get; set; } = new List<Html.CartLine>();

    public WebResponse MissingField { get; set; }

    public WebResponse CartAfterMissingField { get; set; }

    public List<Html.CartLine> LinesAfterMissingField { get; set; } = new List<Html.CartLine>();
}

public sealed class IsolationResult : ScenarioResult
{
    public List<Html.CartLine> LinesInSessionA { get; set; } = new List<Html.CartLine>();

    public decimal? TotalInSessionA { get; set; }

    public List<Html.CartLine> LinesInSessionB { get; set; } = new List<Html.CartLine>();

    public decimal? TotalInSessionB { get; set; }
}

public sealed class StaticResult : ScenarioResult
{
    public string ProjectFile { get; set; }

    public string ProjectText { get; set; }

    public string TargetFramework { get; set; }

    public string Sdk { get; set; }

    public bool HasSystemWeb { get; set; }

    /// <summary>
    /// 指定パスに SQLite ファイルが作られたか。静的走査の時点ではアプリがまだ
    /// 起動していないため、値ではなく参照のたびに測る（C-029）。
    /// </summary>
    public bool DatabaseFileExists => !string.IsNullOrEmpty(DatabasePath) && File.Exists(DatabasePath);

    public string DatabasePath { get; set; }

    public List<string> LegacyReferences { get; set; } = new List<string>();
}

public static class Scenarios
{
    private static readonly Regex OrderIdRegex = new Regex("/Checkout/Complete/(?<id>\\d+)", RegexOptions.IgnoreCase);

    public static IEnumerable<KeyValuePair<string, string>> OrderFields(string promoCode, string firstName = "Ada")
    {
        return new List<KeyValuePair<string, string>>
        {
            new KeyValuePair<string, string>("FirstName", firstName),
            new KeyValuePair<string, string>("LastName", "Lovelace"),
            new KeyValuePair<string, string>("Address", "1 Analytical Way"),
            new KeyValuePair<string, string>("City", "London"),
            new KeyValuePair<string, string>("State", "LDN"),
            new KeyValuePair<string, string>("PostalCode", "10001"),
            new KeyValuePair<string, string>("Country", "UK"),
            new KeyValuePair<string, string>("Phone", "555-0100"),
            new KeyValuePair<string, string>("Email", "ada@example.com"),
            new KeyValuePair<string, string>("PromoCode", promoCode),
        };
    }

    public static int? ParseOrderId(string location)
    {
        if (string.IsNullOrEmpty(location))
        {
            return null;
        }

        var match = OrderIdRegex.Match(location);
        return match.Success ? int.Parse(match.Groups["id"].Value, CultureInfo.InvariantCulture) : (int?)null;
    }

    private static T Guard<T>(Func<T> body) where T : ScenarioResult, new()
    {
        try
        {
            return body();
        }
        catch (PreconditionException ex)
        {
            return new T { Fault = Judgement.Blocked, FaultDetail = ex.Message };
        }
        catch (Exception ex)
        {
            return new T { Fault = Judgement.Error, FaultDetail = ex.GetType().Name + ": " + ex.Message };
        }
    }

    private static void RequireReady(RunState state)
    {
        if (!state.AppReady)
        {
            throw new PreconditionException("アプリが起動していないため判定できません。詳細: " + state.AppStartDetail);
        }
    }

    public static BrowseResult RunBrowse(RunState state) => Guard(() =>
    {
        RequireReady(state);
        var result = new BrowseResult();
        var session = state.Session("browse");

        result.Root = session.Get("/");
        result.CartCountOnRoot = Html.CartCount(result.Root.Body);
        result.Store = session.Get("/Store");

        foreach (var genre in state.Catalog.Genres)
        {
            var response = session.Get("/Store/Browse?genre=" + Uri.EscapeDataString(genre));
            result.GenreBrowses[genre] = response;
            result.GenreCounts[genre] = Html.AlbumIds(response.Body).Distinct().Count();
        }

        result.BrowseUnknown = session.Get("/Store/Browse?genre=NoSuchGenreAtAll");
        result.Details1 = session.Get("/Store/Details/1");
        result.Details2 = session.Get("/Store/Details/2");
        result.DetailsMissing = session.Get("/Store/Details/99999");

        var redirectSession = state.Session("redirect");
        result.AddToCartRedirect = redirectSession.Get("/ShoppingCart/AddToCart/1");

        return result;
    });

    public static CartResult RunCart(RunState state) => Guard(() =>
    {
        RequireReady(state);
        var result = new CartResult();
        var session = state.Session("cart");

        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        result.CartAfterTwoAdds = session.Get("/ShoppingCart");
        result.LinesAfterTwoAdds = Html.CartLines(result.CartAfterTwoAdds.Body);
        result.TotalAfterTwoAdds = Html.Money(result.CartAfterTwoAdds.Body);

        if (result.LinesAfterTwoAdds.Count > 0)
        {
            result.RecordId = result.LinesAfterTwoAdds[0].RecordId;
        }

        result.RemoveFromTwo = session.PostForm("/ShoppingCart/RemoveFromCart", new[]
        {
            new KeyValuePair<string, string>("id", result.RecordId.ToString(CultureInfo.InvariantCulture)),
        });
        result.CartAfterRemoveFromTwo = session.Get("/ShoppingCart");
        result.LinesAfterRemoveFromTwo = Html.CartLines(result.CartAfterRemoveFromTwo.Body);
        result.TotalAfterRemoveFromTwo = Html.Money(result.CartAfterRemoveFromTwo.Body);

        result.RemoveFromOne = session.PostForm("/ShoppingCart/RemoveFromCart", new[]
        {
            new KeyValuePair<string, string>("id", result.RecordId.ToString(CultureInfo.InvariantCulture)),
        });
        result.CartAfterRemoveFromOne = session.Get("/ShoppingCart");
        result.LinesAfterRemoveFromOne = Html.CartLines(result.CartAfterRemoveFromOne.Body);
        result.TotalAfterRemoveFromOne = Html.Money(result.CartAfterRemoveFromOne.Body);

        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        result.CartAfterThreeAdds = session.Get("/ShoppingCart");
        result.LinesAfterThreeAdds = Html.CartLines(result.CartAfterThreeAdds.Body);
        result.TotalAfterThreeAdds = Html.Money(result.CartAfterThreeAdds.Body);

        return result;
    });

    public static OrderResult RunOrder(RunState state) => Guard(() =>
    {
        RequireReady(state);
        var result = new OrderResult();
        var session = state.Session("order");

        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/2");
        result.CartBeforeCheckout = session.Get("/ShoppingCart");
        result.LinesBeforeCheckout = Html.CartLines(result.CartBeforeCheckout.Body);
        result.TotalBeforeCheckout = Html.Money(result.CartBeforeCheckout.Body);

        result.CheckoutFormGet = session.Get("/Checkout/AddressAndPayment");
        result.CheckoutPost = session.PostForm("/Checkout/AddressAndPayment", OrderFields("FREE"));
        result.OrderId = ParseOrderId(result.CheckoutPost.Location);

        if (result.OrderId.HasValue)
        {
            result.Complete = session.Get("/Checkout/Complete/" + result.OrderId.Value.ToString(CultureInfo.InvariantCulture));
        }

        result.CartAfterOrder = session.Get("/ShoppingCart");
        result.LinesAfterOrder = Html.CartLines(result.CartAfterOrder.Body);
        result.TotalAfterOrder = Html.Money(result.CartAfterOrder.Body);

        if (result.OrderId.HasValue)
        {
            var other = state.Session("other");
            result.OtherSessionComplete = other.Get("/Checkout/Complete/" + result.OrderId.Value.ToString(CultureInfo.InvariantCulture));
        }

        session.Get("/ShoppingCart/AddToCart/2");
        result.SecondCheckoutPost = session.PostForm("/Checkout/AddressAndPayment", OrderFields("FREE"));
        result.SecondOrderId = ParseOrderId(result.SecondCheckoutPost.Location);

        return result;
    });

    public static RestartResult RunRestart(RunState state, int? orderIdBefore) => Guard(() =>
    {
        RequireReady(state);
        var result = new RestartResult { OrderIdBefore = orderIdBefore };

        state.Host.Stop();
        state.Host.Start();
        var (ready, detail) = state.Host.WaitReady(TimeSpan.FromSeconds(60));
        result.RestartDetail = detail;
        if (!ready)
        {
            state.AppReady = false;
            state.AppStartDetail = "再起動後: " + detail;
            throw new PreconditionException("再起動後にアプリが応答しません。詳細: " + detail);
        }

        var session = state.Session("restart");
        var store = session.Get("/Store");
        result.GenreCount = state.Catalog.Genres.Count(g => Html.Contains(store.Body, g));

        var rock = session.Get("/Store/Browse?genre=Rock");
        result.RockCount = Html.AlbumIds(rock.Body).Distinct().Count();

        session.Get("/ShoppingCart/AddToCart/3");
        result.CheckoutPost = session.PostForm("/Checkout/AddressAndPayment", OrderFields("FREE"));
        result.OrderIdAfter = ParseOrderId(result.CheckoutPost.Location);

        return result;
    });

    public static InvalidCheckoutResult RunInvalidCheckout(RunState state) => Guard(() =>
    {
        RequireReady(state);
        var result = new InvalidCheckoutResult();
        var session = state.Session("invalid");

        session.Get("/ShoppingCart/AddToCart/1");
        result.CartBefore = session.Get("/ShoppingCart");
        result.LinesBefore = Html.CartLines(result.CartBefore.Body);

        result.WrongPromo = session.PostForm("/Checkout/AddressAndPayment", OrderFields("NOT_FREE"));
        result.CartAfterWrongPromo = session.Get("/ShoppingCart");
        result.LinesAfterWrongPromo = Html.CartLines(result.CartAfterWrongPromo.Body);

        result.MissingField = session.PostForm("/Checkout/AddressAndPayment", OrderFields("FREE", firstName: string.Empty));
        result.CartAfterMissingField = session.Get("/ShoppingCart");
        result.LinesAfterMissingField = Html.CartLines(result.CartAfterMissingField.Body);

        return result;
    });

    public static IsolationResult RunIsolation(RunState state) => Guard(() =>
    {
        RequireReady(state);
        var result = new IsolationResult();
        var sessionA = state.Session("isolation-a");
        var sessionB = state.Session("isolation-b");

        sessionA.Get("/ShoppingCart/AddToCart/1");
        var cartA = sessionA.Get("/ShoppingCart");
        result.LinesInSessionA = Html.CartLines(cartA.Body);
        result.TotalInSessionA = Html.Money(cartA.Body);

        var cartB = sessionB.Get("/ShoppingCart");
        result.LinesInSessionB = Html.CartLines(cartB.Body);
        result.TotalInSessionB = Html.Money(cartB.Body);

        return result;
    });

    public static StaticResult RunStatic(RunState state) => Guard(() =>
    {
        var result = new StaticResult();
        result.ProjectFile = state.Host.WebProjectPath;
        if (string.IsNullOrEmpty(result.ProjectFile))
        {
            throw new PreconditionException("Microsoft.NET.Sdk.Web を使う Web プロジェクトが見つかりません。");
        }

        result.ProjectText = File.ReadAllText(result.ProjectFile);
        var tfm = Regex.Match(result.ProjectText, "<TargetFramework>(?<tfm>[^<]+)</TargetFramework>", RegexOptions.IgnoreCase);
        result.TargetFramework = tfm.Success ? tfm.Groups["tfm"].Value.Trim() : null;
        var sdk = Regex.Match(result.ProjectText, "Sdk\\s*=\\s*\"(?<sdk>[^\"]+)\"", RegexOptions.IgnoreCase);
        result.Sdk = sdk.Success ? sdk.Groups["sdk"].Value : null;
        result.HasSystemWeb = Regex.IsMatch(result.ProjectText, "System\\.Web", RegexOptions.IgnoreCase);

        result.DatabasePath = state.Host.DatabasePath;

        result.LegacyReferences = FindLegacyReferences(state.ArtifactPath);

        return result;
    });

    private static readonly string[] ScannedExtensions = { ".csproj", ".sln", ".cs", ".cshtml", ".config", ".props", ".targets", ".json" };

    /// <summary>
    /// 旧実装を「参照または起動する」記述。名前空間やアセンブリ名に旧名称を使うこと自体は
    /// 移行の妨げではないので、名前の一致ではなく参照・起動の記述を見る。
    /// ヒューリスティックであり、間接的なラッパー化を証明しない（docs/quality-spec.md §7.2）。
    /// </summary>
    private static readonly Regex[] LegacySignals =
    {
        new Regex(@"MvcMusicStore\.(?:exe|dll|pdb|csproj|sln)\b", RegexOptions.IgnoreCase),
        new Regex(@"\bMVC-Music-Store\b", RegexOptions.IgnoreCase),
        new Regex(@"\biisexpress\b", RegexOptions.IgnoreCase),
        new Regex(@"\bSystem\.Web\b", RegexOptions.IgnoreCase),
        new Regex(@"\bnet4[0-9]{0,2}\b", RegexOptions.IgnoreCase),
        new Regex(@"\bTargetFrameworkVersion\b", RegexOptions.IgnoreCase),
        new Regex(@"\bGlobal\.asax\b", RegexOptions.IgnoreCase),
        new Regex(@"\bpackages\.config\b", RegexOptions.IgnoreCase),
    };

    /// <summary>
    /// 成果物ツリーを静的に走査し、旧実装への参照・起動の記述を探す。
    /// </summary>
    public static List<string> FindLegacyReferences(string artifactPath)
    {
        var found = new List<string>();
        foreach (var file in Directory.EnumerateFiles(artifactPath, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(artifactPath, file);
            var parts = relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (parts.Any(p => p.Equals("bin", StringComparison.OrdinalIgnoreCase) || p.Equals("obj", StringComparison.OrdinalIgnoreCase) || p.Equals("wwwroot", StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            var extension = Path.GetExtension(file);
            if (!ScannedExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase))
            {
                continue;
            }

            string text;
            try
            {
                text = File.ReadAllText(file);
            }
            catch (Exception)
            {
                continue;
            }

            foreach (var signal in LegacySignals)
            {
                foreach (Match match in signal.Matches(text))
                {
                    found.Add(relative + " :: " + match.Value);
                }
            }
        }

        return found.Distinct().OrderBy(x => x, StringComparer.Ordinal).ToList();
    }

    public static string DescribeCart(IEnumerable<Html.CartLine> lines)
    {
        var list = lines.ToList();
        if (list.Count == 0)
        {
            return "明細 0 行";
        }

        return "明細 " + list.Count + " 行 (" + string.Join(", ", list.Select(l => $"album={l.AlbumId} count={l.Count}")) + ")";
    }

    public static string DescribeMoney(decimal? value) => value.HasValue ? Html.Money2(value.Value) : "未検出";

    public static string JsonSummary(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return "(空)";
        }

        var builder = new StringBuilder();
        foreach (Match match in Regex.Matches(body, "\"(?<key>[A-Za-z]+)\"\\s*:\\s*(?<value>\"[^\"]*\"|-?[0-9.]+)"))
        {
            if (builder.Length > 0)
            {
                builder.Append(", ");
            }

            builder.Append(match.Groups["key"].Value).Append('=').Append(match.Groups["value"].Value.Trim('"'));
        }

        return builder.Length > 0 ? builder.ToString() : AppHost.Tail(body, 200);
    }
}
