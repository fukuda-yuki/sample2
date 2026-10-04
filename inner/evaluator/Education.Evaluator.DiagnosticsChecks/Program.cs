#nullable enable
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using Evaluator = Education.Evaluator.Program;

// Finite synthetic checks only: no submitted app, worker, browser or historical
// Run is executed or rescored. Exercise the evaluator's actual private methods.
var type = typeof(Evaluator);
SQLitePCL.Batteries_V2.Init();
object? Call(string name, params object?[] args) => type.GetMethod(name, BindingFlags.Static | BindingFlags.NonPublic)!.Invoke(null, args);
void Set(string name, object value) => type.GetField(name, BindingFlags.Static | BindingFlags.NonPublic)!.SetValue(null, value);
var results = (Dictionary<string, (string judgement, string detail)>)type.GetField("results", BindingFlags.Static | BindingFlags.NonPublic)!.GetValue(null)!;
int assertions = 0;
void Require(bool ok, string description)
{
    if (!ok) throw new Exception(description);
    assertions++;
    Console.WriteLine("PASS " + description);
}
string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
var root = Path.Combine(Path.GetTempPath(), "sample2-education-diagnostics-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    var store = Path.Combine(root, "synthetic.sqlite");
    using (var db = new SqliteConnection("Data Source=" + store))
    {
        db.Open();
        using var cmd = db.CreateCommand();
        cmd.CommandText = "CREATE TABLE Students(ID INTEGER PRIMARY KEY,LastName TEXT,FirstMidName TEXT,EnrollmentDate TEXT);"
            + "INSERT INTO Students VALUES(203,'Researcher','Casey','2026-01-02 00:00:00');";
        cmd.ExecuteNonQuery();
    }
    var create = new Dictionary<string, string> { ["LastName"] = "Researcher", ["FirstMidName"] = "Casey", ["EnrollmentDate"] = "2026-01-02" };
    var id = (long)Call("CreatedId", store, create)!;
    var row = (JsonObject)Call("Student", store, id)!;
    Require(id == 203, "unique actual ID survives midnight date suffix");
    Require(!(bool)Call("StudentMatches", row, create)!, "midnight suffix still fails strict stored-field criterion");
    var detail = (string)Call("CreatedObservation", id, row, create)!;
    Require(detail.Contains("ID=203") && detail.Contains("EnrollmentDate expected=2026-01-02; stored=2026-01-02 00:00:00"), "diagnosis reports actual ID and strict mismatch");
    Require((bool)Call("StudentMatches", new JsonObject { ["LastName"] = "Researcher", ["FirstMidName"] = "Casey", ["EnrollmentDate"] = "2026-01-02" }, create)!, "exact stored fields still pass");
    Require(!(bool)Call("Same", JsonValue.Create("2010-09-01"), "2010-09-01 00:00:00")!, "raw import date comparison remains strict");
    using (var db = new SqliteConnection("Data Source=" + store))
    {
        db.Open(); using var cmd = db.CreateCommand();
        cmd.CommandText = "INSERT INTO Students VALUES(204,'Researcher','Casey','2026-01-02');"; cmd.ExecuteNonQuery();
    }
    Require((long)Call("CreatedId", store, create)! == 0, "ambiguous submitted name pair is not assigned an arbitrary ID");

    // Hash-verified synthetic browser evidence and HTTP baseline. Keep E-003
    // failed and the later HTTP checks blocked while observing E-012 to failure.
    var baseline = Path.Combine(root, "baseline"); Directory.CreateDirectory(baseline);
    var output = Path.Combine(root, "output"); Directory.CreateDirectory(output);
    var evidence = Path.Combine(output, "evidence"); Directory.CreateDirectory(evidence);
    var school = Path.Combine(output, "browser-school"); Directory.CreateDirectory(school);
    const string artifactHash = "synthetic-artifact", specHash = "synthetic-spec", instance = "synthetic-instance";
    var requirements = new JsonArray();
    for (var i = 1; i <= 12; i++)
    {
        var judgement = i == 1 ? "pass" : i == 3 ? "fail" : "blocked";
        results[$"E-{i:000}"] = (judgement, "synthetic HTTP baseline");
        requirements.Add(new JsonObject { ["id"] = $"EDU-R-{i:000}", ["severity"] = i == 3 ? "critical" : "normal", ["judgement"] = judgement,
            ["checks"] = new JsonArray(new JsonObject { ["id"] = $"E-{i:000}" }) });
    }
    var ledger = new JsonObject { ["taskId"] = "synthetic", ["specVersion"] = Evaluator.Version, ["requirements"] = requirements };
    File.WriteAllText(Path.Combine(baseline, "evaluation.json"), new JsonObject {
        ["artifactSha256"] = artifactHash, ["specSha256"] = specHash, ["evaluationVersion"] = Evaluator.Version,
        ["requirements"] = requirements.DeepClone() }.ToJsonString());
    File.WriteAllLines(Path.Combine(baseline, "results.jsonl"), Enumerable.Range(1, 12).Select(i => new JsonObject {
        ["requirementId"] = $"EDU-R-{i:000}", ["checkId"] = $"E-{i:000}", ["judgement"] = results[$"E-{i:000}"].judgement,
        ["observation"] = "synthetic HTTP baseline" }.ToJsonString(new() { WriteIndented = false })));
    var editFields = new JsonObject { ["LastName"] = "Review", ["FirstMidName"] = "Morgan", ["EnrollmentDate"] = "2026-02-03" };
    Set("oracle", new JsonObject { ["workflow"] = new JsonObject { ["edit"] = new JsonObject { ["fields"] = editFields } } });
    Set("ledger", ledger); Set("artifactHash", artifactHash); Set("specHash", specHash); Set("evidence", evidence);
    JsonObject Ref(string name) => new() { ["path"] = name, ["sha256"] = Hash(Path.Combine(school, name)) };
    void Capture(string name, string route, int second)
    {
        File.WriteAllText(Path.Combine(school, name + ".json"), new JsonObject {
            ["tabId"] = "synthetic-tab", ["at"] = $"2026-10-04T00:00:0{second}Z", ["page"] = new JsonObject {
                ["url"] = "http://localhost:1234" + route, ["studentId"] = "203", ["firstName"] = "Morgan", ["lastName"] = "Review",
                ["enrollmentDate"] = "2026-02-03", ["fullName"] = "Review, Morgan" } }.ToJsonString());
    }
    Capture("before", "/Student/Create", 1); Capture("created", "/Student/Details/203", 2);
    Capture("edit", "/Student/Edit/203", 3); Capture("after", "/Student/Details/203", 4);
    File.WriteAllText(Path.Combine(school, "before.png"), "synthetic screenshot bytes");
    File.WriteAllText(Path.Combine(school, "after.png"), "synthetic screenshot bytes");
    var database = new JsonObject { ["student"] = new JsonObject { ["ID"] = 203, ["LastName"] = "Review", ["FirstMidName"] = "Morgan",
        ["EnrollmentDate"] = "2026-02-03 00:00:00" }, ["original_rows_preserved"] = true };
    File.WriteAllText(Path.Combine(school, "database.json"), database.ToJsonString());
    var receipt = new JsonObject { ["schemaVersion"] = 1, ["actor"] = "agent", ["artifactSha256"] = artifactHash, ["specSha256"] = specHash,
        ["runInstanceId"] = instance, ["faults"] = new JsonArray(), ["action"] = "create-edit-save", ["studentId"] = "203",
        ["before"] = Ref("before.json"), ["created"] = Ref("created.json"), ["edit"] = Ref("edit.json"), ["after"] = Ref("after.json"),
        ["beforeScreenshot"] = Ref("before.png"), ["afterScreenshot"] = Ref("after.png"), ["database"] = Ref("database.json") };
    var receiptPath = Path.Combine(school, "receipt.json"); File.WriteAllText(receiptPath, receipt.ToJsonString());
    Set("options", new Dictionary<string, string> { ["--browser-school-baseline"] = baseline, ["--browser-school-evidence"] = receiptPath,
        ["--review-run-instance-id"] = instance, ["--artifact"] = root, ["--out"] = output, ["--sequence"] = "1" });
    Call("Compose");
    Require(results["E-012"].judgement == "fail", "actual composition still fails midnight stored-date suffix");
    Require(results["E-003"].judgement == "fail" && results["E-004"].judgement == "blocked", "composition preserves HTTP failure and blocked checks");
    Call("Emit", (object)Array.Empty<string>());
    JsonObject Output() => JsonNode.Parse(File.ReadAllText(Path.Combine(output, "evaluation.json")))!.AsObject();
    var emitted = Output();
    Require(emitted["browserReviewCoverage"]!.ToString() == "agent_observed_StudentCreateEdit", "observed failing browser workflow is covered despite unrelated HTTP blocked checks");
    Require(emitted["researchStatus"]!.ToString() == "incomplete" && emitted["quality"] == null && emitted["verdict"]!.ToString() == "fail_critical", "full research completion, null quality and critical failure remain unchanged");
    Require(emitted["evaluationVersion"]!.ToString() == "education-1.0.0" && emitted["evaluatorImplementationRevision"]!.ToString() == Evaluator.ImplementationRevision, "criteria version stays frozen; implementation revision is explicit");
    Call("Emit", (object)new[] { "synthetic observer fault" });
    Require(Output()["browserReviewCoverage"]!.ToString() == "not_run_or_partial", "observer fault still prevents complete browser coverage");
    database["student"]!["EnrollmentDate"] = "2026-02-03";
    File.WriteAllText(Path.Combine(school, "database.json"), database.ToJsonString());
    receipt["database"] = Ref("database.json"); File.WriteAllText(receiptPath, receipt.ToJsonString());
    Call("Compose");
    Require(results["E-012"].judgement == "pass", "exact UI and stored date still pass browser criterion");
    results["E-012"] = ("blocked", "synthetic unobserved browser"); Call("Emit", (object)Array.Empty<string>());
    Require(Output()["browserReviewCoverage"]!.ToString() == "not_run_or_partial", "unobserved E-012 remains partial");
    Console.WriteLine($"All {assertions} finite synthetic assertions passed; no live execution or historical rescore.");
}
finally
{
    SqliteConnection.ClearAllPools();
    // The target is a fixed-prefix directory created above beneath OS temp.
    if (Path.GetDirectoryName(Path.GetFullPath(root)) != Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar))
        throw new Exception("Unexpected temporary check root");
    Directory.Delete(root, recursive: true);
}
