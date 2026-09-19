using System.Reflection;
using System.Text.Json;
using MusicStore.Evaluator;

if (args.Length >= 2 && args[0] == "--scan")
{
    object result = args.Length == 4 && args[2] == "--assembly"
        ? Assembly.LoadFrom(Path.GetFullPath(args[3])).GetType("MusicStore.Evaluator.LegacyScan")!.GetMethod("Scan")!.Invoke(null, new object[] { args[1] })!
        : LegacyScan.Scan(args[1]);
    var type = result.GetType();
    Console.WriteLine(JsonSerializer.Serialize(new { references = type.GetProperty("References")!.GetValue(result),
        unresolved = type.GetProperty("Unresolved")?.GetValue(result) ?? new List<string>() }));
    return 0;
}

var root = Path.Combine(Path.GetTempPath(), "sample2-legacy-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
var results = new List<object>();
void Write(string dir, string name, string contents)
{
    var path = Path.Combine(dir, name); Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllText(path, contents);
}
string Entry(string path, string type = "{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") => $"Project(\"{type}\") = \"MvcMusicStore\", \"{path}\", \"{{472C4947-C282-4C2D-9FAB-838DF7CD6752}}\"\nEndProject\n";
var header = "Microsoft Visual Studio Solution File, Format Version 12.00\n";
var modern = "<Project Sdk=\"Microsoft.NET.Sdk.Web\"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>";
var legacy = "<Project><PropertyGroup><TargetFrameworkVersion>v4.8</TargetFrameworkVersion></PropertyGroup></Project>";
void Test(string name, Action<string> setup, bool expectReference, bool expectUnresolved)
{
    var dir = Path.Combine(root, name); Directory.CreateDirectory(dir); setup(dir);
    var result = LegacyScan.Scan(dir);
    if ((result.References.Count > 0) != expectReference || (result.Unresolved.Count > 0) != expectUnresolved)
        throw new Exception(name + ": " + JsonSerializer.Serialize(result));
    results.Add(new { name, passed = true, references = result.References, unresolved = result.Unresolved });
}
try
{
    Test("modern_solution_same_name", d => { Write(d,"MvcMusicStore.csproj",modern); Write(d,"MvcMusicStore.sln",header+Entry("MvcMusicStore.csproj")); }, false, false);
    Test("modern_project_reference", d => { Write(d,"MvcMusicStore.csproj",modern); Write(d,"App.csproj",modern.Replace("</Project>","<ItemGroup><ProjectReference Include=\"MvcMusicStore.csproj\" /></ItemGroup></Project>")); }, false, false);
    Test("legacy_solution", d => { Write(d,"Old.csproj",legacy); Write(d,"Solution.sln",header+Entry("Old.csproj")); }, true, false);
    Test("mixed_solution", d => { Write(d,"App.csproj",modern); Write(d,"Old.csproj",legacy); Write(d,"MvcMusicStore.sln",header+Entry("App.csproj")+Entry("Old.csproj")); }, true, false);
    Test("folder_and_backslash", d => { Write(d,"App/Modern.csproj",modern); Write(d,"MvcMusicStore.sln",header+Entry("group","{2150E333-8FDC-42A3-9474-1A3956D46DE8}")+Entry("App\\Modern.csproj")); }, false, false);
    Test("missing_project", d => Write(d,"MvcMusicStore.sln",header+Entry("missing.csproj")), false, true);
    Test("outside_project", d => Write(d,"MvcMusicStore.sln",header+Entry("../outside.csproj")), false, true);
    Test("unparseable_solution", d => Write(d,"MvcMusicStore.sln","broken"), false, true);
    Test("unparseable_project", d => { Write(d,"A.csproj","<Project"); Write(d,"MvcMusicStore.sln",header+Entry("A.csproj")); }, false, true);
    Test("unresolved_framework", d => { Write(d,"A.csproj",modern.Replace("net8.0","$(Target)")); Write(d,"MvcMusicStore.sln",header+Entry("A.csproj")); }, false, true);
    Test("modern_name_comment", d => { Write(d,"App.csproj",modern); Write(d,"Notes.cs","// reference MvcMusicStore.csproj for migration history"); }, false, false);
    Test("cycle", d => { Write(d,"A.csproj",modern.Replace("</Project>","<ItemGroup><ProjectReference Include=\"A.csproj\" /></ItemGroup></Project>")); Write(d,"MvcMusicStore.sln",header+Entry("A.csproj")); }, false, false);
    Console.WriteLine(JsonSerializer.Serialize(new { passed = true, tests = results.Count, results }));
    return 0;
}
finally
{
    // Delete only this invocation's explicitly created temporary fixture root.
    if (Path.GetFullPath(root).StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase)) Directory.Delete(root, true);
}
