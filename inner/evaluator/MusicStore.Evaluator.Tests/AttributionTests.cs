using MusicStore.Evaluator;

static class AttributionTests
{
    static WebResponse Response(int status = 200, string body = "", string location = null) => new() { Status = status, Body = body, Location = location };
    static string Cart(int count, string total = "21.75", int album = 1) =>
        (count == 0 ? "" : $"<table><tr id='row-7'><td><a href='/Store/Details/{album}'>Album</a></td><td id='item-count-7'>{count}</td></tr></table>")
        + $"<b id='cart-total'>{total}</b>";
    static string Form => "<form>"+string.Concat(Attribution16.AddressFields.Append("PromoCode").Select(f=>$"<input name='{f}'>"))+"</form>";
    static RunState State(string version = "1.6.0") => new() { AppReady = true, EvaluationVersion = version,
        Catalog = new() { Genres = new() { "Rock" }, Albums = new() { new() { AlbumId = 1, Price = 7.25m, Genre = "Rock",Title="Rock album",Artist="Artist A" }, new() { AlbumId = 2, Price = 7.25m,Title="Other album",Genre="Jazz",Artist="Artist B" }, new() { AlbumId = 3, Price = 5m } } },
        Ledger = new() { SpecVersion = version, Requirements = Enumerable.Range(1,31).Select(i => new LedgerRequirement { Id = $"R-{i:000}", Severity = "critical" }).ToList() },
        Cart = new(), Order = new(), Restart = new(), InvalidCheckout = new(), Isolation = new() };
    public static void Run(Action<string,bool> check)
    {
        using var s = State();
        CheckResult Result(string id) => Checks.Registry[id](s);
        s.Cart.CartAfterThreeAdds = Response(body: Cart(5,"36.25")); s.Cart.LinesAfterThreeAdds = Html.CartLines(s.Cart.CartAfterThreeAdds.Body); s.Cart.TotalAfterThreeAdds=36.25m;
        check("1.6 C014 arithmetic does not blame residual cart quantities", Result("C-014").Judgement == Judgement.Pass);
        s.EvaluationVersion="1.5.0";
        check("1.5 fixed-three historical arithmetic label remains unchanged", Result("C-014").Judgement == Judgement.Fail);
        s.EvaluationVersion="1.6.0"; s.Cart.CartAfterThreeAdds=Response(body:Cart(3,"$21.75")); s.Cart.LinesAfterThreeAdds=Html.CartLines(s.Cart.CartAfterThreeAdds.Body);
        check("1.6 unambiguous currency prefix retains correct total",Result("C-014").Judgement==Judgement.Pass);
        s.Cart.CartAfterThreeAdds=Response(body:Cart(3,"$21.74"));
        check("1.6 wrong currency-prefixed amount remains finite failure",Result("C-014").Judgement==Judgement.Fail);
        s.Cart.CartAfterThreeAdds=Response(body:Cart(0,"0.00")); s.Cart.LinesAfterThreeAdds.Clear();
        check("1.6 empty setup cannot pass or fail multiplication check",Result("C-014").Judgement==Judgement.Blocked);
        s.Cart.CartAfterThreeAdds=Response(body:Cart(3,"21.7")); s.Cart.LinesAfterThreeAdds=Html.CartLines(s.Cart.CartAfterThreeAdds.Body);
        check("1.6 genuine wrong fractional digits remain finite failure",Result("C-014").Judgement==Judgement.Fail);
        s.Cart.CartAfterThreeAdds=Response(body:Cart(3,"21.75 or 30.00"));
        check("1.6 ambiguous amounts are unobserved rather than invented numeric mismatch",Result("C-014").Judgement==Judgement.Blocked);
        s.Order.CheckoutPost=Response(302,location:"/Checkout/Complete/42"); s.Order.OrderId=42;
        s.Order.CartBeforeCheckout=Response(body:Cart(0,"0.00"));
        var mixed=Result("C-017");
        check("1.6 missing mixed basket remains formation failure with arithmetic unknown",mixed.Judgement==Judgement.Fail && mixed.UnknownObservations.Count>0 && !mixed.Observation.Contains("Mixed-cart independent effective price total: violated"));
        check("1.6 empty purchase cannot falsely pass checkout",Result("C-019").Judgement==Judgement.Blocked);
        s.Order.CartAfterOrder=Response(body:Cart(0,"0.00")); s.Order.TotalAfterOrder=0m;
        check("1.6 empty setup cannot vacuously pass cart clearing",Result("C-021").Judgement==Judgement.Blocked);
        s.Order.OrderId=null; s.Order.Complete=null; s.Order.OtherSessionComplete=null;
        check("1.6 absent owned order cannot prove completion or isolation failure",Result("C-022").Judgement==Judgement.Blocked && Result("C-023").Judgement==Judgement.Blocked);
        s.Order.CartBeforeCheckout=Response(body:Cart(2,"14.50")); s.Order.LinesBeforeCheckout=Html.CartLines(s.Order.CartBeforeCheckout.Body);
        s.Order.CheckoutPost=Response(400); s.Order.CheckoutFormGet=Response();
        check("1.6 valid nonempty checkout HTTP400 remains real end-to-end failure",Result("C-019").Judgement==Judgement.Fail && Result("C-026").Judgement==Judgement.Fail);
        check("1.6 failed first purchase does not prove second lifecycle failure",Result("C-020").Judgement==Judgement.Blocked);
        s.Order.OrderId=42; s.Order.CheckoutPost=Response(302,location:"/Checkout/Complete/42"); s.Order.OrderRowBeforeSecond=new() {Status=OrderStore.ProbeStatus.Found}; s.Order.Complete=Response(body:"<b id='order-number'>42</b>");s.Order.OtherSessionComplete=Response(404);
        s.Order.CartBeforeCheckout=Response(body:Cart(0,"0.00")); s.Order.LinesBeforeCheckout.Clear();
        check("1.6 independent owned ID completion observations survive missing basket",Result("C-022").Judgement==Judgement.Pass && Result("C-023").Judgement==Judgement.Pass);
        s.Isolation.LinesInSessionA.Clear(); s.Isolation.TotalInSessionB=0m;s.Isolation.CartBeforeA=Response(body:Cart(0,"0.00"));s.Isolation.CartBeforeB=Response(body:Cart(0,"0.00"));
        check("1.6 absent populated session is not an isolation failure",Result("C-018").Judgement==Judgement.Blocked && Result("C-032").Judgement==Judgement.Blocked);
        s.Isolation.LinesInSessionB=Html.CartLines(Cart(1,"7.25"));s.Isolation.CartBeforeB=Response(body:Cart(1,"7.25"));
        var leakage=Result("C-018"); check("1.6 finite foreign cart leakage survives missing owned setup",leakage.Judgement==Judgement.Fail && leakage.UnknownObservations.Count>0);
        s.InvalidCheckout.CartBefore=Response(body:Cart(0,"0.00"));s.InvalidCheckout.WrongPromo=Response(body:Form);s.InvalidCheckout.CartAfterWrongPromo=Response(body:Cart(0,"0.00"));
        s.InvalidCheckout.OrdersBefore=new() {Status=OrderStore.ProbeStatus.Found};s.InvalidCheckout.OrdersAfterWrongPromo=new() {Status=OrderStore.ProbeStatus.Found};
        check("1.6 invalid form success cannot fill missing cart-preservation predicate",Result("C-024").Judgement==Judgement.Blocked);
        s.InvalidCheckout.WrongPromo=Response(500); var invalid=Result("C-024");
        check("1.6 actual invalid HTTP500 survives absent cart setup",invalid.Judgement==Judgement.Fail && invalid.UnknownObservations.Count>0);
        s.InvalidCheckout.OrdersAfterWrongPromo.Status=OrderStore.ProbeStatus.Unreadable;
        check("1.6 invalid finite failure coexists with SQL observation fault",Result("C-024").Judgement==Judgement.Fail && Result("C-024").ObservationFaults.Count>0);
        s.InvalidCheckout.AddressCases.Add(new() {Field="FirstName",Before=Response(body:Cart(0,"0.00")),After=Response(body:Cart(0,"0.00")),Response=Response(body:Form),OrdersBefore=new() {Status=OrderStore.ProbeStatus.Found},OrdersAfter=new() {Status=OrderStore.ProbeStatus.Found}});
        check("1.6 missing-field empty setup is unknown rather than SameCart false failure",Result("C-033").Judgement==Judgement.Blocked);
        s.InvalidCheckout.AddressCases[0].Response.Status=500;
        check("1.6 one observed missing-field HTTP500 remains finite failure with other fields unknown",Result("C-033").Judgement==Judgement.Fail && Result("C-033").UnknownObservations.Count>0);
        s.Restart.GenreCount=1;s.Restart.RockCount=1;
        check("1.6 absent new order does not imply existing catalog destruction",Result("C-006").Judgement==Judgement.Blocked);
        s.Restart.GenreCount=0;
        check("1.6 real catalog loss remains failed alongside unknown order preservation",Result("C-006").Judgement==Judgement.Fail && Result("C-006").UnknownObservations.Count>0);
        s.Restart.GenreCount=1;s.Restart.OrderIdBefore=42;s.Restart.OrderIdAfter=43;s.Restart.OrderRowBeforeRestart=new() {Status=OrderStore.ProbeStatus.Found};s.Restart.OrderRowAfterRestart=new() {Status=OrderStore.ProbeStatus.Found};
        s.Restart.CartBeforeCheckout=Response(body:Cart(1,"5.00",3));s.Restart.CheckoutPost=Response(302,location:"/Checkout/Complete/43");
        check("1.6 observed order row persistence is independent from original basket setup",Result("C-006").Judgement==Judgement.Pass);
        s.Restart.OrderRowAfterRestart.Status=OrderStore.ProbeStatus.Unreadable;s.Restart.GenreCount=0;
        check("1.6 catalog failure cannot be erased by later unreadable order probe",Result("C-006").Judgement==Judgement.Fail && Result("C-006").ObservationFaults.Count>0);
        s.Restart.GenreCount=1;s.Restart.OrderRowAfterRestart.Status=OrderStore.ProbeStatus.Found;s.Restart.CheckoutPost.Status=400;s.Restart.OrderIdAfter=null;
        check("1.6 actual valid restart purchase HTTP400 cannot disappear into unknown order-ID comparison",Result("C-006").Judgement==Judgement.Fail && Result("C-006").UnknownObservations.Count>0);
        s.Order.CheckoutPost=Response(303,location:"/Checkout/Complete/42");s.Order.OrderId=42;
        s.Order.CartBeforeCheckout=Response(body:Cart(1,"7.25"));
        check("1.6 public checkout redirect permits an owned HTTP303",Result("C-019").Judgement==Judgement.Pass);
        foreach(var location in new[]{"/Checkout/Complete/42garbage","/Checkout/Complete/42/extra","https://foreign.example/Checkout/Complete/42"})
        { s.Order.CheckoutPost.Location=location;check("1.6 rejects unbound completion Location: "+location,Result("C-019").Judgement==Judgement.Fail); }
        foreach(var location in new[]{"/Checkout/Complete/42?q=1","/Checkout/Complete/42#fragment"})
        {s.Order.CheckoutPost.Location=location;check("1.6 qualified redirect flow remains unknown without claiming product failure",Result("C-019").Judgement==Judgement.Blocked);}
        s.Order.CheckoutPost.Location="http://127.0.0.1:43001/Checkout/Complete/42";
        check("1.6 accepts exact same-owned-origin absolute completion Location",Result("C-019").Judgement==Judgement.Pass);
        foreach(var status in new[]{304,305,306,399}){s.Order.CheckoutPost.Status=status;check("1.6 nonredirect status cannot fake checkout: "+status,Result("C-019").Judgement==Judgement.Fail);}
        foreach(var status in new[]{307,308}){s.Order.CheckoutPost.Status=status;check("1.6 unobserved method-preserving redirect flow is unknown: "+status,Result("C-019").Judgement==Judgement.Blocked);}
        s.Order.CheckoutPost=Response(302,location:"/Checkout/Complete/42");s.Order.Complete=Response(500);s.Order.OrderRowBeforeSecond=new() {Status=OrderStore.ProbeStatus.Unreadable,Detail="synthetic locked probe"};
        check("1.6 owned completion HTTP500 survives later unreadable row probe",Result("C-022").Judgement==Judgement.Fail && Result("C-022").ObservationFaults.Count>0 && Result("C-022").UnknownObservations.Count>0);
        s.Cart.CartAfterThreeAdds=Response(body:Cart(0, ""));s.Cart.LinesAfterThreeAdds.Clear();
        check("1.6 empty multiplication setup cannot erase missing amount display",Result("C-014").Judgement==Judgement.Fail && Result("C-014").UnknownObservations.Count>0);
        s.Cart.CartAfterThreeAdds=Response(body:Cart(3,"21.75")+"<b id='cart-total'>21.75</b>");
        check("1.6 duplicate money markers never supply numeric pass",Result("C-014").Judgement==Judgement.Fail);
        check("1.6 partial form cannot fake address form redisplay",!Attribution16.CheckoutForm("<form><input name='PromoCode'></form>"));
        check("1.6 textarea and select remain valid address controls",Attribution16.CheckoutForm(Form.Replace("<input name='Country'>","<select name='Country'></select>").Replace("<input name='Address'>","<textarea name='Address'></textarea>")));
        var called=0;WebResponse Submit(){called++;return Response(302,location:"/Checkout/Complete/42");}
        check("1.6 dispatch sends no valid purchase against failed empty setup",Scenarios.ObserveCheckout("1.6.0",Response(body:Cart(0,"0.00")),Submit)==null && called==0);
        Scenarios.ObserveCheckout("1.5.0",Response(body:Cart(0,"0.00")),Submit);
        check("1.5 historical empty checkout dispatch remains unchanged",called==1);
        Scenarios.ObserveCheckout("1.6.0",Response(body:Cart(1,"$7.25")),Submit);
        check("1.6 valid checkout dispatch does not depend on display price pass",called==2);
        s.Isolation.LinesInSessionA=Html.CartLines(Cart(1,"$7.25"));s.Isolation.LinesInSessionB.Clear();s.Isolation.ForeignRemovalObserved=true;
        s.Isolation.CartBeforeA=Response(body:Cart(1,"$7.25"));s.Isolation.CartBeforeB=Response(body:Cart(0,"$0.00"));s.Isolation.CartAfterA=null;s.Isolation.CartAfterB=null;
        s.Isolation.Fault=Judgement.Error;s.Isolation.FaultDetail="synthetic after-cart read error";
        check("1.6 foreign POST followed by unreadable carts does not invent false mutation",Result("C-032").Judgement==Judgement.Error && Result("C-032").UnknownObservations.Count>0);
        s.Isolation.Fault=null;s.Isolation.CartAfterA=Response(body:Cart(1,"$7.25"));s.Isolation.CartAfterB=Response(body:Cart(0,"$0.00"));
        check("1.6 foreign removal currency amounts use symmetric independent parsing",Result("C-032").Judgement==Judgement.Pass);
        s.Isolation.CartAfterA=Response(body:Cart(0,"$0.00"));s.Isolation.CartAfterB=null;s.Isolation.Fault=Judgement.Error;
        check("1.6 verified destructive foreign removal survives later other-cart fault",Result("C-032").Judgement==Judgement.Fail && Result("C-032").ObservationFaults.Count>0 && Result("C-032").UnknownObservations.Count>0);
        var known=new CheckResult {RequirementId="R-001",CheckId="C-012",Judgement=Judgement.Error,Observation="synthetic HTTP observer fault"};Attribution16.ProductFailure(known,"synthetic bound500");
        check("1.6 independent product failure cannot erase original observer fault",known.Judgement==Judgement.Fail && known.ObservationFaults.Count==1);
        var ledger=new Ledger {SpecVersion="1.6.0",Requirements=new() {new() {Id="R-001",Severity="critical",Checks=new() {new() {Id="C-012"}}}}};
        var options=CliOptions.Parse(new[]{"--artifact",".","--out",".","--evaluation-version","1.6.0"});
        var output=(EvaluationOutput)typeof(MusicStore.Evaluator.Program).GetMethod("BuildOutput",System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Static)!.Invoke(null,new object[]{ledger,options,"synthetic","spec","artifact",DateTimeOffset.UtcNow,new List<CheckResult>{known}})!;
        check("1.6 shared output keeps known failure plus observer fault partial with null quality",output.Verdict=="fail_critical" && output.Quality==null && output.ResearchStatus=="incomplete" && output.EvaluatorFaults.Count>0);
        known.ObservationFaults.Clear();known.UnknownObservations.Add("synthetic missing predicate");
        output=(EvaluationOutput)typeof(MusicStore.Evaluator.Program).GetMethod("BuildOutput",System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Static)!.Invoke(null,new object[]{ledger,options,"synthetic","spec","artifact",DateTimeOffset.UtcNow,new List<CheckResult>{known}})!;
        check("1.6 shared output never scores finite failure with missing predicate numerically",output.Verdict=="fail_critical" && output.Quality==null && output.UncheckedScope.Count>0);
        s.InitialReadinessObserved=true;s.InitialAppReady=true;s.AppReady=false;s.RootStatus=200;
        check("1.6 later restart failure does not rewrite initial HTTP readiness",Result("C-002").Judgement==Judgement.Pass);
        s.Browse=new() {BrowseUnknown=Response(500),Fault=Judgement.Error,FaultDetail="later DetailsMissing timeout"};
        var early=Result("C-008");
        check("1.6 early product HTTP500 survives later Browse timeout and mutable restart failure",early.Judgement==Judgement.Fail && early.ObservationFaults.Count==1);
        check("1.6 unperformed later details predicate stays observer fault and unknown",Result("C-010").Judgement==Judgement.Error && Result("C-010").UnknownObservations.Count>0);
        s.Browse.Fault=null;
        check("1.6 earlier finite product response survives independent restart unavailable",Result("C-008").Judgement==Judgement.Fail);
        s.Browse.BrowseUnknown.Status=404;s.Browse.Fault=Judgement.Error;
        check("1.6 observed valid response remains a finite pass alongside independent later observer fault",Result("C-008").Judgement==Judgement.Pass && Result("C-008").ObservationFaults.Count>0);
        s.EvaluationVersion="1.5.0";
        check("1.5 historical mutable readiness cascade remains frozen",Result("C-008").Judgement==Judgement.Blocked && Result("C-002").Judgement==Judgement.Fail);
        s.EvaluationVersion="1.6.0";s.AppReady=true;s.Browse.Fault=null;
        foreach(var status in new[]{302,303,307,308}){s.Browse.AddToCartRedirect=Response(status,location:"/ShoppingCart");check("1.6 GET cart redirect preserves valid method: "+status,Result("C-012").Judgement==Judgement.Pass);}
        foreach(var response in new[]{Response(304,location:"/ShoppingCart"),Response(302,location:"https://foreign.example/ShoppingCart"),Response(302,location:"/ShoppingCart/evil")})
        {s.Browse.AddToCartRedirect=response;check("1.6 invalid cart redirect cannot pass",Result("C-012").Judgement==Judgement.Fail);}
        s.Catalog.ById(2).Price=2.48m;
        foreach(var amount in new[]{"2.48","$2.48"}){s.Browse.Details2=Response(body:"Other album Jazz Artist B Price: "+amount);check("1.6 exact current-price token passes "+amount,Result("C-009").Judgement==Judgement.Pass);}
        foreach(var amount in new[]{"12.48","2.480"}){s.Browse.Details2=Response(body:"Other album Jazz Artist B Price: "+amount);check("1.6 current-price substring cannot fake correct price "+amount,Result("C-009").Judgement==Judgement.Fail);}
        s.Browse.Details2=Response(body:"Other album Jazz Artist B <script>2.48</script>");check("1.6 script cannot supply current price",Result("C-009").Judgement==Judgement.Fail);
        s.Browse.Details2=Response(body:"Other album Jazz Artist B 2.48 12.48");check("1.6 multiple monetary tokens leave current-price attribution unknown",Result("C-009").Judgement==Judgement.Blocked);
        var generic=Cart(2,"14.50").Replace("<table>","<section>").Replace("</table>","</section>").Replace("<tr","<div").Replace("</tr>","</div>").Replace("<td","<span").Replace("</td>","</span>");
        s.Cart.CartAfterTwoAdds=Response(body:generic);
        check("1.6 generic DIV cart row preserves declared quantity semantics",Result("C-013").Judgement==Judgement.Pass);
        check("1.5 tr-specific cart projection remains unchanged",Html.CartLines(generic).Count==0);
        s.Cart.CartAfterRemoveFromTwo=Response(body:Cart(1,"7.25"));s.Cart.RemoveFromOne=Response(body:"{\"itemCount\":0}");
        s.Cart.CartAfterRemoveFromOne=Response(body:"<div id='row-7'><a href='/Store/Details/1'>Album</a></div><b id='cart-total'>0.00</b>");
        var marker=Result("C-016");check("1.6 malformed residual marked row cannot fake empty-cart success",marker.Judgement==Judgement.Fail && marker.UnknownObservations.Count>0);
        s.Cart.CartAfterRemoveFromOne=Response(body:"<div id='row-unknown'>Unreadable remaining cart</div><b id='cart-total'>0.00</b>");
        check("1.6 unsupported remaining row identity cannot fake empty-cart success",Result("C-016").Judgement==Judgement.Blocked);
        s.Cart.CartAfterRemoveFromOne=Response(body:"<span id='item-count-7'>1</span><b id='cart-total'>0.00</b>");
        check("1.6 orphan quantity marker cannot establish an empty cart",Result("C-016").Judgement==Judgement.Fail && Result("C-016").UnknownObservations.Count>0);
        var alias=generic.Replace("row-7","row-007").Replace("item-count-7","item-count-007").Replace("Details/1","Details/01/");
        check("1.6 equivalent positive identifier spelling and trailing route slash decode independently",Html.ObserveCart16(alias).Violations.Count==0 && Html.CartLines(alias,"1.6.0").Single().RecordId==7);
        s.Order.CheckoutPost=Response(302,location:"/Checkout/Complete/42");s.Order.OrderId=42;s.Order.OrderRowBeforeSecond=new() {Status=OrderStore.ProbeStatus.Found};s.Order.CartBeforeCheckout=Response(body:Cart(1,"7.25"));
        s.Order.CartAfterOrder=s.Cart.CartAfterRemoveFromOne;s.Order.CartBeforeSecondCheckout=Response(body:Cart(1,"2.48",2));s.Order.SecondCheckoutPost=Response(302,location:"/Checkout/Complete/43");s.Order.SecondOrderId=43;
        check("1.6 malformed residual first cart cannot establish second-purchase lifecycle",Result("C-020").Judgement==Judgement.Blocked);
        check("1.6 malformed residual post-purchase row cannot establish cart-clearing success",Result("C-021").Judgement==Judgement.Fail && Result("C-021").UnknownObservations.Count>0);
        s.Isolation.Fault=null;s.Isolation.CartBeforeA=Response(body:Cart(1,"7.25"));s.Isolation.CartBeforeB=Response(500,Cart(0,"0.00"));
        check("1.6 HTTP500 empty-looking other cart cannot establish isolation",Result("C-018").Judgement==Judgement.Fail && Result("C-018").UnknownObservations.Count>0);
    }
}
