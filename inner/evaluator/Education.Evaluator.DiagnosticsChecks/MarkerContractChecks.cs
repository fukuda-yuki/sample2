#nullable enable
using System.Reflection;
using Evaluator = Education.Evaluator.Program;

// Public marker names and invented values only. Feed the actual observation
// predicate and check accumulator, including unresolved/failure precedence.
static class MarkerContractChecks
{
    public static void Run(Action<bool,string> require)
    {
        var type=typeof(Evaluator);
        object? Call(string method,params object?[] args)=>type.GetMethod(method,BindingFlags.NonPublic|BindingFlags.Static)!.Invoke(null,args);
        var results=(Dictionary<string,(string judgement,string detail)>)type.GetField("results",BindingFlags.NonPublic|BindingFlags.Static)!.GetValue(null)!;
        var holds=(Dictionary<int,HashSet<string>>)type.GetField("markerHolds",BindingFlags.NonPublic|BindingFlags.Static)!.GetValue(null)!;
        string Observe(int check,string html,string name,string value,string target="student-id",string id="203",string? row=null)
        {
            holds.Clear();results[$"E-{check:000}"]=("blocked","synthetic pending");
            var matched=(bool)Call("MarkerMatches",check,html,name,value,target,id,row)!;
            Call("Check",check,matched,"Synthetic marker observation");
            return results[$"E-{check:000}"].judgement;
        }
        foreach(var markup in new[]{"<span id='student-first-name'>Morgan</span>","<span student-first-name='Morgan'>Morgan</span>",
            "<span student-first-name><b>Morgan</b></span>","<span id='student-first-name' student-first-name='Morgan'>Morgan</span>"})
            require(Observe(5,markup,"student-first-name","Morgan")=="pass","E-005 supports one bound visible id/named-attribute field");
        foreach(var markup in new[]{"<span student-first-name='Morgan'></span>","<span student-first-name='Morgan'>Other</span>",
            "<span student-first-name='Other'>Morgan</span>","<span hidden student-first-name='Morgan'>Morgan</span>",
            "<div style='display:none'><span student-first-name='Morgan'>Morgan</span></div>",
            "<span student-first-name='Morgan'><script>Morgan</script></span>",
            "<span student-first-name='Morgan'><i hidden>Morgan</i></span>",
            "<section student-id='999'><span student-first-name='Morgan'>Morgan</span></section>",
            "<div>Morgan</div><span student-first-name='Morgan'></span>"})
            require(Observe(5,markup,"student-first-name","Morgan")=="fail","E-005 rejects absent/conflicting/inert/foreign field binding");
        require(Observe(5,"<div student-id='203'></div>","student-id","203")=="blocked","attribute-only student ID remains unresolved");
        require(Observe(5,"<span student-id='203'>999</span>","student-id","203")=="fail","visible contradictory student ID is a failure");
        require(Observe(5,"<div student-id='203' student-first-name='Morgan'>203 Morgan</div>","student-first-name","Morgan")=="blocked","compound region without field binding is unresolved, not page-wide matching");
        require(Observe(5,"<style>.concealed { display:none }</style><span class='concealed' student-first-name='Morgan'>Morgan</span>","student-first-name","Morgan")=="blocked","HTTP text alone cannot promote a CSS-controlled alternative marker");
        require(Observe(5,"<script>/* synthetic dynamic page */</script><span student-first-name='Morgan'>Morgan</span>","student-first-name","Morgan")=="blocked","unrendered dynamic alternative marker stays unresolved");
        require(Observe(5,"<span student-first-name>Morgan</span><span id='student-first-name'>Morgan</span>","student-first-name","Morgan")=="blocked","nonunique markers do not select one convenient value");
        foreach(var grade in new[]{"A","No grade"})
        {
            require(Observe(5,$"<div id='enrollment-17'><span grade-17='{grade}'>{grade}</span></div>","grade-17",grade,row:"enrollment-17")=="pass","grade/null display stays in its enrollment row");
            require(Observe(5,$"<div id='enrollment-18'><span grade-17='{grade}'>{grade}</span></div><div id='enrollment-17'></div>","grade-17",grade,row:"enrollment-17")=="fail","grade from another enrollment cannot satisfy the target row");
        }
        require(Observe(5,"<span student-enrollment-date='2026-02-03'>2026-02-03 00:00:00</span>","student-enrollment-date","2026-02-03")=="fail","UI date retains exact calendar format");
        require(Observe(5,"<span student-full-name='Morgan Review'>Morgan Review</span>","student-full-name","Review, Morgan")=="fail","FullName retains original last-comma-first semantics");
        require(Observe(6,"<span course-credits='3'>3</span>","course-credits","3","course-id","42")=="pass","E-006 accepts visible credits in the owned course response");
        require(Observe(6,"<div course-id='99'><span course-credits='3'>3</span></div>","course-credits","3","course-id","42")=="fail","E-006 rejects foreign course binding");
        require(Observe(6,"<span department-name='Languages'>Languages</span>","department-name","Science","course-id","42")=="fail","department relationship remains exact");
        require(!((HashSet<long>)Call("Ids","<div student-203='203'></div>","student-")!).SetEquals(new[]{203L}),"student list still requires explicit HTML row IDs");
        Observe(5,"<span student-id='203'></span>","student-id","203");
        Call("Check",5,false,"Synthetic independent join failure");Call("Check",5,true,"Later marker observation");
        require(results["E-005"].judgement=="fail","known relationship failure dominates unresolved marker and later success");
        holds.Clear();
    }
}
