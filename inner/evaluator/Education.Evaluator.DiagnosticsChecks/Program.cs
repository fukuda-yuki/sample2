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
    var id = (long)Call("CreatedId", store, new HashSet<long>())!;
    var row = (JsonObject)Call("Student", store, id)!;
    Require(id == 203, "unique actual ID survives midnight date suffix");
    Require((bool)Call("StudentMatches", row, create)!, "DB calendar date accepts exact midnight representation");
    var detail = (string)Call("CreatedObservation", id, row, create)!;
    Require(detail.Contains("ID=203") && detail.Contains("match"), "diagnosis reports actual ID and semantic match");
    Require((bool)Call("StudentMatches", new JsonObject { ["LastName"] = "Researcher", ["FirstMidName"] = "Casey", ["EnrollmentDate"] = "2026-01-02" }, create)!, "exact stored fields still pass");
    Require(!(bool)Call("Same", JsonValue.Create("2010-09-01"), "2010-09-01 00:00:00")!, "generic non-calendar comparison remains strict");
    foreach(var value in new[]{"2026-01-02","2026-01-02 00:00:00","2026-01-02T00:00:00","2026-01-02T00:00:00.0","2026-01-02 00:00:00.000","2026-01-02T00:00:00.0000000","2026-01-02T00:00:00.00000000"})
        Require((bool)Call("CalendarDateMatches","2026-01-02",value)!, "accepted DB date representation: "+value);
    foreach(var value in new[]{"2026-01-03","2026-01-02 00:00:01","2026-01-02T00:00:00Z","2026-01-02T00:00:00+00:00","2026-01-02T00:00:00.00000001","2026-01-02T00:00:00.","2026-01-02T00:00:00.000\n","2026-1-2","2026-02-30"," 2026-01-02", "2026-01-02 "})
        Require(!(bool)Call("CalendarDateMatches","2026-01-02",value)!, "rejected DB date representation: "+value);
    Require((bool)Call("CalendarDateMatches","2024-02-29","2024-02-29T00:00:00")! && !(bool)Call("CalendarDateMatches","2026-02-29","2026-02-29")!, "calendar leap boundary is validated");
    Require((bool)Call("SameField","Departments","StartDate",JsonValue.Create("2010-09-01"),"2010-09-01 00:00:00")!, "department StartDate is a calendar field");
    Require(!(bool)Call("SameField","Departments","Name",JsonValue.Create("2010-09-01"),"2010-09-01 00:00:00")!, "names are never date-normalized");
    Require((long)Call("CreatedId",store,new HashSet<long>{203})! == 0, "preexisting same-name row is never reused as newly created ID");
    using (var db = new SqliteConnection("Data Source=" + store))
    {
        db.Open(); using var cmd = db.CreateCommand();
        cmd.CommandText = "INSERT INTO Students VALUES(204,'Researcher','Casey','2026-01-02');"; cmd.ExecuteNonQuery();
    }
    Require((long)Call("CreatedId", store, new HashSet<long>())! == 0, "two added IDs are ambiguous regardless of submitted names");
    Require((long)Call("CreatedId", store, new HashSet<long>{203})! == 204, "same-name original plus one new row selects only the true new ID");
    Require((long)Call("CreatedId", store, new HashSet<long>{202,203})! == 0, "removing any pre-create ID blocks dependent edit identity");

    // Runtime WAL data is valid: inspect one read transaction, without treating
    // a sidecar as a product failure. The databases here are synthetic copies.
    var walStore=Path.Combine(root,"wal.sqlite");
    using(var writer=new SqliteConnection("Data Source="+walStore+";Pooling=False"))
    {
        writer.Open();using var command=writer.CreateCommand();
        command.CommandText="PRAGMA journal_mode=WAL;PRAGMA wal_autocheckpoint=0;CREATE TABLE Students(ID INTEGER PRIMARY KEY,LastName TEXT,FirstMidName TEXT,EnrollmentDate TEXT);CREATE TABLE Departments(DepartmentID INTEGER PRIMARY KEY,StartDate TEXT);CREATE TABLE Courses(CourseID INTEGER PRIMARY KEY);CREATE TABLE Enrollments(EnrollmentID INTEGER PRIMARY KEY);INSERT INTO Students VALUES(203,'Researcher','Casey','2026-01-02 00:00:00');INSERT INTO Departments VALUES(1,'2010-09-01T00:00:00');";
        command.ExecuteNonQuery();
        Set("oracle",JsonNode.Parse("""{"tables":{"Students":{"key":"ID","rows":[{"ID":203,"LastName":"Researcher","FirstMidName":"Casey","EnrollmentDate":"2026-01-02"}]},"Departments":{"key":"DepartmentID","rows":[{"DepartmentID":1,"StartDate":"2010-09-01"}]},"Courses":{"key":"CourseID","rows":[]},"Enrollments":{"key":"EnrollmentID","rows":[]}}}""")!);
        var observationArgs=new object?[]{walStore,null,false};
        Require(File.Exists(walStore+"-wal")&&(bool)Call("RowsMatch",observationArgs)!, "read transaction observes committed WAL calendar values");
        using(var pending=writer.BeginTransaction())
        {
            command.Transaction=pending;command.CommandText="UPDATE Students SET FirstMidName='uncommitted' WHERE ID=203";command.ExecuteNonQuery();
            Require((bool)Call("RowsMatch",new object?[]{walStore,null,false})!, "deferred read does not request writer lock or observe uncommitted WAL changes");
            pending.Rollback();command.Transaction=null;
        }
        command.CommandText="UPDATE Students SET FirstMidName='wrong' WHERE ID=203";command.ExecuteNonQuery();
        Require(!(bool)Call("RowsMatch",new object?[]{walStore,null,false})!, "wrong original value remains a product mismatch");
        command.CommandText="ALTER TABLE Students RENAME TO PreviousStudents;CREATE TABLE Students(ID INTEGER,LastName TEXT,FirstMidName TEXT,EnrollmentDate TEXT);INSERT INTO Students VALUES(203,'Researcher','Casey','2026-01-02');INSERT INTO Students VALUES(203,'Researcher','Casey','2026-01-02');";command.ExecuteNonQuery();
        Require(!(bool)Call("RowsMatch",new object?[]{walStore,null,false})!, "duplicate original IDs cannot hide behind the first matching row");
        Require((long)Call("CreatedId",walStore,new HashSet<long>())! == 0, "duplicate newly stored ID is never identified as one valid new student");
        command.CommandText="ALTER TABLE Departments ADD COLUMN Note TEXT";command.ExecuteNonQuery();var nullSnapshot=(string)Call("Snapshot",walStore,true)!;
        command.CommandText="UPDATE Departments SET Note='' WHERE DepartmentID=1";command.ExecuteNonQuery();
        Require((string)Call("Snapshot",walStore,true)! != nullSnapshot, "invalid-input snapshot distinguishes SQL null from empty text");
    }
    Require(!(bool)Call("RowsMatch",new object?[]{store,null,false})!, "missing required domain tables are observed schema mismatches");
    var corrupt=Path.Combine(root,"corrupt.sqlite");File.WriteAllText(corrupt,"not a sqlite database");
    bool Fault(string path)
    {
        try{Call("RowsMatch",new object?[]{path,null,false});return false;}
        catch(TargetInvocationException ex){return ex.InnerException is SqliteException;}
    }
    Require(Fault(corrupt), "corrupt SQLite read is an observer fault, never a value mismatch");
    Require(Fault(Path.Combine(root,"absent.sqlite")), "unreadable absent SQLite is an observer fault, never a product false fail");
    var caseStore=Path.Combine(root,"identifier-case.sqlite");
    using(var db=new SqliteConnection("Data Source="+caseStore))
    {
        db.Open();using var command=db.CreateCommand();
        command.CommandText="CREATE TABLE students(id INTEGER PRIMARY KEY,lastname TEXT,firstmidname TEXT,enrollmentdate TEXT);CREATE TABLE departments(departmentid INTEGER PRIMARY KEY,startdate TEXT);CREATE TABLE courses(courseid INTEGER PRIMARY KEY);CREATE TABLE enrollments(enrollmentid INTEGER PRIMARY KEY);INSERT INTO students VALUES(203,'Researcher','Casey','2026-01-02');INSERT INTO departments VALUES(1,'2010-09-01');";command.ExecuteNonQuery();
    }
    Require((bool)Call("RowsMatch",new object?[]{caseStore,null,false})!, "schema checks honor SQLite identifier case equivalence");
    Require((bool)Call("StudentMatches",(JsonObject)Call("Student",caseStore,203L)!,create)!, "student observation canonicalizes query field labels, not product values");
    var markers=(HashSet<long>)Call("Ids","<div id='student-101'></div><div id='student-101'></div>","student-")!;
    Require(!markers.SetEquals(new[]{101L}), "duplicate student row markers do not collapse into a passing ID set");

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
        ["EnrollmentDate"] = "2026-02-03 00:00:00" }, ["original_rows_preserved"] = true, ["read_only"] = true };
    File.WriteAllText(Path.Combine(school, "database.json"), database.ToJsonString());
    File.WriteAllText(Path.Combine(school,"request.json"),new JsonObject{["artifactSha256"]=artifactHash,["specSha256"]=specHash,["runInstanceId"]=instance,["evaluationVersion"]=Evaluator.Version,["baseUrl"]="http://localhost:1234"}.ToJsonString());
    var receipt = new JsonObject { ["schemaVersion"] = 2, ["actor"] = "agent", ["artifactSha256"] = artifactHash, ["specSha256"] = specHash,
        ["baseUrl"]="http://localhost:1234",["requestSha256"]=Hash(Path.Combine(school,"request.json")),["productFailures"]=new JsonArray(),
        ["runInstanceId"] = instance, ["faults"] = new JsonArray(), ["action"] = "create-edit-save", ["studentId"] = "203",
        ["before"] = Ref("before.json"), ["created"] = Ref("created.json"), ["edit"] = Ref("edit.json"), ["after"] = Ref("after.json"),
        ["beforeScreenshot"] = Ref("before.png"), ["afterScreenshot"] = Ref("after.png"), ["database"] = Ref("database.json") };
    var receiptPath = Path.Combine(school, "receipt.json"); File.WriteAllText(receiptPath, receipt.ToJsonString());
    Set("options", new Dictionary<string, string> { ["--browser-school-baseline"] = baseline, ["--browser-school-evidence"] = receiptPath,
        ["--review-run-instance-id"] = instance, ["--artifact"] = root, ["--out"] = output, ["--sequence"] = "1" });
    Call("Compose");
    Require(results["E-012"].judgement == "pass", "actual composition accepts DB midnight while requiring exact UI date");
    Require(results["E-003"].judgement == "fail" && results["E-004"].judgement == "blocked", "composition preserves HTTP failure and blocked checks");
    Call("Emit", (object)Array.Empty<string>());
    JsonObject Output() => JsonNode.Parse(File.ReadAllText(Path.Combine(output, "evaluation.json")))!.AsObject();
    var emitted = Output();
    Require(emitted["browserReviewCoverage"]!.ToString() == "agent_observed_StudentCreateEdit", "observed failing browser workflow is covered despite unrelated HTTP blocked checks");
    Require(emitted["researchStatus"]!.ToString() == "incomplete" && emitted["quality"] == null && emitted["verdict"]!.ToString() == "fail_critical", "full research completion, null quality and critical failure remain unchanged");
    Require(emitted["evaluationVersion"]!.ToString() == "education-1.1.0" && emitted["evaluatorImplementationRevision"]!.ToString() == Evaluator.ImplementationRevision, "new criteria version is explicit; historical version is not rewritten");
    Call("Emit", (object)new[] { "synthetic observer fault" });
    Require(Output()["browserReviewCoverage"]!.ToString() == "not_run_or_partial", "observer fault still prevents complete browser coverage");
    database["student"]!["EnrollmentDate"] = "2026-02-03";
    File.WriteAllText(Path.Combine(school, "database.json"), database.ToJsonString());
    receipt["database"] = Ref("database.json"); File.WriteAllText(receiptPath, receipt.ToJsonString());
    Call("Compose");
    Require(results["E-012"].judgement == "pass", "exact UI and stored date still pass browser criterion");
    var afterPath=Path.Combine(school,"after.json");var after=JsonNode.Parse(File.ReadAllText(afterPath))!;
    after["page"]!["enrollmentDate"]="2026-02-03 00:00:00";File.WriteAllText(afterPath,after.ToJsonString());receipt["after"]=Ref("after.json");File.WriteAllText(receiptPath,receipt.ToJsonString());
    Call("Compose");Require(results["E-012"].judgement=="fail", "DB date equivalence never relaxes the exact UI date contract");
    database["original_rows_preserved"]=false;File.WriteAllText(Path.Combine(school,"database.json"),database.ToJsonString());receipt["database"]=Ref("database.json");File.WriteAllText(receiptPath,receipt.ToJsonString());
    Call("Compose");Require(results["E-012"].judgement=="fail", "changed original rows still fail after date repair");

    // A real owned operation response is a product fact even if a later observer
    // fault prevents the rest of the workflow; an exception alone proves none.
    var failure=new JsonObject{["caseId"]="school-create-submit-001",["checkId"]="E-012",["operation"]="school-create-submit",["method"]="POST",["url"]="http://localhost:1234/Student/Create",["status"]=500,["clickConfirmed"]=true};
    var failureEvidence=failure.DeepClone();failureEvidence["resourceType"]="document";failureEvidence["requestPayload"]="LastName=Review";failureEvidence["responseBody"]="synthetic product error";
    File.WriteAllText(Path.Combine(school,"response.json"),failureEvidence.ToJsonString());failure["evidence"]=Ref("response.json");
    receipt["productFailures"]=new JsonArray(failure);receipt["action"]="not-run";receipt["faults"]=new JsonArray("synthetic later screenshot failure");File.WriteAllText(receiptPath,receipt.ToJsonString());
    bool CompositionFault()
    {
        try{Call("Compose");return false;}catch(TargetInvocationException ex){return ex.InnerException is IOException or InvalidDataException;}
    }
    Require(CompositionFault()&&results["E-012"].judgement=="fail", "hash-bound owned HTTP500 remains a product failure despite later observer fault");
    Call("Emit",(object)new[]{"synthetic later screenshot failure"});
    Require(Output()["quality"]==null&&Output()["browserReviewCoverage"]!.ToString()=="not_run_or_partial", "HTTP500 plus observer fault never claims completed coverage or numeric quality");
    receipt["faults"]=new JsonArray();File.WriteAllText(receiptPath,receipt.ToJsonString());Call("Compose");Call("Emit",(object)Array.Empty<string>());
    Require(Output()["quality"]==null&&Output()["browserReviewCoverage"]!.ToString()=="not_run_or_partial", "partial HTTP500 observation alone is not the full browser workflow");
    failure["url"]="http://foreign.invalid/Student/Create";File.WriteAllText(receiptPath,receipt.ToJsonString());
    Require(CompositionFault()&&results["E-012"].judgement=="blocked", "foreign or altered response evidence cannot produce a product failure");
    receipt["productFailures"]=new JsonArray();receipt["faults"]=new JsonArray("synthetic arbitrary HTTP500-looking exception");File.WriteAllText(receiptPath,receipt.ToJsonString());
    Require(CompositionFault()&&results["E-012"].judgement=="blocked", "error text mentioning HTTP500 does not substitute for observed product response");
    receipt["productFailures"]=new JsonArray();receipt["faults"]=new JsonArray();receipt["action"]="create-edit-save";
    foreach(var name in new[]{"before","created","edit","after"})
    {
        var capturePath=Path.Combine(school,name+".json");var capture=JsonNode.Parse(File.ReadAllText(capturePath))!;
        capture["page"]!["url"]=capture["page"]!["url"]!.ToString().Replace("http://localhost:1234","http://foreign.invalid:1234");
        File.WriteAllText(capturePath,capture.ToJsonString());receipt[name]=Ref(name+".json");
    }
    File.WriteAllText(receiptPath,receipt.ToJsonString());
    Require(CompositionFault()&&results["E-012"].judgement=="blocked", "four mutually consistent foreign captures cannot substitute for the owned app");
    failure["url"]="http://localhost:1234/Student/Create";receipt["productFailures"]=new JsonArray(failure.DeepClone(),new JsonObject{["caseId"]="malformed-later"});receipt["action"]="not-run";File.WriteAllText(receiptPath,receipt.ToJsonString());
    bool AnyCompositionFault(){try{Call("Compose");return false;}catch(TargetInvocationException){return true;}}
    Require(AnyCompositionFault()&&results["E-012"].judgement=="fail", "valid first product failure remains sticky if later response evidence is malformed");
    results["E-012"] = ("blocked", "synthetic unobserved browser"); Call("Emit", (object)Array.Empty<string>());
    Require(Output()["browserReviewCoverage"]!.ToString() == "not_run_or_partial", "unobserved E-012 remains partial");
    if(args.Length==2 && args[0]=="--product-receipt")
    {
        var actualRoot=Path.GetDirectoryName(Path.GetFullPath(args[1]))!;
        var actualReceipt=JsonNode.Parse(File.ReadAllText(args[1]))!;
        Set("artifactHash",actualReceipt["artifactSha256"]!.ToString());Set("specHash",actualReceipt["specSha256"]!.ToString());
        Set("options",new Dictionary<string,string>{["--review-run-instance-id"]=actualReceipt["runInstanceId"]!.ToString()});
        Call("BrowserProductFailures",actualRoot,actualReceipt);
        Require(results["E-012"].judgement=="fail", "actual independently collected browser HTTP500 receipt interoperates with compiled evaluator");
    }
    Console.WriteLine($"All {assertions} finite synthetic assertions passed; no live execution or historical rescore.");
}
catch(Exception ex)
{
    Console.Error.WriteLine("FAIL "+ex);Environment.ExitCode=1;
}
finally
{
    SqliteConnection.ClearAllPools();
    // The target is a fixed-prefix directory created above beneath OS temp.
    if (Path.GetDirectoryName(Path.GetFullPath(root)) != Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar))
        throw new Exception("Unexpected temporary check root");
    Directory.Delete(root, recursive: true);
}
