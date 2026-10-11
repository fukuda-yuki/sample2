using MusicStore.Evaluator;

// Public R-014/R-015 synthetic HTTP/cart observations enter the ordinary
// check registry. No saved Run, model, source asset or private oracle is used.
static class RemovalAliasTests
{
    static WebResponse Response(string body, int status=200) => new() { Status=status, Body=body };
    static string Cart(int count, string total) => (count==0 ? "" :
        $"<table><tr id='row-7'><td><a href='/Store/Details/1'>Synthetic album</a></td><td id='item-count-7'>{count}</td></tr></table>")
        +$"<b id='cart-total'>{total}</b>";

    public static void Run(Action<string,bool> check)
    {
        foreach(var decrement in new[]{true,false})
        {
            var checkId=decrement?"C-015":"C-016";
            var remaining=decrement?1:0;
            using var state=new RunState { AppReady=true, EvaluationVersion="1.6.0",
                Catalog=new() { Albums=new() { new() { AlbumId=1, Price=7.25m } } },
                Ledger=new() { Requirements=new() { new() { Id=decrement?"R-014":"R-015", Severity="major" } } },
                Cart=new() };
            var before=Response(Cart(remaining+1,decrement?"14.50":"7.25"));
            var after=Response(Cart(remaining,decrement?"7.25":"0.00"));
            CheckResult Observe(string json, WebResponse observedAfter=null, int status=200)
            {
                var response=json==null?null:Response(json,status);
                if(decrement)
                { state.Cart.CartAfterTwoAdds=before; state.Cart.RemoveFromTwo=response; state.Cart.CartAfterRemoveFromTwo=observedAfter??after; }
                else
                { state.Cart.CartAfterRemoveFromTwo=before; state.Cart.RemoveFromOne=response; state.Cart.CartAfterRemoveFromOne=observedAfter??after; }
                return Checks.Registry[checkId](state);
            }
            foreach(var json in new[]{
                $"{{\"ItemCount\":{remaining}}}", $"{{\"itemCount\":{remaining}}}",
                $"{{\"ITEMCOUNT\":{remaining}}}",
                $"{{\"ItemCount\":{remaining},\"itemCount\":{remaining}}}",
                $"{{\"itemCount\":{remaining},\"ITEMCOUNT\":{remaining},\"ItemCount\":{remaining},\"other\":99}}"})
                check(checkId+" equivalent casing aliases: "+json,Observe(json).Judgement==Judgement.Pass);
            foreach(var json in new[]{"{}","[]","null","not JSON", "{\"ItemCount\":null}",
                $"{{\"ItemCount\":\"{remaining}\"}}", $"{{\"ItemCount\":{remaining}.5}}",
                "{\"ItemCount\":2147483648}",
                $"{{\"ItemCount\":{remaining+1}}}",
                $"{{\"ItemCount\":{remaining},\"itemCount\":{remaining+1}}}",
                $"{{\"ItemCount\":{remaining},\"itemCount\":null}}",
                $"{{\"ItemCount\":{remaining},\"ItemCount\":{remaining+1}}}"})
                check(checkId+" invalid/ambiguous count: "+json,Observe(json).Judgement==Judgement.Fail);
            var duplicate=$"{{\"ItemCount\":{remaining},\"ItemCount\":{remaining}}}";
            check(checkId+" equal repeated member name remains unresolved",Observe(duplicate).Judgement==Judgement.Blocked);
            check(checkId+" unresolved JSON cannot erase wrong cart",Observe(duplicate,Response(Cart(9,"65.25"))).Judgement==Judgement.Fail);
            var equal=$"{{\"ItemCount\":{remaining},\"itemCount\":{remaining}}}";
            check(checkId+" equal aliases cannot hide wrong cart",Observe(equal,Response(Cart(9,"65.25"))).Judgement==Judgement.Fail);
            check(checkId+" equal aliases cannot hide wrong total",Observe(equal,Response(Cart(remaining,"99.00"))).Judgement==Judgement.Fail);
            check(checkId+" HTTP500 remains a product failure",Observe(equal,status:500).Judgement==Judgement.Fail);
            check(checkId+" absent response stays unobserved",Observe(null).Judgement==Judgement.Blocked);
            state.Cart.Fault=Judgement.Error; state.Cart.FaultDetail="Synthetic observer outage";
            check(checkId+" observer outage stays separate",Observe(null).Judgement==Judgement.Error);
            var failure=Observe("{\"ItemCount\":99}");
            check(checkId+" confirmed wrong value survives observer outage",failure.Judgement==Judgement.Fail && failure.ObservationFaults.Count>0);
        }
    }
}
