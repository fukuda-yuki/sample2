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

    public string EvaluationVersion { get; set; } = Program.DefaultEvaluationVersion;

    public bool ExplicitOrderContract => EvaluationVersion is "1.2.0" or "1.3.0" or "1.4.0" or "1.5.0" or "1.6.0";

    public MigrationContinuity Migration { get; set; }

    public bool AppReady { get; set; }
    public bool InitialReadinessObserved { get; set; }
    public bool InitialAppReady { get; set; }
    public bool StartupReady => EvaluationVersion=="1.6.0" && InitialReadinessObserved ? InitialAppReady : AppReady;

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

    public BrowserCartReview BrowserCartReview { get; set; }

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
    public WebResponse CartBeforeSecondCheckout { get; set; }
    public OrderStore.Probe OrderRowBeforeSecond { get; set; }
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
    public WebResponse CartBeforeCheckout { get; set; }
    public int? GenreCount { get; set; }

    public int? RockCount { get; set; }

    public int? OrderIdBefore { get; set; }

    public int? OrderIdAfter { get; set; }

    /// <summary>再起動の直前に観測した、再起動前の注文行。</summary>
    public OrderStore.Probe OrderRowBeforeRestart { get; set; }

    /// <summary>再起動後、新しい注文を作る前に観測した、同じ注文行。</summary>
    public OrderStore.Probe OrderRowAfterRestart { get; set; }

    public WebResponse CheckoutPost { get; set; }

    public string RestartDetail { get; set; } = string.Empty;
}

public sealed class InvalidCheckoutResult : ScenarioResult
{
    public List<InvalidFieldObservation> AddressCases { get; } = new();
    public bool AllMissingAddressFieldsPreserved { get; set; }
    public List<string> MissingAddressObservations { get; } = new();
    public OrderStore.Snapshot OrdersBefore { get; set; }
    public OrderStore.Snapshot OrdersAfterWrongPromo { get; set; }
    public OrderStore.Snapshot OrdersBeforeMissing { get; set; }
    public OrderStore.Snapshot OrdersAfterMissing { get; set; }
    public WebResponse CartBeforeMissing { get; set; }

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
    public bool ForeignRemovalObserved { get; set; }
    public WebResponse CartBeforeA { get; set; }
    public WebResponse CartBeforeB { get; set; }
    public WebResponse CartAfterA { get; set; }
    public WebResponse CartAfterB { get; set; }
    public List<Html.CartLine> LinesInSessionA { get; set; } = new List<Html.CartLine>();

    public decimal? TotalInSessionA { get; set; }

    public List<Html.CartLine> LinesInSessionB { get; set; } = new List<Html.CartLine>();

    public decimal? TotalInSessionB { get; set; }

    public bool ForeignRemovalPreserved { get; set; }
}

public sealed class InvalidFieldObservation
{
    public string Field { get; set; }
    public WebResponse Before { get; set; }
    public WebResponse Response { get; set; }
    public WebResponse After { get; set; }
    public OrderStore.Snapshot OrdersBefore { get; set; }
    public OrderStore.Snapshot OrdersAfter { get; set; }
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

    /// <summary>
    /// 旧実装を参照・起動する記述（設定・参照・起動処理）。コメントでの言及は含めない。
    /// </summary>
    public List<string> LegacyReferences { get; set; } = new List<string>();

    /// <summary>
    /// コメント・説明文での旧名称の言及。診断情報であり、依存の根拠にしない。
    /// </summary>
    public List<string> LegacyMentions { get; set; } = new List<string>();

    public List<string> LegacyUnresolved { get; set; } = new List<string>();
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

    private static T Guard<T>(RunState state, T result, Func<T,T> body) where T : ScenarioResult, new()
    {
        if (state.EvaluationVersion != "1.6.0") return Guard(() => body(result));
        try { return body(result); }
        catch (PreconditionException ex) { result.Fault=Judgement.Blocked; result.FaultDetail=ex.Message; }
        catch (Exception ex) { result.Fault=Judgement.Error; result.FaultDetail=ex.GetType().Name+": "+ex.Message; }
        return result;
    }

    private static void RequireReady(RunState state)
    {
        if (!state.AppReady)
        {
            throw new PreconditionException("アプリが起動していないため判定できません。詳細: " + state.AppStartDetail);
        }
    }

    public static BrowseResult RunBrowse(RunState state) => Guard(state, new BrowseResult(), result =>
    {
        RequireReady(state);
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

    public static CartResult RunCart(RunState state) => Guard(state, new CartResult(), result =>
    {
        RequireReady(state);
        var session = state.Session("cart");

        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        result.CartAfterTwoAdds = session.Get("/ShoppingCart");
        result.LinesAfterTwoAdds = Html.CartLines(result.CartAfterTwoAdds.Body,state.EvaluationVersion);
        result.TotalAfterTwoAdds = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(result.CartAfterTwoAdds.Body).Value:Html.Money(result.CartAfterTwoAdds.Body));

        if (result.LinesAfterTwoAdds.Count > 0)
        {
            result.RecordId = result.LinesAfterTwoAdds[0].RecordId;
        }

        result.RemoveFromTwo = state.EvaluationVersion=="1.6.0" && Html.ObserveCart16(result.CartAfterTwoAdds.Body).Violations.Count>0 ? null : ObserveRemoval(state.EvaluationVersion, result.LinesAfterTwoAdds, 2, result.RecordId, id =>
        {
            return session.PostForm("/ShoppingCart/RemoveFromCart", new[]
            {
                new KeyValuePair<string, string>("id", id.ToString(CultureInfo.InvariantCulture)),
            });
        });
        result.CartAfterRemoveFromTwo = session.Get("/ShoppingCart");
        result.LinesAfterRemoveFromTwo = Html.CartLines(result.CartAfterRemoveFromTwo.Body,state.EvaluationVersion);
        result.TotalAfterRemoveFromTwo = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(result.CartAfterRemoveFromTwo.Body).Value:Html.Money(result.CartAfterRemoveFromTwo.Body));

        result.RemoveFromOne = state.EvaluationVersion=="1.6.0" && Html.ObserveCart16(result.CartAfterRemoveFromTwo.Body).Violations.Count>0 ? null : ObserveRemoval(state.EvaluationVersion, result.LinesAfterRemoveFromTwo, 1, result.RecordId, id =>
        {
            return session.PostForm("/ShoppingCart/RemoveFromCart", new[]
            {
                new KeyValuePair<string, string>("id", id.ToString(CultureInfo.InvariantCulture)),
            });
        });
        result.CartAfterRemoveFromOne = session.Get("/ShoppingCart");
        result.LinesAfterRemoveFromOne = Html.CartLines(result.CartAfterRemoveFromOne.Body,state.EvaluationVersion);
        result.TotalAfterRemoveFromOne = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(result.CartAfterRemoveFromOne.Body).Value:Html.Money(result.CartAfterRemoveFromOne.Body));

        if (state.EvaluationVersion == "1.6.0") session = state.Session("cart-total");
        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        result.CartAfterThreeAdds = session.Get("/ShoppingCart");
        result.LinesAfterThreeAdds = Html.CartLines(result.CartAfterThreeAdds.Body,state.EvaluationVersion);
        result.TotalAfterThreeAdds = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(result.CartAfterThreeAdds.Body).Value:Html.Money(result.CartAfterThreeAdds.Body));

        return result;
    });

    public static bool RemovalPrecondition(IReadOnlyList<Html.CartLine> lines, int quantity) =>
        lines.Count == 1 && lines[0].AlbumId == 1 && lines[0].Count == quantity && lines[0].RecordId > 0;

    public static WebResponse ObserveRemoval(string version, IReadOnlyList<Html.CartLine> lines, int quantity,
        int historicalRecordId, Func<int, WebResponse> submit)
    {
        if (version is "1.5.0" or "1.6.0" && !RemovalPrecondition(lines, quantity)) return null;
        // The current line is the prerequisite for this distinct check. A
        // legitimate application may replace a row while decrementing it.
        return submit(version is "1.5.0" or "1.6.0" ? lines[0].RecordId : historicalRecordId);
    }

    public static WebResponse ObserveCheckout(string version, WebResponse cart, Func<WebResponse> submit) =>
        version=="1.6.0" && !(cart?.Status==200 && Html.ObserveCart16(cart.Body).Violations.Count==0 && Attribution16.Populated(Html.CartLines(cart.Body,version))) ? null : submit();

    public static OrderResult RunOrder(RunState state) => Guard(state, new OrderResult(), result =>
    {
        RequireReady(state);
        var session = state.Session("order");

        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/1");
        session.Get("/ShoppingCart/AddToCart/2");
        result.CartBeforeCheckout = session.Get("/ShoppingCart");
        result.LinesBeforeCheckout = Html.CartLines(result.CartBeforeCheckout.Body,state.EvaluationVersion);
        result.TotalBeforeCheckout = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(result.CartBeforeCheckout.Body).Value:Html.Money(result.CartBeforeCheckout.Body));

        result.CheckoutFormGet = session.Get("/Checkout/AddressAndPayment");
        result.CheckoutPost = ObserveCheckout(state.EvaluationVersion, result.CartBeforeCheckout, () => session.PostForm("/Checkout/AddressAndPayment", OrderFields("FREE")));
        result.OrderId = ParseOrderId(result.CheckoutPost?.Location);

        if (result.OrderId.HasValue)
        {
            result.Complete = session.Get("/Checkout/Complete/" + result.OrderId.Value.ToString(CultureInfo.InvariantCulture));
        }

        result.CartAfterOrder = session.Get("/ShoppingCart");
        result.LinesAfterOrder = Html.CartLines(result.CartAfterOrder.Body,state.EvaluationVersion);
        result.TotalAfterOrder = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(result.CartAfterOrder.Body).Value:Html.Money(result.CartAfterOrder.Body));

        if (result.OrderId.HasValue)
        {
            var other = state.Session("other");
            result.OtherSessionComplete = other.Get("/Checkout/Complete/" + result.OrderId.Value.ToString(CultureInfo.InvariantCulture));
        }

        if (state.EvaluationVersion == "1.6.0")
        {
            if (result.OrderId > 0) result.OrderRowBeforeSecond = OrderStore.OrderRowExists(state.Host.DatabasePath,result.OrderId.Value);
            if (Attribution16.Accepted(result.CheckoutPost,result.OrderId,state.Host.BaseUrl) && result.OrderRowBeforeSecond?.Found == true
                && Attribution16.CartReady(result.CartBeforeCheckout) && Attribution16.Populated(result.LinesBeforeCheckout)
                && Attribution16.CartReady(result.CartAfterOrder) && result.LinesAfterOrder.Count==0 && Attribution16.Money(result.CartAfterOrder.Body).Value==0m)
            {
                session.Get("/ShoppingCart/AddToCart/2");
                result.CartBeforeSecondCheckout=session.Get("/ShoppingCart");
                result.SecondCheckoutPost=ObserveCheckout(state.EvaluationVersion,result.CartBeforeSecondCheckout,
                    () => session.PostForm("/Checkout/AddressAndPayment",OrderFields("fReE")));
            }
        }
        else
        {
            session.Get("/ShoppingCart/AddToCart/2");
            result.SecondCheckoutPost=session.PostForm("/Checkout/AddressAndPayment",OrderFields(state.EvaluationVersion is "1.3.0" or "1.4.0" or "1.5.0" ? "fReE" : "FREE"));
        }
        result.SecondOrderId=ParseOrderId(result.SecondCheckoutPost?.Location);

        return result;
    });

    public static RestartResult RunRestart(RunState state, int? orderIdBefore) => Guard(state, new RestartResult { OrderIdBefore = orderIdBefore }, result =>
    {
        RequireReady(state);

        // 再起動前の注文行を、再起動の前に観測しておく。再起動後に同じ行が残って
        // いるかを見るための比較対象であり、注文番号の差では代替しない。
        if (orderIdBefore.HasValue)
        {
            result.OrderRowBeforeRestart = OrderStore.OrderRowExists(state.Host.DatabasePath, orderIdBefore.Value);
        }

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

        // 新しい注文を作る前に、再起動前の注文行が残っているかを観測する。
        // 先に注文を作ると、保持していない成果物でも番号だけは進んでしまう。
        if (orderIdBefore.HasValue)
        {
            result.OrderRowAfterRestart = OrderStore.OrderRowExists(state.Host.DatabasePath, orderIdBefore.Value);
        }

        session.Get("/ShoppingCart/AddToCart/3");
        if(state.EvaluationVersion=="1.6.0") result.CartBeforeCheckout=session.Get("/ShoppingCart");
        result.CheckoutPost=ObserveCheckout(state.EvaluationVersion,result.CartBeforeCheckout,()=>session.PostForm("/Checkout/AddressAndPayment",OrderFields("FREE")));
        result.OrderIdAfter=ParseOrderId(result.CheckoutPost?.Location);

        return result;
    });

    public static InvalidCheckoutResult RunInvalidCheckout(RunState state) => Guard(state, new InvalidCheckoutResult(), result =>
    {
        RequireReady(state);
        var session = state.Session("invalid");

        session.Get("/ShoppingCart/AddToCart/1");
        result.CartBefore = session.Get("/ShoppingCart");
        result.LinesBefore = Html.CartLines(result.CartBefore.Body,state.EvaluationVersion);

        if (state.ExplicitOrderContract) result.OrdersBefore = OrderStore.ReadIds(state.Host.DatabasePath);

        result.WrongPromo = session.PostForm("/Checkout/AddressAndPayment", OrderFields("NOT_FREE"));
        result.CartAfterWrongPromo = session.Get("/ShoppingCart");
        result.LinesAfterWrongPromo = Html.CartLines(result.CartAfterWrongPromo.Body,state.EvaluationVersion);

        if (state.ExplicitOrderContract)
        {
            result.OrdersAfterWrongPromo = OrderStore.ReadIds(state.Host.DatabasePath);
            session = state.Session("invalid-missing");
            session.Get("/ShoppingCart/AddToCart/1");
            result.CartBeforeMissing = session.Get("/ShoppingCart");
            result.OrdersBeforeMissing = OrderStore.ReadIds(state.Host.DatabasePath);
        }
        else result.CartBeforeMissing = result.CartBefore;

        result.MissingField = session.PostForm("/Checkout/AddressAndPayment", OrderFields("FREE", firstName: string.Empty));
        result.CartAfterMissingField = session.Get("/ShoppingCart");
        result.LinesAfterMissingField = Html.CartLines(result.CartAfterMissingField.Body,state.EvaluationVersion);
        if (state.ExplicitOrderContract) result.OrdersAfterMissing = OrderStore.ReadIds(state.Host.DatabasePath);

        if (state.EvaluationVersion is "1.3.0" or "1.4.0" or "1.5.0" or "1.6.0")
        {
            if(state.EvaluationVersion=="1.6.0")
            {
                foreach(var field in Attribution16.AddressFields)
                {
                    var trial=new InvalidFieldObservation {Field=field}; result.AddressCases.Add(trial);
                    var fresh=state.Session("invalid-fields-"+field);
                    fresh.Get("/ShoppingCart/AddToCart/1");trial.Before=fresh.Get("/ShoppingCart");
                    trial.OrdersBefore=OrderStore.ReadIds(state.Host.DatabasePath);
                    var data=OrderFields("FREE").ToDictionary(x=>x.Key,x=>x.Value);data[field]="";
                    trial.Response=fresh.PostForm("/Checkout/AddressAndPayment",data);
                    trial.After=fresh.Get("/ShoppingCart");trial.OrdersAfter=OrderStore.ReadIds(state.Host.DatabasePath);
                }
                return result;
            }
            var addressSession = state.Session("invalid-fields");
            addressSession.Get("/ShoppingCart/AddToCart/1");
            var originalCart = addressSession.Get("/ShoppingCart");
            var originalOrders = OrderStore.ReadIds(state.Host.DatabasePath);
            result.AllMissingAddressFieldsPreserved = true;
            foreach (var field in new[] { "FirstName", "LastName", "Address", "City", "State", "PostalCode", "Country", "Phone", "Email" })
            {
                var data = OrderFields("FREE").ToDictionary(x => x.Key, x => x.Value); data[field] = "";
                var response = addressSession.PostForm("/Checkout/AddressAndPayment", data);
                var cart = addressSession.Get("/ShoppingCart");
                var orders = OrderStore.ReadIds(state.Host.DatabasePath);
                var accepted = response.Status == 200 && Html.HasCheckoutForm(response.Body)
                    && Html.SameCart(originalCart.Body, cart.Body) && originalOrders.SameAs(orders);
                result.MissingAddressObservations.Add(field + ": invalid input preserves cart/orders and form=" + accepted);
                result.AllMissingAddressFieldsPreserved &= accepted;
            }
        }

        return result;
    });

    public static IsolationResult RunIsolation(RunState state) => Guard(state, new IsolationResult(), result =>
    {
        RequireReady(state);
        var sessionA = state.Session("isolation-a");
        var sessionB = state.Session("isolation-b");

        sessionA.Get("/ShoppingCart/AddToCart/1");
        var cartA = sessionA.Get("/ShoppingCart");
        result.CartBeforeA=cartA;
        result.LinesInSessionA = Html.CartLines(cartA.Body,state.EvaluationVersion);
        result.TotalInSessionA = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(cartA.Body).Value:Html.Money(cartA.Body));

        var cartB = sessionB.Get("/ShoppingCart");
        result.CartBeforeB=cartB;
        result.LinesInSessionB = Html.CartLines(cartB.Body,state.EvaluationVersion);
        result.TotalInSessionB = (state.EvaluationVersion=="1.6.0"?Attribution16.Money(cartB.Body).Value:Html.Money(cartB.Body));

        if (state.EvaluationVersion is "1.3.0" or "1.4.0" or "1.5.0" or "1.6.0" && result.LinesInSessionA.Count == 1
            && (state.EvaluationVersion!="1.6.0" || cartA.Status==200 && cartB.Status==200
                && Html.ObserveCart16(cartA.Body).Violations.Count==0 && Html.ObserveCart16(cartB.Body).Violations.Count==0 && Attribution16.Populated(result.LinesInSessionA)))
        {
            sessionB.PostForm("/ShoppingCart/RemoveFromCart", new Dictionary<string,string>
            { ["id"] = result.LinesInSessionA[0].RecordId.ToString(CultureInfo.InvariantCulture) });
            result.ForeignRemovalObserved=true;
            var afterA = sessionA.Get("/ShoppingCart");
            result.CartAfterA=afterA;
            var afterB = sessionB.Get("/ShoppingCart");
            result.CartAfterB=afterB;
            result.ForeignRemovalPreserved = (state.EvaluationVersion=="1.6.0"
                ? Html.CartLines(cartA.Body,state.EvaluationVersion).Select(x=>(x.AlbumId,x.Count)).OrderBy(x=>x).SequenceEqual(Html.CartLines(afterA.Body,state.EvaluationVersion).Select(x=>(x.AlbumId,x.Count)).OrderBy(x=>x))
                    && Attribution16.Money(cartA.Body).Value.HasValue && Attribution16.Money(cartA.Body).Value==Attribution16.Money(afterA.Body).Value
                : Html.SameCart(cartA.Body, afterA.Body))
                && Html.CartLines(cartB.Body,state.EvaluationVersion).Select(x => (x.RecordId, x.AlbumId, x.Count))
                    .SequenceEqual(Html.CartLines(afterB.Body,state.EvaluationVersion).Select(x => (x.RecordId, x.AlbumId, x.Count)))
                && (state.EvaluationVersion=="1.6.0"?Attribution16.Money(cartB.Body).Value:Html.Money(cartB.Body)).HasValue
                && (state.EvaluationVersion=="1.6.0"?Attribution16.Money(cartB.Body).Value:Html.Money(cartB.Body))
                    == (state.EvaluationVersion=="1.6.0"?Attribution16.Money(afterB.Body).Value:Html.Money(afterB.Body));
        }

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
        var project = System.Xml.Linq.XDocument.Parse(result.ProjectText);
        result.TargetFramework = project.Descendants().FirstOrDefault(e => e.Name.LocalName == "TargetFramework")?.Value.Trim();
        result.Sdk = project.Root?.Attribute("Sdk")?.Value
            ?? project.Descendants().FirstOrDefault(e => e.Name.LocalName == "Sdk")?.Attribute("Name")?.Value;
        result.HasSystemWeb = project.Descendants().Where(e => e.Name.LocalName is "Reference" or "PackageReference")
            .Any(e => (e.Attribute("Include")?.Value ?? "").StartsWith("System.Web", StringComparison.OrdinalIgnoreCase));

        result.DatabasePath = state.Host.DatabasePath;

        var scan = LegacyScan.Scan(state.ArtifactPath);
        result.LegacyReferences = scan.References;
        result.LegacyMentions = scan.Mentions;
        result.LegacyUnresolved = scan.Unresolved;

        return result;
    });

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
