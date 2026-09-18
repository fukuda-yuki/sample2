using System.Diagnostics;
using System.Text.Json;
using MusicStore.Evaluator;

if (args.Contains("--environment-child"))
{
    Console.WriteLine(Environment.GetEnvironmentVariable("OPENCODE_GO_API_KEY") == null
        && Environment.GetEnvironmentVariable("UNRELATED_SECRET") == null ? "absent" : "leaked");
    return;
}

var cases = new List<object>();
void Check(string name, bool pass)
{
    cases.Add(new { name, pass });
    if (!pass) throw new Exception("Regression failed: " + name);
}

Check("comment cannot supply money", Html.Money("<!-- <td id='cart-total'>17.98</td> -->") == null);
Check("script cannot supply album", Html.AlbumIds("<script>\"<a href='/Store/Details/1'>X</a>\"</script>").Count == 0);
Check("template cannot supply count", Html.CartCount("<template><b id='cart-status'>Cart (2)</b></template>") == null);
Check("entities and child text", Html.CartCount("<a id='cart&#45;status'>Cart (<b>2</b>)</a>") == 2);
Check("order text with child elements", Html.OrderNumber("Your order number is: <b>123</b>") == 123);
Check("order overflow is not an evaluator fault", Html.OrderNumber("order number is: 9999999999999999") == null);
Check("localized order label", Html.MarkedOrderNumber("注文番号: <b id='order-number'> <i>123</i> </b>") == 123);
Check("comment cannot supply order marker", Html.MarkedOrderNumber("<!-- <b id='order-number'>123</b> -->") == null);
Check("duplicate order marker rejected", Html.MarkedOrderNumber("<b id='order-number'>123</b><b id='order-number'>124</b>") == null);
Check("order marker must contain only a number", Html.MarkedOrderNumber("<b id='order-number'>ID 123</b>") == null);
Check("order marker overflow does not fault", Html.MarkedOrderNumber("<b id='order-number'>9999999999999999</b>") == null);
var cart = "<table><tr id='row&#45;5'><td><a href='/Store/Details/2'>Title</a></td><td id='item-count-5'><span>2</span></td></tr></table>";
var line = Html.CartLines(cart).Single();
Check("DOM-equivalent quantity", line.RecordId == 5 && line.AlbumId == 2 && line.Count == 2);
Check("wrong quantity stays wrong", Html.CartLines(cart.Replace("<span>2</span>", "<span>9</span>")).Single().Count == 9);
var pricedCart = cart.Replace("</table>", "<tr><td id='cart-total'>17.98</td></tr></table>");
Check("cart record IDs may change", Html.SameCart(pricedCart,
    pricedCart.Replace("row&#45;5", "row&#45;7").Replace("item-count-5", "item-count-7")));
Check("invalid checkout quantity change detected", !Html.SameCart(pricedCart, pricedCart.Replace("<span>2</span>", "<span>3</span>")));
Check("invalid checkout album change detected", !Html.SameCart(pricedCart, pricedCart.Replace("Details/2", "Details/3")));
Check("invalid checkout total change detected", !Html.SameCart(pricedCart, pricedCart.Replace("17.98", "8.99")));
Check("form control is required", !Html.HasCheckoutForm("<p>PromoCode</p>"));
Check("localized form label accepted", Html.HasCheckoutForm("<form><label>コード</label><input name='PromoCode'></form>"));
Check("comment cannot satisfy visible text", !Html.Contains("<!-- Rock -->Jazz", "Rock"));

var root = Path.Combine(Path.GetTempPath(), "sample2-parser-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    File.WriteAllText(Path.Combine(root, "App.csproj"), "<Project Sdk = 'Microsoft.NET.Sdk.Web'><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup><!-- <Reference Include='System.Web'/> --></Project>");
    Check("XML single quotes", AppHost.FindWebProjects(root).Count == 1);
    File.WriteAllText(Path.Combine(root, "App.csproj"), "<Project><Sdk Name='Microsoft.NET.Sdk.Web'/></Project>");
    Check("XML child SDK", AppHost.FindWebProjects(root).Count == 1);
    File.WriteAllText(Path.Combine(root, "App.csproj"), "<Project><!-- Microsoft.NET.Sdk.Web --></Project>");
    Check("XML comment is not SDK", AppHost.FindWebProjects(root).Count == 0);
    File.WriteAllText(Path.Combine(root, "launchSettings.json"), """
        {"iisSettings":{"iisExpress":{"applicationUrl":"http://localhost:1234"}},
         "profiles":{"IIS Express":{"commandName":"IISExpress"}}}
        """);
    Check("ASP.NET Core IIS Express profile is not a legacy dependency", LegacyScan.Scan(root).References.Count == 0);
    File.WriteAllText(Path.Combine(root, "MvcMusicStore.csproj"), "<Project Sdk='Microsoft.NET.Sdk.Web'><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>");
    Check("modern project may retain the legacy project name", LegacyScan.Scan(root).References.Count == 0);
    File.WriteAllText(Path.Combine(root, "MvcMusicStore.csproj"), "<Project><PropertyGroup><TargetFrameworkVersion>v4.8</TargetFrameworkVersion></PropertyGroup></Project>");
    Check("actual legacy project remains rejected", LegacyScan.Scan(root).References.Count > 0);
    File.Delete(Path.Combine(root, "MvcMusicStore.csproj"));
    File.WriteAllText(Path.Combine(root, "Bridge.cs"), """
        class Bridge { public string Command = "iisexpress /path:MvcMusicStore\\"; }
        """);
    Check("IIS Express legacy target is still detected", LegacyScan.Scan(root).References.Count == 1);
}
finally { Directory.Delete(root, true); }

// Only synthetic markers: no discovery or reading of the user's credential.
Environment.SetEnvironmentVariable("OPENCODE_GO_API_KEY", "synthetic-canary");
Environment.SetEnvironmentVariable("UNRELATED_SECRET", "synthetic-canary");
var result = AppHost.RunProcess("dotnet", $"\"{typeof(Program).Assembly.Location}\" --environment-child", Environment.CurrentDirectory, 10);
Check("real child process does not inherit secrets", result.ExitCode == 0 && result.StdOut.Trim() == "absent");
Console.WriteLine(JsonSerializer.Serialize(new { passed = cases.Count, cases }));
