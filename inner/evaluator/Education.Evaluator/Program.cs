using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml.Linq;
using AngleSharp.Html.Parser;
using Microsoft.Data.Sqlite;

namespace Education.Evaluator;

// This evaluator executes the submitted product. Expectations are frozen,
// researcher-owned source/data authority, not values returned by the product.
public static class Program
{
    public const string Version = "education-1.0.0";
    static readonly JsonSerializerOptions Json = new() { WriteIndented = true };
    static readonly string[] Tables = { "Students", "Departments", "Courses", "Enrollments" };
    static Dictionary<string,string> options;
    static JsonObject ledger, oracle;
    static readonly Dictionary<string,(string judgement,string detail)> results = new();
    static string artifactHash, specHash, evidence;

    public static int Main(string[] args)
    {
        options = new();
        for (var i=0; i<args.Length; i+=2)
        {
            if (i+1>=args.Length || !args[i].StartsWith("--")) throw new ArgumentException("Expected named value pairs.");
            options.Add(args[i],args[i+1]);
        }
        Directory.CreateDirectory(O("--out"));
        evidence=Path.Combine(O("--out"),"evidence");Directory.CreateDirectory(evidence);
        ledger=JsonNode.Parse(File.ReadAllText(O("--spec"))).AsObject();
        artifactHash=HashTree(O("--artifact"));specHash=HashFile(O("--spec"));
        for(var i=1;i<=12;i++) results[$"E-{i:000}"]=("blocked","Prerequisite or browser action not observed.");
        try
        {
            if(O("--evaluation-version")!=Version || S(ledger,"specVersion")!=Version)
                throw new InvalidDataException("Education evaluation/ledger version mismatch.");
            var ids=ledger["requirements"].AsArray().SelectMany(r=>r["checks"].AsArray()).Select(c=>S(c,"id")).ToList();
            if(ids.Count!=12 || !ids.Order().SequenceEqual(results.Keys.Order())) throw new InvalidDataException("Check inventory mismatch.");
            oracle=JsonNode.Parse(File.ReadAllText(Path.Combine(Path.GetDirectoryName(O("--spec")),"migration-oracle.json"))).AsObject();
            if(S(oracle,"task_id")!=S(ledger,"taskId")) throw new InvalidDataException("Oracle/task identity mismatch.");
            ValidateAssets();
            if(options.ContainsKey("--browser-school-baseline")) Compose();
            else Observe();
            return Emit(Array.Empty<string>());
        }
        catch(Exception ex)
        {
            File.WriteAllText(Path.Combine(evidence,"evaluator-fault.txt"),ex.ToString());
            // Existing confirmed product failures survive a subsequent observer fault.
            return Emit(new[]{ex.GetType().Name+": "+ex.Message});
        }
    }

    static string O(string name)=>options[name];
    static string S(JsonNode node,string name)=>node[name]?.ToString();
    static string HashFile(string path)=>Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
    static string HashTree(string root)
    {
        var paths=Directory.EnumerateFiles(root,"*",SearchOption.AllDirectories)
            .Select(p=>Path.GetRelativePath(root,p))
            .Where(p=>!p.Split(Path.DirectorySeparatorChar,Path.AltDirectorySeparatorChar).Any(x=>new[]{"bin","obj",".git"}.Contains(x,StringComparer.OrdinalIgnoreCase)))
            .OrderBy(p=>p.Replace('/','\\'),StringComparer.Ordinal);
        var text=string.Concat(paths.Select(p=>p.Replace('\\','/')+" "+HashFile(Path.Combine(root,p))+"\n"));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();
    }
    static void Check(int id,bool pass,string detail)=>results[$"E-{id:000}"]=(pass?"pass":"fail",detail);
    static SqliteConnection Database(string path)
    {
        var c=new SqliteConnection(new SqliteConnectionStringBuilder{DataSource=path,Mode=SqliteOpenMode.ReadOnly,Pooling=false}.ToString());c.Open();return c;
    }
    static bool Same(JsonNode expected,object actual)
    {
        if(expected==null) return actual is null or DBNull;
        if(actual is null or DBNull) return false;
        var a=Convert.ToString(actual,CultureInfo.InvariantCulture);var b=expected.ToString();
        return decimal.TryParse(a,NumberStyles.Number,CultureInfo.InvariantCulture,out var x)
            && decimal.TryParse(b,NumberStyles.Number,CultureInfo.InvariantCulture,out var y)?x==y:a==b;
    }
    static bool RowsMatch(string path,out string detail,bool raw=false)
    {
        var missing=new List<string>();
        try
        {
            using var db=Database(path);
            foreach(var table in Tables)
            {
                var contract=oracle["tables"][table];var key=S(contract,"key");
                foreach(var row in contract["rows"].AsArray())
                {
                    using var cmd=db.CreateCommand();
                    var from=raw?table switch {"Students"=>"Person","Departments"=>"Department","Courses"=>"Course",_=>"Enrollment"}:table;
                    var fields=row.AsObject().Select(k=>raw&&table=="Students"&&k.Key=="FirstMidName"?"FirstName AS FirstMidName":"\""+k.Key+"\"");
                    cmd.CommandText="SELECT "+string.Join(",",fields)+" FROM \""+from+"\" WHERE \""+key+"\"=$id"+(raw&&table=="Students"?" AND Discriminator='Student'":"");
                    cmd.Parameters.AddWithValue("$id",row[key].ToString());using var reader=cmd.ExecuteReader();
                    if(!reader.Read()) missing.Add(table+"/"+row[key]+" absent");
                    else foreach(var value in row.AsObject()) if(!Same(value.Value,reader[value.Key])) missing.Add(table+"/"+row[key]+"/"+value.Key+" differs");
                }
            }
        }
        catch(SqliteException ex){missing.Add("SQLite "+ex.SqliteErrorCode+": "+ex.Message);}
        detail=missing.Count==0?"Every specified original row/column is preserved.":string.Join("; ",missing);
        return missing.Count==0;
    }
    static void ValidateAssets()
    {
        var assets=Path.GetDirectoryName(O("--spec"));
        if(!RowsMatch(Path.Combine(assets,"initial-store.sqlite"),out var target)) throw new InvalidDataException("Prepared target disagrees with independent oracle: "+target);
        if(!RowsMatch(Path.Combine(assets,"legacy-school.sqlite"),out var raw,true)) throw new InvalidDataException("Raw source projection disagrees with independent oracle: "+raw);
        using(var source=Database(Path.Combine(assets,"legacy-school.sqlite")))
        using(var targetDb=Database(Path.Combine(assets,"initial-store.sqlite")))
            foreach(var table in Tables)
            {
                using var a=source.CreateCommand();using var b=targetDb.CreateCommand();
                var original=table switch {"Students"=>"Person","Departments"=>"Department","Courses"=>"Course",_=>"Enrollment"};
                a.CommandText="SELECT COUNT(*) FROM \""+original+"\""+(table=="Students"?" WHERE Discriminator='Student'":"");
                b.CommandText="SELECT COUNT(*) FROM \""+table+"\"";
                var expected=oracle["tables"][table]["rows"].AsArray().Count;
                if((long)a.ExecuteScalar()!=expected||(long)b.ExecuteScalar()!=expected)throw new InvalidDataException("Oracle does not cover every supplied source/target row: "+table);
            }
        if(!oracle["tables"].AsObject().Select(x=>x.Key).Order().SequenceEqual(Tables.Order())) throw new InvalidDataException("Expected four domain tables.");
        if(oracle["grade_map"]==null || oracle["authority"]?.AsArray().Count==0) throw new InvalidDataException("Independent grade/source authority absent.");
    }
    static JsonObject Student(string path,long id)
    {
        using var db=Database(path);using var cmd=db.CreateCommand();cmd.CommandText="SELECT ID,LastName,FirstMidName,EnrollmentDate FROM Students WHERE ID=$id";cmd.Parameters.AddWithValue("$id",id);
        using var r=cmd.ExecuteReader();if(!r.Read()) return null;var row=new JsonObject();
        for(var i=0;i<r.FieldCount;i++) row[r.GetName(i)]=JsonValue.Create(Convert.ToString(r.GetValue(i),CultureInfo.InvariantCulture));return row;
    }
    static string Snapshot(string path,bool includeStudents=true)
    {
        using var db=Database(path);var text=new StringBuilder();
        foreach(var table in Tables.Where(t=>includeStudents||t!="Students"))
        {
            using var cmd=db.CreateCommand();cmd.CommandText="SELECT * FROM \""+table+"\" ORDER BY \""+S(oracle["tables"][table],"key")+"\"";
            using var r=cmd.ExecuteReader();while(r.Read()) for(var i=0;i<r.FieldCount;i++) text.Append(table).Append('/').Append(r.GetName(i)).Append('=').Append(Convert.ToString(r.GetValue(i),CultureInfo.InvariantCulture)).Append('\0');
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text.ToString()))).ToLowerInvariant();
    }
    static long StudentCount(string path)
    {
        using var db=Database(path);using var cmd=db.CreateCommand();cmd.CommandText="SELECT COUNT(*) FROM Students";return (long)cmd.ExecuteScalar();
    }
    static bool NoLegacyBinary(string published)
    {
        foreach(var path in Directory.EnumerateFiles(published,"*.dll",SearchOption.AllDirectories))
        {
            using var stream=File.OpenRead(path);using var pe=new PEReader(stream);
            if(!pe.HasMetadata)continue;var metadata=pe.GetMetadataReader();
            if(metadata.AssemblyReferences.Any(h=>metadata.GetString(metadata.GetAssemblyReference(h).Name)=="System.Web"))return false;
            foreach(var handle in metadata.CustomAttributes)
            {
                var attribute=metadata.GetCustomAttribute(handle);var constructor=attribute.Constructor;
                EntityHandle type=constructor.Kind==HandleKind.MemberReference?metadata.GetMemberReference((MemberReferenceHandle)constructor).Parent
                    :constructor.Kind==HandleKind.MethodDefinition?metadata.GetMethodDefinition((MethodDefinitionHandle)constructor).GetDeclaringType():default;
                string name=null,space=null;
                if(type.Kind==HandleKind.TypeReference){var t=metadata.GetTypeReference((TypeReferenceHandle)type);name=metadata.GetString(t.Name);space=metadata.GetString(t.Namespace);}
                if(type.Kind==HandleKind.TypeDefinition){var t=metadata.GetTypeDefinition((TypeDefinitionHandle)type);name=metadata.GetString(t.Name);space=metadata.GetString(t.Namespace);}
                if(name=="TargetFrameworkAttribute"&&space=="System.Runtime.Versioning"
                    &&Encoding.UTF8.GetString(metadata.GetBlobBytes(attribute.Value)).Contains(".NETFramework"))return false;
            }
        }
        return true;
    }
    static Dictionary<string,string> Fields(JsonNode node)=>node.AsObject().ToDictionary(k=>k.Key,k=>k.Value.ToString());
    static bool StudentMatches(JsonObject row,Dictionary<string,string> fields)=>row!=null&&fields.All(f=>S(row,f.Key)==f.Value);
    static long CreatedId(string path,Dictionary<string,string> fields)
    {
        using var db=Database(path);using var cmd=db.CreateCommand();cmd.CommandText="SELECT ID FROM Students WHERE LastName=$last AND FirstMidName=$first AND EnrollmentDate=$date";
        cmd.Parameters.AddWithValue("$last",fields["LastName"]);cmd.Parameters.AddWithValue("$first",fields["FirstMidName"]);cmd.Parameters.AddWithValue("$date",fields["EnrollmentDate"]);
        using var r=cmd.ExecuteReader();if(!r.Read()) return 0;var id=r.GetInt64(0);return r.Read()?0:id;
    }
    sealed record Response(int Status,string Body,string Location);
    sealed class Web:IDisposable
    {
        readonly HttpClient http;
        public Web(string url){http=new HttpClient(new HttpClientHandler{AllowAutoRedirect=false,UseCookies=true}){BaseAddress=new Uri(url),Timeout=TimeSpan.FromSeconds(15)};}
        public Response Get(string route)=>Send(new HttpRequestMessage(HttpMethod.Get,route));
        public Response Post(string route,Dictionary<string,string> values)=>Send(new HttpRequestMessage(HttpMethod.Post,route){Content=new FormUrlEncodedContent(values)});
        Response Send(HttpRequestMessage request)
        {
            using var r=http.Send(request);var body=r.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            var location=r.Headers.Location==null?null:new Uri(request.RequestUri,r.Headers.Location);
            var route=location==null?null:location.GetLeftPart(UriPartial.Authority)==http.BaseAddress.GetLeftPart(UriPartial.Authority)?location.AbsolutePath.TrimEnd('/'):location.AbsoluteUri;
            File.AppendAllText(Path.Combine(evidence,"http.log"),$"{request.Method} {request.RequestUri} => {(int)r.StatusCode}, Location={r.Headers.Location}\n{body}\n");
            return new((int)r.StatusCode,body,route);
        }
        public void Dispose()=>http.Dispose();
    }
    static string Marker(string html,string id)
    {
        var nodes=new HtmlParser().ParseDocument(html).QuerySelectorAll("[id='"+id+"']");return nodes.Length==1?nodes[0].TextContent.Trim():null;
    }
    static HashSet<long> Ids(string html,string prefix)=>new HtmlParser().ParseDocument(html).QuerySelectorAll("[id^='"+prefix+"']")
        .Select(e=>long.TryParse(e.Id[prefix.Length..],out var id)?id:0).Where(id=>id>0).ToHashSet();
    static Dictionary<string,string> Form(string html,Dictionary<string,string> fields)
    {
        var result=new HtmlParser().ParseDocument(html).QuerySelectorAll("input[type='hidden'][name]").ToDictionary(x=>x.GetAttribute("name"),x=>x.GetAttribute("value")??"");
        foreach(var f in fields) result[f.Key]=f.Value;return result;
    }
    static bool HasForm(string html)=>new[]{"LastName","FirstMidName","EnrollmentDate"}.All(n=>new HtmlParser().ParseDocument(html).QuerySelectorAll("[name='"+n+"']").Length==1);
    static List<Dictionary<string,string>> Invalids(Dictionary<string,string> valid)
    {
        var tests=new List<Dictionary<string,string>>();
        foreach(var field in new[]{"LastName","FirstMidName","EnrollmentDate"}) {var f=new Dictionary<string,string>(valid);f.Remove(field);tests.Add(f);}
        foreach(var field in new[]{"LastName","FirstMidName","EnrollmentDate"}) {var f=new Dictionary<string,string>(valid);f[field]="   ";tests.Add(f);}
        foreach(var field in new[]{"LastName","FirstMidName"}) {var f=new Dictionary<string,string>(valid);f[field]=new string('x',51);tests.Add(f);}
        var date=new Dictionary<string,string>(valid);date["EnrollmentDate"]="2026-02-30";tests.Add(date);return tests;
    }
    static void Observe()
    {
        using var host=new AppHost(O("--artifact"),O("--work"),evidence);
        if(!AppHost.DotnetAvailable(out var sdk)) throw new IOException("dotnet unavailable: "+sdk);
        var projects=AppHost.FindWebProjects(O("--artifact"));
        if(projects.Count==0){Check(1,false,"No runnable Web project.");return;}
        host.SelectProject(projects[0]);var project=XDocument.Load(projects[0]);
        var tfm=project.Descendants().FirstOrDefault(e=>e.Name.LocalName=="TargetFramework")?.Value;
        var references=Directory.EnumerateFiles(O("--artifact"),"*.csproj",SearchOption.AllDirectories).SelectMany(p=>XDocument.Load(p).Descendants()).ToList();
        var modernReferences=references.All(e=>e.Name.LocalName is not("Reference" or "PackageReference")||!(e.Attribute("Include")?.Value??"").StartsWith("System.Web",StringComparison.OrdinalIgnoreCase))
            && references.Where(e=>e.Name.LocalName=="TargetFramework").All(e=>!e.Value.StartsWith("net4"));
        Check(2,modernReferences,"No System.Web/net4x project dependencies.");
        var publish=host.Publish();File.WriteAllText(Path.Combine(evidence,"publish.log"),publish.StdOut+publish.StdErr);
        if(publish.ExitCode!=0||host.FindEntryAssembly()==null){Check(1,false,"dotnet publish failed: "+publish.ExitCode);return;}
        Check(2,modernReferences&&NoLegacyBinary(host.PublishDir),"Project and published managed assembly metadata contain no System.Web/.NETFramework execution dependency.");
        host.Start();var ready=host.WaitReady(TimeSpan.FromSeconds(30));
        Check(1,ready.Ready&&tfm!=null&&System.Text.RegularExpressions.Regex.IsMatch(tfm,"^net([8-9]|[1-9][0-9]+)\\."),"Published web app / readiness: "+ready.Detail);
        if(!ready.Ready)return;
        var imported=RowsMatch(host.DatabasePath,out var initial);
        Check(3,imported,"Actual initial missing-path raw schema import: "+initial);
        if(!imported)return;
        using var web=new Web(host.BaseUrl);
        var home=web.Get("/");var list=web.Get("/Student");
        var students=oracle["tables"]["Students"]["rows"].AsArray();var ids=students.Select(s=>long.Parse(S(s,"ID"))).ToHashSet();
        var links=new HtmlParser().ParseDocument(home.Body).QuerySelectorAll("a[href]").Select(a=>a.GetAttribute("href")).ToList();
        var search=web.Get("/Student?SearchString="+Uri.EscapeDataString(S(oracle["workflow"]["search"],"query")));
        var expectedSearch=oracle["workflow"]["search"]["student_ids"].AsArray().Select(x=>long.Parse(x.ToString())).ToHashSet();
        var listDoc=new HtmlParser().ParseDocument(list.Body);
        var ordinaryLinks=ids.All(id=>listDoc.GetElementById("student-"+id)?.QuerySelectorAll("a[href]").Select(a=>a.GetAttribute("href")).Contains("/Student/Details/"+id)==true
            &&listDoc.GetElementById("student-"+id)?.QuerySelectorAll("a[href]").Select(a=>a.GetAttribute("href")).Contains("/Student/Edit/"+id)==true);
        Check(4,home.Status==200&&links.Contains("/Student")&&links.Contains("/Course")&&list.Status==200&&Ids(list.Body,"student-").SetEquals(ids)&&ordinaryLinks
            &&search.Status==200&&Ids(search.Body,"student-").SetEquals(expectedSearch),"Home/list/search student identifiers and routes.");
        var detailsOk=true;var notes=new List<string>();
        foreach(var s in students)
        {
            var id=S(s,"ID");var d=web.Get("/Student/Details/"+id);var doc=new HtmlParser().ParseDocument(d.Body);
            var fields=new[]{("student-id","ID"),("student-first-name","FirstMidName"),("student-last-name","LastName"),("student-enrollment-date","EnrollmentDate")};
            var ok=d.Status==200&&fields.All(f=>Marker(d.Body,f.Item1)==S(s,f.Item2))&&Marker(d.Body,"student-full-name")==S(s,"LastName")+", "+S(s,"FirstMidName");
            var expected=oracle["tables"]["Enrollments"]["rows"].AsArray().Where(e=>S(e,"StudentID")==id).ToList();
            ok&=Ids(d.Body,"enrollment-").SetEquals(expected.Select(e=>long.Parse(S(e,"EnrollmentID"))));
            foreach(var e in expected)
            {
                var eid=S(e,"EnrollmentID");var grade=e["Grade"]==null?"No grade":oracle["grade_map"][e["Grade"].ToString()].ToString();
                var row=doc.GetElementById("enrollment-"+eid);var course=oracle["tables"]["Courses"]["rows"].AsArray().Single(c=>S(c,"CourseID")==S(e,"CourseID"));
                ok&=Marker(d.Body,"grade-"+eid)==grade&&row!=null&&row.TextContent.Contains(S(course,"Title"))&&row.QuerySelectorAll("a[href]").Any(a=>a.GetAttribute("href")=="/Course/Details/"+S(e,"CourseID"));
            }
            detailsOk&=ok;notes.Add(id+"="+ok);
        }
        detailsOk&=web.Get("/Student/Details/99999999").Status==404;
        Check(5,detailsOk,"Original student details, FullName, joins, grade enum and null semantics: "+string.Join(",",notes));
        var courses=oracle["tables"]["Courses"]["rows"].AsArray();var courseList=web.Get("/Course");var coursesOk=courseList.Status==200&&Ids(courseList.Body,"course-").SetEquals(courses.Select(c=>long.Parse(S(c,"CourseID"))));
        foreach(var c in courses)
        {
            var d=web.Get("/Course/Details/"+S(c,"CourseID"));var department=oracle["tables"]["Departments"]["rows"].AsArray().Single(x=>S(x,"DepartmentID")==S(c,"DepartmentID"));
            coursesOk&=d.Status==200&&Marker(d.Body,"course-id")==S(c,"CourseID")&&Marker(d.Body,"course-credits")==S(c,"Credits")&&Marker(d.Body,"department-name")==S(department,"Name")&&d.Body.Contains(WebUtility.HtmlEncode(S(c,"Title")));
        }
        coursesOk&=web.Get("/Course/Details/99999999").Status==404;Check(6,coursesOk,"Externally assigned course IDs, title, credits and department relationships.");
        var create=Fields(oracle["workflow"]["create"]["fields"]);var beforeCreateCount=StudentCount(host.DatabasePath);var form=web.Get("/Student/Create");var posted=web.Post("/Student/Create",Form(form.Body,create));
        var newId=CreatedId(host.DatabasePath,create);var created=Student(host.DatabasePath,newId);
        Check(7,form.Status==200&&HasForm(form.Body)&&posted.Status is 302 or 303&&posted.Location=="/Student/Details/"+newId&&newId>0&&!ids.Contains(newId)&&StudentCount(host.DatabasePath)==beforeCreateCount+1&&StudentMatches(created,create)&&RowsMatch(host.DatabasePath,out _),"One new student stored without old-ID collision; ID="+newId);
        var invalidCreateOk=true;var initialSnapshot=Snapshot(host.DatabasePath);
        foreach(var invalid in Invalids(create))
        {
            var g=web.Get("/Student/Create");var r=web.Post("/Student/Create",Form(g.Body,invalid));invalidCreateOk&=r.Status==200&&HasForm(r.Body)&&Snapshot(host.DatabasePath)==initialSnapshot;
        }
        Check(8,invalidCreateOk,"Nine missing/whitespace/51-char/calendar-invalid create cases preserve all tables.");
        if(newId<=0)return;
        var edit=Fields(oracle["workflow"]["edit"]["fields"]);edit["ID"]=newId.ToString();var beforeEditCount=StudentCount(host.DatabasePath);var beforeEditRelated=Snapshot(host.DatabasePath,false);
        var editForm=web.Get("/Student/Edit/"+newId);var saved=web.Post("/Student/Edit/"+newId,Form(editForm.Body,edit));var edited=Student(host.DatabasePath,newId);
        Check(9,editForm.Status==200&&HasForm(editForm.Body)&&saved.Status is 302 or 303&&saved.Location=="/Student/Details/"+newId&&StudentMatches(edited,edit)
            &&StudentCount(host.DatabasePath)==beforeEditCount&&Snapshot(host.DatabasePath,false)==beforeEditRelated&&RowsMatch(host.DatabasePath,out _)&&web.Get("/Student/Edit/99999999").Status==404,"Selected new student edit without altering originals/joins; ID="+newId);
        var invalidEditOk=true;var editedSnapshot=Snapshot(host.DatabasePath);
        foreach(var invalid in Invalids(edit))
        {
            var g=web.Get("/Student/Edit/"+newId);var r=web.Post("/Student/Edit/"+newId,Form(g.Body,invalid));invalidEditOk&=r.Status==200&&HasForm(r.Body)&&Snapshot(host.DatabasePath)==editedSnapshot;
        }
        Check(10,invalidEditOk,"Nine missing/whitespace/51-char/calendar-invalid edit cases preserve all tables.");
        var firstPid=host.AppProcessId;host.Stop();var firstStopped=host.ProcessExited;host.Start();var restarted=host.WaitReady(TimeSpan.FromSeconds(30));
        var restartIdentity=firstStopped&&host.AppProcessId!=firstPid;
        File.WriteAllText(Path.Combine(evidence,"restart.json"),JsonSerializer.Serialize(new{firstPid,firstStopConfirmed=firstStopped,restartedPid=host.AppProcessId,sameDatabasePath=host.DatabasePath},Json));
        Check(11,restarted.Ready&&restartIdentity&&Snapshot(host.DatabasePath)==editedSnapshot&&RowsMatch(host.DatabasePath,out _),"Restart retains the actual complete pre-stop database without duplication; independent invalid-input failures remain E-008/E-010; first stop="+firstStopped+", distinct PID="+restartIdentity);
        host.Stop();
    }

    static string ReadVerified(string root,JsonNode reference)
    {
        var relative=S(reference,"path");if(string.IsNullOrWhiteSpace(relative)||Path.IsPathRooted(relative)||relative.Replace('\\','/').Split('/').Contains(".."))throw new InvalidDataException("Invalid browser evidence path.");
        var path=Path.GetFullPath(Path.Combine(root,relative));if(!path.StartsWith(Path.GetFullPath(root)+Path.DirectorySeparatorChar,StringComparison.Ordinal)||HashFile(path)!=S(reference,"sha256"))throw new InvalidDataException("Browser evidence hash mismatch.");return File.ReadAllText(path);
    }
    static void Compose()
    {
        var baseline=O("--browser-school-baseline");var previous=JsonNode.Parse(File.ReadAllText(Path.Combine(baseline,"evaluation.json")));
        if(S(previous,"artifactSha256")!=artifactHash||S(previous,"specSha256")!=specHash||S(previous,"evaluationVersion")!=Version)throw new InvalidDataException("Baseline identity mismatch.");
        var baselineChecks=new HashSet<string>();
        foreach(var line in File.ReadLines(Path.Combine(baseline,"results.jsonl")))
        {
            var r=JsonNode.Parse(line);var checkId=S(r,"checkId");if(!results.ContainsKey(checkId)||!baselineChecks.Add(checkId))throw new InvalidDataException("Unknown/duplicate baseline check.");
            var requirement=ledger["requirements"].AsArray().Single(q=>q["checks"].AsArray().Any(c=>S(c,"id")==checkId));
            if(S(r,"requirementId")!=S(requirement,"id")||S(previous["requirements"].AsArray().Single(q=>S(q,"id")==S(requirement,"id")),"judgement")!=S(r,"judgement"))throw new InvalidDataException("Baseline output/check disagreement.");
            results[checkId]=(S(r,"judgement"),S(r,"observation"));
        }
        if(baselineChecks.Count!=12)throw new InvalidDataException("Missing baseline checks.");
        var receiptPath=O("--browser-school-evidence");var receipt=JsonNode.Parse(File.ReadAllText(receiptPath));
        if(receipt["schemaVersion"].GetValue<int>()!=1||S(receipt,"actor")!="agent"||S(receipt,"artifactSha256")!=artifactHash||S(receipt,"specSha256")!=specHash||S(receipt,"runInstanceId")!=O("--review-run-instance-id"))throw new InvalidDataException("School browser identity mismatch.");
        if(receipt["faults"].AsArray().Count>0)throw new IOException("Browser observer fault: "+receipt["faults"]);
        if(S(receipt,"action")!="create-edit-save")return;
        var root=Path.GetDirectoryName(receiptPath);var after=JsonNode.Parse(ReadVerified(root,receipt["after"]));
        var before=JsonNode.Parse(ReadVerified(root,receipt["before"]));var created=JsonNode.Parse(ReadVerified(root,receipt["created"]));var edit=JsonNode.Parse(ReadVerified(root,receipt["edit"]));
        ReadVerified(root,receipt["beforeScreenshot"]);ReadVerified(root,receipt["afterScreenshot"]);
        var database=JsonNode.Parse(ReadVerified(root,receipt["database"]));var id=S(receipt,"studentId");
        var captures=new[]{before,created,edit,after};var origins=captures.Select(c=>new Uri(S(c["page"],"url")).GetLeftPart(UriPartial.Authority)).Distinct().Count();
        if(string.IsNullOrWhiteSpace(S(before,"tabId"))||captures.Any(c=>S(c,"tabId")!=S(before,"tabId"))||origins!=1
            ||new Uri(S(before["page"],"url")).AbsolutePath!="/Student/Create"||new Uri(S(created["page"],"url")).AbsolutePath!="/Student/Details/"+id
            ||new Uri(S(edit["page"],"url")).AbsolutePath!="/Student/Edit/"+id
            ||!captures.Select(c=>DateTimeOffset.Parse(S(c,"at"))).SequenceEqual(captures.Select(c=>DateTimeOffset.Parse(S(c,"at"))).Order()))throw new InvalidDataException("Browser context/action chronology mismatch.");
        var expected=Fields(oracle["workflow"]["edit"]["fields"]);var page=after["page"];
        var pass=new Uri(S(page,"url")).AbsolutePath=="/Student/Details/"+id&&S(page,"studentId")==id&&S(page,"firstName")==expected["FirstMidName"]&&S(page,"lastName")==expected["LastName"]&&S(page,"enrollmentDate")==expected["EnrollmentDate"]
            &&S(page,"fullName")==expected["LastName"]+", "+expected["FirstMidName"]&&StudentMatches(database["student"].AsObject(),expected)
            &&S(database["student"],"ID")==id&&database["original_rows_preserved"].GetValue<bool>();
        Check(12,pass,"Actual ordinary Create/Edit/Save: UI and independently read SQLite row match; student ID="+id);
    }

    static int Emit(IEnumerable<string> faults)
    {
        var faultList=faults.ToList();var outcomes=new List<object>();var critical=new List<string>();var passed=0;var failed=0;var blocked=0;
        foreach(var r in ledger["requirements"].AsArray())
        {
            var own=r["checks"].AsArray().Select(c=>results[S(c,"id")]).ToList();var judgement=own.Any(c=>c.judgement=="fail")?"fail":own.Any(c=>c.judgement!="pass")?"blocked":"pass";
            if(judgement=="pass")passed++;else if(judgement=="fail"){failed++;if(S(r,"severity")=="critical")critical.Add(S(r,"id"));}else blocked++;
            outcomes.Add(new{id=S(r,"id"),category=S(r,"category"),title=S(r,"title"),severity=S(r,"severity"),basis=S(r,"basis"),expectation=S(r,"expectation"),judgement});
        }
        var complete=options.ContainsKey("--browser-school-evidence")&&results["E-012"].judgement!="blocked"&&blocked==0&&faultList.Count==0;
        var output=new JsonObject
        {
            ["evaluationId"]=S(ledger,"taskId")+"-"+artifactHash[..12]+"-"+Version+"-"+int.Parse(O("--sequence")).ToString("000"),["taskId"]=S(ledger,"taskId"),["taskTitle"]=S(ledger,"taskTitle"),
            ["evaluationVersion"]=Version,["specVersion"]=S(ledger,"specVersion"),["specSha256"]=specHash,["artifactPath"]=O("--artifact"),["artifactSha256"]=artifactHash,
            ["sourceRepository"]=S(ledger,"sourceRepository"),["sourceCommit"]=S(ledger,"sourceCommit"),["researchStatus"]=complete?"complete":"incomplete",
            ["browserReviewCoverage"]=complete?"agent_observed_StudentCreateEdit":"not_run_or_partial",["browserReviewEvidenceSha256"]=options.ContainsKey("--browser-school-evidence")?HashFile(O("--browser-school-evidence")):null,
            ["reviewRunInstanceId"]=options.GetValueOrDefault("--review-run-instance-id"),["baselineEvaluationSha256"]=options.ContainsKey("--browser-school-baseline")?HashFile(Path.Combine(O("--browser-school-baseline"),"evaluation.json")):null,
            ["baselineResultsSha256"]=options.ContainsKey("--browser-school-baseline")?HashFile(Path.Combine(O("--browser-school-baseline"),"results.jsonl")):null,
            ["verdict"]=critical.Count>0?"fail_critical":failed>0?"fail":faultList.Count>0?"error":blocked>0?"blocked":"pass",
            ["quality"]=complete&&blocked==0?Math.Round(passed*100.0/12,2):null,["requirementCount"]=12,["passedCount"]=passed,["failedCount"]=failed,["blockedCount"]=blocked,["errorCount"]=faultList.Count,
            ["criticalFailed"]=JsonSerializer.SerializeToNode(critical),["evaluatorFaults"]=JsonSerializer.SerializeToNode(faultList),["requirements"]=JsonSerializer.SerializeToNode(outcomes),["humanReview"]="not_run"
        };
        File.WriteAllText(Path.Combine(O("--out"),"evaluation.json"),output.ToJsonString(Json));
        File.WriteAllText(Path.Combine(O("--out"),"results.jsonl"),string.Concat(ledger["requirements"].AsArray().SelectMany(r=>r["checks"].AsArray().Select(c=>JsonSerializer.Serialize(new{requirementId=S(r,"id"),checkId=S(c,"id"),judgement=results[S(c,"id")].judgement,observation=results[S(c,"id")].detail})+"\n"))));
        File.WriteAllText(Path.Combine(O("--out"),"evaluator-manifest.json"),JsonSerializer.Serialize(new{evaluationVersion=Version,evaluatorVersion=Version,evaluatorSha256=HashFile(typeof(Program).Assembly.Location),artifactSha256=artifactHash,specSha256=specHash,implementedCheckIds=results.Keys,humanReview="not_run"},Json));
        return faultList.Count>0?2:0;
    }
}
