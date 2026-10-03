using Microsoft.Data.Sqlite;

public sealed class Store
{
    readonly string connectionString;
    public Store(string connectionString, string applicationRoot)
    {
        this.connectionString = connectionString;
        var path = new SqliteConnectionStringBuilder(connectionString).DataSource;
        if (File.Exists(path)) return;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        var source = Path.Combine(applicationRoot, "Data", "legacy-school.sqlite");
        if (!File.Exists(source)) source = "/inputs/existing-business/legacy-school.sqlite";
        if (!File.Exists(source)) throw new FileNotFoundException("Original legacy business snapshot required", source);
        using var db = Open();
        using var attach = db.CreateCommand();
        attach.CommandText = "ATTACH DATABASE $source AS old";
        attach.Parameters.AddWithValue("$source", source);
        attach.ExecuteNonQuery();
        using var transaction = db.BeginTransaction();
        using var command = db.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            CREATE TABLE Students(ID INTEGER PRIMARY KEY AUTOINCREMENT,LastName TEXT NOT NULL,FirstMidName TEXT NOT NULL,EnrollmentDate TEXT NOT NULL);
            CREATE TABLE Departments(DepartmentID INTEGER PRIMARY KEY,Name TEXT NOT NULL,Budget TEXT NOT NULL,StartDate TEXT NOT NULL);
            CREATE TABLE Courses(CourseID INTEGER PRIMARY KEY,Title TEXT NOT NULL,Credits INTEGER NOT NULL,DepartmentID INTEGER NOT NULL REFERENCES Departments(DepartmentID));
            CREATE TABLE Enrollments(EnrollmentID INTEGER PRIMARY KEY,CourseID INTEGER NOT NULL REFERENCES Courses(CourseID),StudentID INTEGER NOT NULL REFERENCES Students(ID),Grade INTEGER);
            INSERT INTO Students(ID,LastName,FirstMidName,EnrollmentDate) SELECT ID,LastName,FirstName,EnrollmentDate FROM old.Person WHERE Discriminator='Student';
            INSERT INTO Departments SELECT DepartmentID,Name,Budget,StartDate FROM old.Department;
            INSERT INTO Courses SELECT CourseID,Title,Credits,DepartmentID FROM old.Course;
            INSERT INTO Enrollments SELECT EnrollmentID,CourseID,StudentID,Grade FROM old.Enrollment;
            """;
        command.ExecuteNonQuery();
        transaction.Commit();
    }
    SqliteConnection Open()
    {
        var connection = new SqliteConnection(connectionString);
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "PRAGMA foreign_keys=ON";
        command.ExecuteNonQuery();
        return connection;
    }
    public List<Dictionary<string, object?>> Query(string sql, params (string, object)[] args)
    {
        using var db = Open();
        using var command = db.CreateCommand();
        command.CommandText = sql;
        foreach (var (key, value) in args) command.Parameters.AddWithValue(key, value);
        using var reader = command.ExecuteReader();
        var result = new List<Dictionary<string, object?>>();
        while (reader.Read())
        {
            var row = new Dictionary<string, object?>();
            for (int index = 0; index < reader.FieldCount; index++) row[reader.GetName(index)] = reader.IsDBNull(index) ? null : reader.GetValue(index);
            result.Add(row);
        }
        return result;
    }
    public long Save(long? id, string last, string first, string date)
    {
        using var db = Open();
        using var command = db.CreateCommand();
        command.CommandText = id.HasValue
            ? "UPDATE Students SET LastName=$last,FirstMidName=$first,EnrollmentDate=$date WHERE ID=$id; SELECT $id;"
            : "INSERT INTO Students(LastName,FirstMidName,EnrollmentDate) VALUES($last,$first,$date); SELECT last_insert_rowid();";
        command.Parameters.AddWithValue("$last", last);
        command.Parameters.AddWithValue("$first", first);
        command.Parameters.AddWithValue("$date", date);
        if (id.HasValue) command.Parameters.AddWithValue("$id", id.Value);
        return Convert.ToInt64(command.ExecuteScalar());
    }
}
