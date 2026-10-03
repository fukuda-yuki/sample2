using System.Net;

public static class Pages
{
    public static string E(object? value) => WebUtility.HtmlEncode(Convert.ToString(value) ?? "");
    public static string Page(string title, string body) => "<!doctype html><html><head><meta charset='utf-8'><title>" + E(title) + "</title></head><body><nav><a href='/'>Home</a> <a href='/Student'>Students</a> <a href='/Course'>Courses</a></nav><h1>" + E(title) + "</h1>" + body + "</body></html>";
    public static string Students(IEnumerable<Dictionary<string, object?>> rows, string search)
    {
        var body = "<a href='/Student/Create'>Create student</a><form method='get'><input name='SearchString' value='" + E(search) + "'><button>Search</button></form><table>";
        foreach (var row in rows)
        {
            var id = E(row["ID"]);
            body += "<tr id='student-" + id + "'><td>" + E(row["LastName"]) + ", " + E(row["FirstMidName"]) + "</td><td><a href='/Student/Details/" + id + "'>Details</a> <a href='/Student/Edit/" + id + "'>Edit</a></td></tr>";
        }
        return Page("Students", body + "</table>");
    }
    public static string Student(Dictionary<string, object?> student, IEnumerable<Dictionary<string, object?>> enrollments)
    {
        var body = "<div id='student-id'>" + E(student["ID"]) + "</div><div id='student-first-name'>" + E(student["FirstMidName"]) + "</div><div id='student-last-name'>" + E(student["LastName"]) + "</div><div id='student-enrollment-date'>" + E(student["EnrollmentDate"]) + "</div><div id='student-full-name'>" + E(student["LastName"]) + ", " + E(student["FirstMidName"]) + "</div><a href='/Student/Edit/" + E(student["ID"]) + "'>Edit</a><table>";
        foreach (var row in enrollments)
        {
            var id = E(row["EnrollmentID"]);
            int? grade = row["Grade"] is null ? null : Convert.ToInt32(row["Grade"]);
            body += "<tr id='enrollment-" + id + "'><td><a href='/Course/Details/" + E(row["CourseID"]) + "'>" + E(row["Title"]) + "</a></td><td id='grade-" + id + "'>" + E(GradePolicy.Display(grade)) + "</td></tr>";
        }
        return Page("Student details", body + "</table>");
    }
    public static string Form(long? id, string last, string first, string date, string error = "")
    {
        var action = id.HasValue ? "/Student/Edit/" + id : "/Student/Create";
        return Page(id.HasValue ? "Edit student" : "Create student", "<div role='alert'>" + E(error) + "</div><form action='" + action + "' method='post'><label>Last name<input name='LastName' value='" + E(last) + "'></label><label>First name<input name='FirstMidName' value='" + E(first) + "'></label><label>Enrollment date<input name='EnrollmentDate' type='date' value='" + E(date) + "'></label><button type='submit'>" + (id.HasValue ? "Save" : "Create") + "</button></form>");
    }
    public static string Courses(IEnumerable<Dictionary<string, object?>> rows) => Page("Courses", "<table>" + string.Join("", rows.Select(row => "<tr id='course-" + E(row["CourseID"]) + "'><td><a href='/Course/Details/" + E(row["CourseID"]) + "'>" + E(row["Title"]) + "</a></td></tr>")) + "</table>");
    public static string Course(Dictionary<string, object?> row) => Page(E(row["Title"]), "<div id='course-id'>" + E(row["CourseID"]) + "</div><div id='course-title'>" + E(row["Title"]) + "</div><div id='course-credits'>" + E(row["Credits"]) + "</div><div id='department-name'>" + E(row["Name"]) + "</div>");
}
