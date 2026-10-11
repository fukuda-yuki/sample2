using System.Globalization;
using System.Text.RegularExpressions;

namespace MusicStore.Evaluator;

/// <summary>Explicit 1.6 predicates; historical contracts use their original checks.</summary>
public static class Attribution16
{
    private static List<Html.CartLine> CartLines(string html)=>Html.CartLines(html,"1.6.0");
    public static readonly string[] AddressFields = { "FirstName", "LastName", "Address", "City", "State", "PostalCode", "Country", "Phone", "Email" };
    public sealed record MoneyObservation(decimal? Value, bool ContractFailure, string Detail);
    public static MoneyObservation Money(string html)
    {
        var doc = new AngleSharp.Html.Parser.HtmlParser().ParseDocument(html ?? "");
        foreach (var node in doc.QuerySelectorAll("script,style,template")) node.Remove();
        var nodes = doc.QuerySelectorAll("[id='cart-total']");
        if (nodes.Length != 1) return new(null, true, "Exactly one cart-total display was not present.");
        var text = nodes[0].TextContent.Trim();
        var match = Regex.Match(text, @"\A(?<a>[+-])?\s*(?<prefix>\p{Sc})?\s*(?<b>[+-])?\s*(?<n>[0-9]+\.[0-9]{2})\s*(?<suffix>\p{Sc})?\z");
        if (match.Success && !(match.Groups["a"].Success && match.Groups["b"].Success)
            && !(match.Groups["prefix"].Success && match.Groups["suffix"].Success))
        {
            if(System.Numerics.BigInteger.Parse(match.Groups["n"].Value.Replace(".",""),CultureInfo.InvariantCulture)
                > System.Numerics.BigInteger.Parse("79228162514264337593543950335",CultureInfo.InvariantCulture))
                return new(null,false,"Amount exceeds the exactly representable decimal coefficient.");
            var sign = match.Groups["a"].Value + match.Groups["b"].Value;
            if (decimal.TryParse(sign + match.Groups["n"].Value, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint,
                CultureInfo.InvariantCulture, out var value)) return new(value, false, "Unambiguous displayed amount: " + text);
        }
        // An unsupported/ambiguous representation is not an observed wrong amount.
        var numeric = Regex.Match(text,@"\A(?<a>[+-])?\s*(?<prefix>\p{Sc})?\s*(?<b>[+-])?\s*[0-9]+(?:\.[0-9]*)?\s*(?<suffix>\p{Sc})?\z");
        var wrongFraction = text.Length == 0 || numeric.Success && !(numeric.Groups["a"].Success && numeric.Groups["b"].Success)
            && !(numeric.Groups["prefix"].Success && numeric.Groups["suffix"].Success);
        return new(null, wrongFraction, wrongFraction ? "Display does not have a decimal point and exactly two fractional digits." : "Unsupported or ambiguous money display: " + text);
    }
    public static bool CheckoutForm(string html)
    {
        var doc = new AngleSharp.Html.Parser.HtmlParser().ParseDocument(html ?? "");
        foreach (var node in doc.QuerySelectorAll("script,style,template")) node.Remove();
        return doc.QuerySelectorAll("form").Any(form => AddressFields.Append("PromoCode").All(name =>
            form.QuerySelectorAll("input,select,textarea").Any(control => string.Equals(control.GetAttribute("name"),name,StringComparison.OrdinalIgnoreCase))));
    }
    public static bool Populated(IReadOnlyList<Html.CartLine> lines) => lines.Count > 0
        && lines.All(x => x.RecordId > 0 && x.AlbumId > 0 && x.Count > 0)
        && lines.Select(x => x.RecordId).Distinct().Count() == lines.Count;
    public static bool CartReady(WebResponse response)=>response?.Status==200 && Html.ObserveCart16(response.Body).Violations.Count==0;
    public static bool CartMatches(IReadOnlyList<Html.CartLine> lines, params (int Album,int Quantity)[] expected) =>
        Populated(lines) && lines.Count == expected.Length && expected.All(x => lines.Count(l => l.AlbumId==x.Album && l.Count==x.Quantity)==1);
    public static bool Accepted(WebResponse response, int? id, string ownedBaseUrl=null)
        => response?.Status is 301 or 302 or 303 && OwnedIdentifier(response,id,ownedBaseUrl);
    public static bool OwnedIdentifier(WebResponse response,int? id,string ownedBaseUrl=null,bool allowQualification=false)
    {
        if(response?.Status is not (301 or 302 or 303 or 307 or 308) || id is null or <=0 || string.IsNullOrWhiteSpace(response.Location))return false;
        if(!Uri.TryCreate(new Uri(ownedBaseUrl??"http://127.0.0.1:43001"),response.Location,out var uri))return false;
        var origin=new Uri(ownedBaseUrl??"http://127.0.0.1:43001");
        return uri.GetLeftPart(UriPartial.Authority)==origin.GetLeftPart(UriPartial.Authority)
            && (allowQualification || uri.Query.Length==0 && uri.Fragment.Length==0) && uri.UserInfo.Length==0
            && uri.AbsolutePath=="/Checkout/Complete/"+id.Value.ToString(CultureInfo.InvariantCulture);
    }
    public static void ProductFailure(CheckResult result,string detail)
    {
        if(result.Judgement==Judgement.Error)result.ObservationFaults.Add(result.Observation);
        if(result.Judgement==Judgement.Blocked)result.UnknownObservations.Add("Original HTTP predicate was not observed before the independent product response failure.");
        result.Judgement=Judgement.Fail; result.Observation+="\n"+detail;
    }

    sealed class Composer
    {
        public CheckResult Result { get; }
        readonly List<string> observations = new();
        bool failed;
        public Composer(RunState state, string id)
        {
            var map = new Dictionary<string,string> { ["C-003"]="R-002",["C-004"]="R-003",["C-005"]="R-004",["C-006"]="R-005",["C-007"]="R-006",["C-008"]="R-007",["C-009"]="R-008",["C-010"]="R-009",["C-011"]="R-010",["C-012"]="R-011",["C-013"]="R-012",["C-014"]="R-013",["C-015"]="R-014",["C-016"]="R-015",["C-017"]="R-016",["C-018"]="R-017",["C-019"]="R-018",["C-020"]="R-019",["C-021"]="R-020",["C-022"]="R-021",["C-023"]="R-022",["C-024"]="R-023",["C-025"]="R-024",["C-026"]="R-025",["C-031"]="R-030",["C-032"]="R-031",["C-033"]="R-024" };
            var requirement=state.Ledger.Requirements.Single(r=>r.Id==map[id]);
            Result=new() {CheckId=id,RequirementId=requirement.Id,Expectation=requirement.Expectation,Input="Explicit 1.6 prerequisite and independent predicate assessment"};
            if(state.EvaluatorFault!=null) Fault(state.EvaluatorFault);
        }
        public bool Require(bool present,string reason) { if(!present) Result.UnknownObservations.Add(reason); return present; }
        public void Assert(bool ok,string detail) { observations.Add(detail+": "+(ok?"satisfied":"violated")); failed|=!ok; }
        public void Fault(string reason) => Result.ObservationFaults.Add(reason);
        public bool Response(WebResponse response,string label)
        {
            return Require(response!=null,label+" response was not observed.");
        }
        public decimal? Amount(WebResponse response,string label)
        {
            if(!Response(response,label)) return null;
            Assert(response.Status==200,label+" HTTP200");
            if(response.Status!=200) {Require(false,label+" money display not assessed after non-200 response.");return null;}
            var money=Money(response.Body);
            if(money.Value.HasValue) observations.Add(money.Detail);
            else if(money.ContractFailure) Assert(false,label+": "+money.Detail);
            else Require(false,label+": "+money.Detail);
            return money.Value;
        }
        public List<Html.CartLine> Cart(WebResponse response,string label)
        {
            if(!Response(response,label))return new();
            var cart=Html.ObserveCart16(response.Body);
            foreach(var failure in cart.ContractFailures)Assert(false,label+": "+failure);
            foreach(var gap in cart.UnknownObservations)Require(false,label+": "+gap);
            return cart.Lines;
        }
        public void Scenario(ScenarioResult scenario)
        {
            if(scenario?.Fault==Judgement.Error) Fault(scenario.FaultDetail);
            else if(scenario?.Fault==Judgement.Blocked) Require(false,scenario.FaultDetail);
        }
        public CheckResult Finish()
        {
            Result.Judgement=failed?Judgement.Fail:Result.UnknownObservations.Count>0?Result.ObservationFaults.Count>0?Judgement.Error:Judgement.Blocked:Judgement.Pass;
            Result.Observation=string.Join("\n",observations.Concat(Result.UnknownObservations).Concat(Result.ObservationFaults));
            return Result;
        }
    }
    public static CheckResult Check(RunState state,string id)
    {
        var c=new Composer(state,id); var order=state.Order; var cart=state.Cart;
        if(id is "C-003" or "C-004" or "C-005" or "C-007" or "C-008" or "C-009" or "C-010" or "C-011" or "C-012") Browse(c,state,id);
        else if(id is "C-013" or "C-014")
        {
            c.Scenario(cart);var response=id=="C-013"?cart?.CartAfterTwoAdds:cart?.CartAfterThreeAdds;
            if(c.Response(response,"Cart"))
            {
                var lines=c.Cart(response,"Added cart");var readable=Html.ObserveCart16(response.Body).Violations.Count==0;
                if(id=="C-013") {if(c.Require(readable,"Two-add quantity predicate is not readable from the declared row markers."))c.Assert(response.Status==200 && CartMatches(lines,(1,2)),"Two additions produce one album-one quantity-two line");}
                else
                {
                    var total=c.Amount(response,"Cart total");
                    if(c.Require(readable && Populated(lines),"No complete positive cart quantities were established for the multiplication predicate.")
                        && c.Require(lines.All(l=>state.Catalog.ById(l.AlbumId)!=null),"An observed album has no independent catalog price."))
                    { if(total.HasValue)c.Assert(total==lines.Sum(l=>l.Count*state.Catalog.ById(l.AlbumId).Price),"Displayed total equals source-defined unit price times actual observed quantities"); }
                }
            }
        }
        else if(id is "C-015" or "C-016") Removal(c,state,id);
        else if(id=="C-017")
        {
            c.Scenario(order);
            if(c.Response(order?.CartBeforeCheckout,"Mixed cart"))
            {
                var lines=c.Cart(order.CartBeforeCheckout,"Mixed cart");
                var readable=Html.ObserveCart16(order.CartBeforeCheckout.Body).Violations.Count==0;
                var formed=readable && order.CartBeforeCheckout.Status==200 && CartMatches(lines,(1,2),(2,1));
                if(c.Require(readable,"Mixed-cart quantities were not unambiguously observed."))c.Assert(formed,"Exact album identities and per-album quantities");
                var total=c.Amount(order.CartBeforeCheckout,"Mixed cart");
                if(c.Require(formed,"The requested mixed basket was not established for its total predicate.") && total.HasValue)c.Assert(total==2*state.Catalog.ById(1).Price+state.Catalog.ById(2).Price,"Mixed-cart independent effective price total");
            }
        }
        else if(id is "C-019" or "C-026")
        {
            c.Scenario(order);
            if(id=="C-026" && c.Response(order?.CheckoutFormGet,"Unauthenticated form"))
                c.Assert(order.CheckoutFormGet.Status==200 && CheckoutForm(order.CheckoutFormGet.Body),"Unauthenticated address form is available");
            if(c.Require(order?.CartBeforeCheckout?.Status==200 && Html.ObserveCart16(order.CartBeforeCheckout.Body).Violations.Count==0 && Populated(CartLines(order.CartBeforeCheckout.Body)),"A nonempty owned cart before valid checkout was not established.")
                && c.Response(order?.CheckoutPost,"Valid checkout"))Checkout(c,order.CheckoutPost,order.OrderId,state.Host?.BaseUrl);
        }
        else if(id=="C-020")
        {
            c.Scenario(order);
            var first=order!=null && Accepted(order.CheckoutPost,order.OrderId,state.Host?.BaseUrl) && order.OrderRowBeforeSecond?.Found==true
                && CartReady(order.CartBeforeCheckout) && Populated(CartLines(order.CartBeforeCheckout.Body))
                && CartReady(order.CartAfterOrder) && CartLines(order.CartAfterOrder.Body).Count==0 && Money(order.CartAfterOrder.Body).Value==0m;
            if(c.Require(first,"A stored first purchase with an emptied cart was not established.")
                && c.Require(CartReady(order.CartBeforeSecondCheckout) && CartMatches(CartLines(order.CartBeforeSecondCheckout.Body),(2,1)),"A distinct second basket after the first purchase was not established.")
                && c.Response(order.SecondCheckoutPost,"Second checkout")) { Checkout(c,order.SecondCheckoutPost,order.SecondOrderId,state.Host?.BaseUrl);if(order.SecondOrderId>0)c.Assert(order.SecondOrderId!=order.OrderId,"Second purchase creates a distinct order ID"); }
        }
        else if(id=="C-021")
        {
            c.Scenario(order);
            if(c.Require(order!=null && Accepted(order.CheckoutPost,order.OrderId,state.Host?.BaseUrl) && CartReady(order.CartBeforeCheckout) && Populated(CartLines(order.CartBeforeCheckout.Body)),"An actual nonempty purchase before cart clearing was not established."))
            { var total=c.Amount(order.CartAfterOrder,"Post-purchase cart");var lines=c.Cart(order.CartAfterOrder,"Post-purchase cart"); if(order.CartAfterOrder!=null && (lines.Count>0 || Html.ObserveCart16(order.CartAfterOrder.Body).Violations.Count==0))c.Assert(lines.Count==0,"Post-purchase cart has no rows");if(total.HasValue)c.Assert(total==0m,"Post-purchase total is zero"); }
        }
        else if(id is "C-022" or "C-023")
        {
            c.Scenario(order);
            if(c.Require(order!=null && OwnedIdentifier(order.CheckoutPost,order.OrderId,state.Host?.BaseUrl),"A positive owned order ID from an observed checkout redirect was not established."))
            {
                c.Require(order.OrderRowBeforeSecond?.Found==true,"The owned order's stored row was not independently established.");
                var response=id=="C-022"?order.Complete:order.OtherSessionComplete;
                if(c.Response(response,"Order completion"))c.Assert(id=="C-022"?response.Status==200 && Html.MarkedOrderNumber(response.Body)==order.OrderId
                    :(response.Status is 403 or 404) && !Html.HasOrderMarker(response.Body) && Html.OrderNumber(response.Body)!=order.OrderId,"Owned completion display / foreign-session refusal");
            }
            if(order?.OrderRowBeforeSecond?.Status==OrderStore.ProbeStatus.Unreadable)c.Fault(order.OrderRowBeforeSecond.Detail);
        }
        else if(id is "C-024" or "C-025" or "C-033")
        {
            var invalid=state.InvalidCheckout;c.Scenario(invalid);
            if(id=="C-033")
            {
                foreach(var field in AddressFields)
                {
                    var trials=invalid?.AddressCases.Where(t=>t.Field==field).ToArray() ?? Array.Empty<InvalidFieldObservation>();
                    if(c.Require(trials.Length==1,field+" independent trial was not observed exactly once."))Invalid(c,trials[0]);
                }
            }
            else if(invalid!=null)Invalid(c,new() {Field=id=="C-024"?"Wrong promo":"FirstName",Before=id=="C-024"?invalid.CartBefore:invalid.CartBeforeMissing,
                After=id=="C-024"?invalid.CartAfterWrongPromo:invalid.CartAfterMissingField,Response=id=="C-024"?invalid.WrongPromo:invalid.MissingField,
                OrdersBefore=id=="C-024"?invalid.OrdersBefore:invalid.OrdersBeforeMissing,OrdersAfter=id=="C-024"?invalid.OrdersAfterWrongPromo:invalid.OrdersAfterMissing});
            else c.Require(false,"Invalid checkout scenario was not observed.");
        }
        else if(id is "C-018" or "C-032")
        {
            var isolation=state.Isolation;c.Scenario(isolation);
            var populated=isolation?.CartBeforeA?.Status==200 && Html.ObserveCart16(isolation.CartBeforeA.Body).Violations.Count==0 && Populated(CartLines(isolation.CartBeforeA.Body));
            c.Require(populated,"A populated owned session with positive cart identity was not established.");
            if(id=="C-018" && isolation!=null)
            {
                if(c.Response(isolation.CartBeforeB,"Independent empty session"))
                {
                    var lines=c.Cart(isolation.CartBeforeB,"Independent empty session");var total=c.Amount(isolation.CartBeforeB,"Independent empty session");
                    if(isolation.CartBeforeB.Status==200 && (lines.Count>0 || Html.ObserveCart16(isolation.CartBeforeB.Body).Violations.Count==0))c.Assert(lines.Count==0,"Independent empty session contains no foreign cart rows");
                    else c.Require(false,"Independent-session cart projection was not observed.");
                    if(total.HasValue)c.Assert(total==0,"Independent empty session total is zero");
                }
            }
            else if(c.Require(isolation?.ForeignRemovalObserved==true,"No foreign removal request with an owned positive ID was observed.") && populated)
            {
                foreach(var pair in new[]{(Before:isolation.CartBeforeA,After:isolation.CartAfterA),(Before:isolation.CartBeforeB,After:isolation.CartAfterB)})
                {
                    if(c.Response(pair.Before,"Foreign removal before cart") && c.Response(pair.After,"Foreign removal after cart"))
                    {
                        var before=c.Amount(pair.Before,"Foreign removal before cart");var after=c.Amount(pair.After,"Foreign removal after cart");
                        var beforeLines=c.Cart(pair.Before,"Foreign removal before cart");var afterLines=c.Cart(pair.After,"Foreign removal after cart");
                        if(c.Require(pair.Before.Status==200 && pair.After.Status==200 && Html.ObserveCart16(pair.Before.Body).Violations.Count==0 && Html.ObserveCart16(pair.After.Body).Violations.Count==0,"Complete foreign cart projection could not be compared."))c.Assert(beforeLines.Select(x=>(x.AlbumId,x.Count)).OrderBy(x=>x)
                            .SequenceEqual(afterLines.Select(x=>(x.AlbumId,x.Count)).OrderBy(x=>x)),"Foreign removal preserves each session's albums and quantities");
                        else c.Require(false,"Foreign cart projection could not be compared after non-200 response.");
                        if(before.HasValue && after.HasValue)c.Assert(before==after,"Foreign removal preserves each session's total");
                    }
                }
            }
        }
        else if(id=="C-006")Restart(c,state);
        else if(id=="C-031")
        {
            if(c.Require(state.Migration!=null,"Independent migration observation was not available."))
            {
                c.Assert(!state.Migration.HasConfirmedFailure,state.Migration.Detail);
                foreach(var gap in state.Migration.UnknownObservations)c.Require(false,gap);
                foreach(var fault in state.Migration.ObservationFaults)c.Fault(fault);
                if(state.Migration.Judgement==Judgement.Blocked && state.Migration.UnknownObservations.Count==0)c.Require(false,"Migration workflow was not fully observed.");
            }
        }
        c.Result.Evidence=string.Join("\n",new[]{state.Transcript("browse"),state.Transcript("redirect"),state.Transcript("cart"),state.Transcript("cart-total"),state.Transcript("order"),state.Transcript("other"),state.Transcript("restart"),state.Transcript("invalid"),state.Transcript("invalid-missing"),state.Transcript("isolation-a"),state.Transcript("isolation-b")}.Where(s=>s.Length>0));
        return c.Finish();
    }
    static void Browse(Composer c,RunState state,string id)
    {
        var b=state.Browse;c.Scenario(b);
        if(!c.Require(b!=null,"Browse scenario was not observed."))return;
        if(id=="C-004")
        {
            foreach(var genre in state.Catalog.Genres)
            {
                b.GenreBrowses.TryGetValue(genre,out var response);
                if(c.Response(response,"Genre "+genre))c.Assert(response.Status==200 && Html.AlbumIds(response.Body).Distinct().Count()==state.Catalog.CountByGenre(genre),"Genre "+genre+" contains the independent expected album count");
            }
            return;
        }
        if(id=="C-007")
        {
            b.GenreBrowses.TryGetValue("Rock",out var response);
            if(c.Response(response,"Rock browse"))c.Assert(response.Status==200 && Html.Contains(response.Body,state.Catalog.ById(1).Title) && !Html.Contains(response.Body,state.Catalog.ById(2).Title),"Rock contains its own representative album and excludes the other genre's album");return;
        }
        var r=id switch {"C-003"=>b.Store,"C-005"=>b.Details1,"C-008"=>b.BrowseUnknown,"C-009"=>b.Details2,"C-010"=>b.DetailsMissing,"C-011"=>b.Root,"C-012"=>b.AddToCartRedirect,_=>null};
        if(!c.Response(r,id))return;
        if(id is "C-008" or "C-010")c.Assert(r.Status==404,"Unknown genre/album returns HTTP404");
        else if(id=="C-012")
        {
            var origin=new Uri(state.Host?.BaseUrl??"http://127.0.0.1:43001");
            var known=Uri.TryCreate(origin,r.Location??"",out var target) && target.GetLeftPart(UriPartial.Authority)==origin.GetLeftPart(UriPartial.Authority)
                && target.UserInfo.Length==0 && target.AbsolutePath.TrimEnd('/') is "/ShoppingCart" or "/ShoppingCart/Index";
            if(known && (target.Query.Length>0 || target.Fragment.Length>0))c.Require(false,"Qualified cart redirect navigation was not observed.");
            else c.Assert(known && r.Status is 301 or 302 or 303 or 307 or 308,"Add redirects to an exact owned cart destination");
        }
        else
        {
            c.Assert(r.Status==200,id+" HTTP200");
            if(r.Status!=200)return;
            var text=Html.Text(r.Body);
            if(id is "C-003" or "C-011")c.Assert(state.Catalog.Genres.All(g=>text.Contains(g,StringComparison.OrdinalIgnoreCase)),"All supplied genres are displayed");
            if(id=="C-011")c.Assert(Html.CartCount(r.Body)==0,"Initial home cart summary is zero");
            if(id=="C-005")c.Assert(text.Contains(state.Catalog.ById(1).Title,StringComparison.Ordinal),"Album-one title is displayed");
            if(id=="C-009")
            {
                var album=state.Catalog.ById(2);
                c.Assert(text.Contains(album.Title,StringComparison.Ordinal) && text.Contains(album.Genre,StringComparison.OrdinalIgnoreCase) && text.Contains(album.Artist,StringComparison.OrdinalIgnoreCase),"Album title, genre and artist are displayed");
                var priceText=text.Replace(album.Title,"").Replace(album.Genre,"").Replace(album.Artist,"");
                var tokens=Regex.Matches(priceText,@"(?<![0-9.,])[+-]?\s*\p{Sc}?\s*[0-9]+\.[0-9]+\s*\p{Sc}?(?![0-9.,]|[eE][+-]?[0-9])");
                if(tokens.Count==0 && Regex.IsMatch(priceText,@"[0-9]\.[0-9]"))c.Require(false,"Unit-price representation was not unambiguous under the bounded decimal-token observer.");
                else if(tokens.Count==0)c.Assert(false,"Current price with a decimal point and two fractional digits is displayed");
                else if(c.Require(tokens.Count==1,"Multiple visible decimal tokens make the current unit-price observation ambiguous."))
                {
                    var money=Money("<b id='cart-total'>"+System.Net.WebUtility.HtmlEncode(tokens[0].Value)+"</b>");
                    if(money.Value.HasValue)c.Assert(money.Value==album.Price,"The complete visible current-price numeric token equals the independent source price");
                    else if(money.ContractFailure)c.Assert(false,money.Detail);else c.Require(false,money.Detail);
                }
            }
        }
    }
    static void Invalid(Composer c,InvalidFieldObservation trial)
    {
        if(!c.Response(trial.Response,trial.Field+" invalid input"))return;
        c.Assert(trial.Response.Status==200 && CheckoutForm(trial.Response.Body),trial.Field+" invalid input redisplays the full address form with HTTP200");
        var populated=trial.Before?.Status==200 && Html.ObserveCart16(trial.Before.Body).Violations.Count==0 && Populated(CartLines(trial.Before.Body));
        if(c.Require(populated,trial.Field+" cart preservation lacked an initially nonempty cart."))
        {
            var before=c.Amount(trial.Before,trial.Field+" before cart");var after=c.Amount(trial.After,trial.Field+" after cart");
            var afterLines=c.Cart(trial.After,trial.Field+" after cart");
            if(trial.After!=null && c.Require(Html.ObserveCart16(trial.After.Body).Violations.Count==0,"Invalid-input after-cart quantities were not fully observed."))c.Assert(CartLines(trial.Before.Body).Select(x=>(x.AlbumId,x.Count)).OrderBy(x=>x)
                .SequenceEqual(afterLines.Select(x=>(x.AlbumId,x.Count)).OrderBy(x=>x)),trial.Field+" cart quantities and albums are preserved");
            if(before.HasValue && after.HasValue)c.Assert(before==after,trial.Field+" displayed cart amount is preserved");
        }
        foreach(var snapshot in new[]{trial.OrdersBefore,trial.OrdersAfter})
        {
            if(snapshot?.Status==OrderStore.ProbeStatus.Unreadable)c.Fault(snapshot.Detail);
            else if(snapshot?.Status==OrderStore.ProbeStatus.ContractViolation)c.Assert(false,snapshot.Detail);
        }
        if(c.Require(trial.OrdersBefore?.Status==OrderStore.ProbeStatus.Found && trial.OrdersAfter?.Status==OrderStore.ProbeStatus.Found,trial.Field+" stored order-ID comparison was not observed."))
            c.Assert(trial.OrdersBefore.SameAs(trial.OrdersAfter),trial.Field+" stored order IDs are unchanged");
    }
    static void Checkout(Composer c,WebResponse response,int? id,string origin)
    {
        if(OwnedIdentifier(response,id,origin,true) && !OwnedIdentifier(response,id,origin))
            c.Require(false,"Same-origin completion query/fragment flow was not observed; it is not a declared product format violation.");
        else if(response.Status is 307 or 308 && OwnedIdentifier(response,id,origin))
            c.Require(false,"Method-preserving checkout redirect flow was not observed; an artificial completion GET cannot establish that flow.");
        else c.Assert(Accepted(response,id,origin),"Checkout uses a recognized redirect to its exact owned completion route and positive ID");
    }
    static void Removal(Composer c,RunState state,string id)
    {
        var r=state.Cart;c.Scenario(r);var decrement=id=="C-015";
        var before=decrement?r?.CartAfterTwoAdds:r?.CartAfterRemoveFromTwo;
        var response=decrement?r?.RemoveFromTwo:r?.RemoveFromOne;
        var after=decrement?r?.CartAfterRemoveFromTwo:r?.CartAfterRemoveFromOne;
        var quantity=decrement?2:1;
        if(c.Require(before?.Status==200 && Html.ObserveCart16(before.Body).Violations.Count==0 && Scenarios.RemovalPrecondition(CartLines(before.Body),quantity),"HTTP removal lacked the required current positive owned record ID and quantity.") && c.Response(response,"HTTP removal"))
        {
            c.Assert(response.Status==200,"Removal JSON response HTTP200");
            try
            {
                using var json=System.Text.Json.JsonDocument.Parse(response.Body??"");
                var properties=json.RootElement.EnumerateObject().Where(x=>x.Name.Equals("itemCount",StringComparison.OrdinalIgnoreCase)).ToArray();
                // R-014/R-015 require the remaining quantity. Distinct casing
                // aliases may agree on it. Identical member names with correct
                // equal values remain unresolved under the limited adjudication.
                var valuesCorrect=properties.Length>0 && properties.All(x=>x.Value.TryGetInt32(out var n) && n==quantity-1);
                c.Assert(valuesCorrect,
                    "Removal JSON itemCount casing aliases consistently report the correct integer");
                if(valuesCorrect)c.Require(properties.Select(x=>x.Name).Distinct(StringComparer.Ordinal).Count()==properties.Length,
                    "Equal repeated JSON member names are outside the adjudicated casing-alias contract.");
            }
            catch(System.Text.Json.JsonException) {c.Assert(false,"Removal response is a JSON object");}
            catch(InvalidOperationException) {c.Assert(false,"Removal response has a numeric itemCount");}
            var total=c.Amount(after,"Post-removal cart");
            var afterLines=c.Cart(after,"Post-removal cart");
            if(after!=null && (Html.ObserveCart16(after.Body).Violations.Count==0 || !decrement && afterLines.Count>0))c.Assert(decrement?CartMatches(afterLines,(1,1)):afterLines.Count==0,"Correct independent post-removal cart quantities and album identity");
            if(total.HasValue)c.Assert(total==(quantity-1)*state.Catalog.ById(1).Price,"Correct independent post-removal total");
        }
        var browser=state.BrowserCartReview?.For(id);
        if(browser?.Complete==true)c.Assert(browser.Pass,"Independent browser removal: "+browser.Detail);
    }
    static void Restart(Composer c,RunState state)
    {
        var r=state.Restart;c.Scenario(r);
        if(!c.Require(r!=null,"Restart scenario was not observed."))return;
        if(c.Require(r.GenreCount.HasValue && r.RockCount.HasValue,"Restart catalog counts were not observed."))c.Assert(r.GenreCount==state.Catalog.Genres.Count && r.RockCount==state.Catalog.CountByGenre("Rock"),"Existing catalog counts persist after restart");
        if(c.Require(CartReady(r.CartBeforeCheckout) && Populated(CartLines(r.CartBeforeCheckout.Body)),"Restart purchase input cart was not observed."))
        {if(c.Response(r.CheckoutPost,"Restart valid checkout"))Checkout(c,r.CheckoutPost,r.OrderIdAfter,state.Host?.BaseUrl);}
        if(c.Require(r.OrderIdBefore>0,"No positive order existed for the restart row-preservation comparison."))
        {
            foreach(var probe in new[]{r.OrderRowBeforeRestart,r.OrderRowAfterRestart})
            {
                if(probe?.Status==OrderStore.ProbeStatus.Unreadable){c.Fault(probe.Detail);c.Require(false,"Restart row-preservation probe was unreadable.");}
                else if(c.Require(probe!=null,"Restart order-row probe was not observed."))c.Assert(probe.Found,"Existing order row is present: "+probe.Detail);
            }
            if(c.Require(r.OrderIdAfter>0,"A new order ID after restart was not observed."))c.Assert(r.OrderIdAfter!=r.OrderIdBefore,"Restart order ID differs from original order ID");
        }
    }
}
