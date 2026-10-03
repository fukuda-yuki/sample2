using System.Globalization;

var builder = WebApplication.CreateBuilder(args);
var connection = builder.Configuration.GetConnectionString("SchoolContext") ?? "Data Source=school.sqlite";
var store = new Store(connection, AppContext.BaseDirectory);
var app = builder.Build();
IResult Html(string text) => Results.Content(text, "text/html; charset=utf-8");
Dictionary<string, object?>? Student(long id) => store.Query("SELECT * FROM Students WHERE ID=$id", ("$id", id)).SingleOrDefault();
app.MapGet("/", () => Html(Pages.Page("Contoso University", "<p>Student, course and enrollment migration reference</p>")));
app.MapGet("/Student", (HttpRequest request) =>
{
    var search = request.Query["SearchString"].ToString();
    var rows = store.Query("SELECT * FROM Students ORDER BY ID");
    if (search.Length > 0) rows = rows.Where(row => (Convert.ToString(row["LastName"]) ?? "").Contains(search, StringComparison.OrdinalIgnoreCase) || (Convert.ToString(row["FirstMidName"]) ?? "").Contains(search, StringComparison.OrdinalIgnoreCase)).ToList();
    return Html(Pages.Students(rows, search));
});
app.MapGet("/Student/Details/{id:long}", (long id) =>
{
    var student = Student(id);
    return student is null ? Results.NotFound() : Html(Pages.Student(student, store.Query("SELECT e.*,c.Title FROM Enrollments e JOIN Courses c ON e.CourseID=c.CourseID WHERE e.StudentID=$id ORDER BY e.EnrollmentID", ("$id", id))));
});
app.MapGet("/Student/Create", () => Html(Pages.Form(null, "", "", "")));
app.MapGet("/Student/Edit/{id:long}", (long id) =>
{
    var row = Student(id);
    return row is null ? Results.NotFound() : Html(Pages.Form(id, Convert.ToString(row["LastName"])!, Convert.ToString(row["FirstMidName"])!, Convert.ToString(row["EnrollmentDate"])!));
});
async Task<IResult> Save(HttpRequest request, long? id)
{
    if (id.HasValue && Student(id.Value) is null) return Results.NotFound();
    var fields = await request.ReadFormAsync();
    string last = fields["LastName"].ToString(), first = fields["FirstMidName"].ToString(), date = fields["EnrollmentDate"].ToString();
    if (string.IsNullOrWhiteSpace(last) || string.IsNullOrWhiteSpace(first) || last.Length > 50 || first.Length > 50 || !DateOnly.TryParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed))
        return Html(Pages.Form(id, last, first, date, "Names (1–50 characters) and a valid enrollment date are required."));
    var saved = store.Save(id, last, first, parsed.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
    return Results.Redirect("/Student/Details/" + saved);
}
app.MapPost("/Student/Create", (HttpRequest request) => Save(request, null));
app.MapPost("/Student/Edit/{id:long}", (HttpRequest request, long id) => Save(request, id));
app.MapGet("/Course", () => Html(Pages.Courses(store.Query("SELECT * FROM Courses ORDER BY CourseID"))));
app.MapGet("/Course/Details/{id:long}", (long id) =>
{
    var row = store.Query("SELECT c.*,d.Name FROM Courses c JOIN Departments d ON c.DepartmentID=d.DepartmentID WHERE c.CourseID=$id", ("$id", id)).SingleOrDefault();
    return row is null ? Results.NotFound() : Html(Pages.Course(row));
});
app.Run();
