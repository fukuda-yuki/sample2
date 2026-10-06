using System.Reflection;
using System.Text.Json;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
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
void AssemblyFixture(string dir, string framework, bool systemWeb = false)
{
    // Minimal managed metadata fixtures: not runnable app evidence.
    var m = new MetadataBuilder();
    m.AddModule(0, m.GetOrAddString("MvcMusicStore.dll"), m.GetOrAddGuid(Guid.NewGuid()), default, default);
    m.AddAssembly(m.GetOrAddString("MvcMusicStore"), new Version(1,0), default, default, default, default);
    var runtime = m.AddAssemblyReference(m.GetOrAddString("System.Runtime"), new Version(8,0), default, default, default, default);
    if (systemWeb) m.AddAssemblyReference(m.GetOrAddString("System.Web"), new Version(4,0), default, default, default, default);
    var attr = m.AddTypeReference(runtime, m.GetOrAddString("System.Runtime.Versioning"), m.GetOrAddString("TargetFrameworkAttribute"));
    var constructor = m.AddMemberReference(attr, m.GetOrAddString(".ctor"), m.GetOrAddBlob(new byte[] { 0x20, 1, 1, 0x0e }));
    var value = new BlobBuilder(); value.WriteUInt16(1); value.WriteSerializedString(framework); value.WriteUInt16(0);
    m.AddCustomAttribute(MetadataTokens.EntityHandle(0x20000001), constructor, m.GetOrAddBlob(value));
    var image = new BlobBuilder();
    new ManagedPEBuilder(new PEHeaderBuilder(imageCharacteristics: Characteristics.Dll), new MetadataRootBuilder(m), new BlobBuilder()).Serialize(image);
    File.WriteAllBytes(Path.Combine(dir, "MvcMusicStore.dll"), image.ToArray());
}
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
    Test("same_name_database_folder", d => { Write(d, "Store.cs", "class Store { string db = \"Data Source=/tmp/mvc-music-store/musicstore.sqlite\"; }"); Write(d, "appsettings.json", "{\"db\":\"Data Source=/tmp/mvc-music-store/musicstore.sqlite\"}"); }, false, false);
    Test("modern_named_assembly", d => { AssemblyFixture(d, ".NETCoreApp,Version=v8.0"); Write(d, "Launch.cs", "class Launch { void Go() { Process.Start(\"MvcMusicStore.dll\"); } }"); }, false, false);
    Test("legacy_named_assembly", d => AssemblyFixture(d, ".NETFramework,Version=v4.8"), true, false);
    Test("modern_label_with_old_dependency", d => AssemblyFixture(d, ".NETCoreApp,Version=v8.0", true), true, false);
    Test("invalid_named_assembly", d => Write(d,"MvcMusicStore.dll","not a managed assembly"), false, true);
    Test("missing_named_launch", d => Write(d,"Launch.cs","class Launch { void Go() { Assembly.LoadFrom(\"MvcMusicStore.dll\"); } }"), false, true);
    Test("unresolved_named_project_reference", d => Write(d,"App.csproj",modern.Replace("</Project>","<ItemGroup><Reference Include=\"MvcMusicStore\" /></ItemGroup></Project>")), false, true);
    Test("renamed_reference_missing_old_hint", d => Write(d,"App.csproj",modern.Replace("</Project>","<ItemGroup><Reference Include=\"Wrapper\"><HintPath>../MvcMusicStore.dll</HintPath></Reference></ItemGroup></Project>")), false, true);
    Test("missing_dotnet_named_launch", d => Write(d,"Launch.cs","class Launch { void Go() { Process.Start(\"dotnet\", \"MvcMusicStore.dll\"); } }"), false, true);
    Test("missing_named_assembly_load", d => Write(d,"Launch.cs","class Launch { void Go() { Assembly.Load(\"MvcMusicStore\"); } }"), false, true);
    Test("missing_named_launch_settings", d => Write(d,"launchSettings.json","{\"profiles\":{\"App\":{\"commandName\":\"Executable\",\"executablePath\":\"MvcMusicStore.exe\"}}}"), false, true);
    Test("locked_source_is_unresolved", d => {
        Write(d, "Locked.cs", "class Modern {}");
        using var locked = new FileStream(Path.Combine(d, "Locked.cs"), FileMode.Open, FileAccess.ReadWrite, FileShare.None);
        var scan = LegacyScan.Scan(d);
        if (scan.Unresolved.Count == 0) throw new Exception("Unreadable source must not pass by omission.");
    }, false, false);
    Console.WriteLine(JsonSerializer.Serialize(new { passed = true, tests = results.Count, results }));
    return 0;
}
finally
{
    // Delete only this invocation's explicitly created temporary fixture root.
    if (Path.GetFullPath(root).StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase)) Directory.Delete(root, true);
}
