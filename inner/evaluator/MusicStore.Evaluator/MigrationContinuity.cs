using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;

namespace MusicStore.Evaluator;

public sealed class MigrationContract
{
    public string InitialDatabase { get; set; }
    public string Oracle { get; set; }
}

/// <summary>Private independent expectations never enter the model's public request.</summary>
public sealed class MigrationContinuity
{
    private string initialDatabase;
    private JsonDocument oracle;
    private string evaluationVersion;
    private readonly List<string> failures = new();
    private readonly List<string> observations = new();
    public List<string> UnknownObservations { get; } = new();
    public List<string> ObservationFaults { get; } = new();
    public string Judgement { get; private set; } = MusicStore.Evaluator.Judgement.Blocked;
    public bool HasConfirmedFailure => failures.Count > 0;
    public string Detail => string.Join("\n", observations.Concat(failures).Concat(UnknownObservations).Concat(ObservationFaults));

    public static MigrationContinuity Load(MigrationContract contract, string assetDirectory, string evaluationVersion = "1.5.0")
    {
        string Asset(string relative)
        {
            var root = Path.GetFullPath(assetDirectory);
            var path = Path.GetFullPath(Path.Combine(root, relative));
            if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                || !File.Exists(path)) throw new InvalidDataException("Missing or escaping migration asset: " + relative);
            return path;
        }
        var value = new MigrationContinuity
        {
            evaluationVersion = evaluationVersion,
            initialDatabase = Asset(contract.InitialDatabase),
            oracle = JsonDocument.Parse(File.ReadAllText(Asset(contract.Oracle))),
        };
        var root = value.oracle.RootElement;
        if (root.GetProperty("schema_version").GetInt32() != 1
            || root.GetProperty("tables").EnumerateObject().Count() == 0
            || root.GetProperty("authority").GetArrayLength() == 0)
            throw new InvalidDataException("Independent migration oracle schema/authority missing.");
        // Prove the initial database agrees with the oracle before it is given to a product.
        value.Preserved(value.initialDatabase, "initial_asset");
        if (value.failures.Count > 0 || value.ObservationFaults.Count > 0 || value.UnknownObservations.Count > 0) throw new InvalidDataException(value.Detail);
        value.observations.Clear();
        return value;
    }

    public void Seed(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.Copy(initialDatabase, path, overwrite: false);
    }

    public void Preserved(string path, string phase)
    {
        try
        {
            using var db = Open(path);
            foreach (var table in oracle.RootElement.GetProperty("tables").EnumerateObject())
            {
                var key = table.Value.GetProperty("key").GetString();
                var rows = table.Value.GetProperty("rows");
                var observed = 0;
                foreach (var row in rows.EnumerateArray())
                {
                    using var command = db.CreateCommand();
                    command.CommandText = $"SELECT * FROM {Identifier(table.Name)} WHERE {Identifier(key)}=$key";
                    command.Parameters.AddWithValue("$key", Value(row.GetProperty(key)));
                    using var reader = command.ExecuteReader();
                    if (!reader.Read()) { failures.Add($"{phase}: missing {table.Name}.{key}={row.GetProperty(key)}"); continue; }
                    foreach (var column in row.EnumerateObject())
                    {
                        var actual = reader[column.Name];
                        if (!Same(column.Value, actual))
                            failures.Add($"{phase}: {table.Name}[{row.GetProperty(key)}].{column.Name}: expected {column.Value}; observed {actual}");
                    }
                    if (reader.Read()) failures.Add($"{phase}: duplicate {table.Name} key {row.GetProperty(key)}");
                    observed++;
                }
                observations.Add($"{phase}: {table.Name} preserved row observations {observed}/{rows.GetArrayLength()}");
            }
        }
        catch (SqliteException ex) { SqlFault(ex,phase); }
        catch (IndexOutOfRangeException ex) { failures.Add(phase + ": stored migration column missing: " + ex.Message); }
        catch (Exception ex) when (evaluationVersion == "1.6.0") { ObservationFaults.Add(phase+": "+ex.GetType().Name+": "+ex.Message); UnknownObservations.Add(phase+": stored rows not fully observed."); }
    }

    public void Observe(RunState state)
    {
        try
        {
            Preserved(state.Host.DatabasePath, "after_restart");
            using var db = Open(state.Host.DatabasePath);
            var workflow = oracle.RootElement.GetProperty("workflow");
            if(evaluationVersion=="1.6.0")
            {
                List<Html.CartLine> Input(WebResponse response)=>response?.Status==200 && Html.ObserveCart16(response.Body).Violations.Count==0?Html.CartLines(response.Body,"1.6.0"):new();
                ObserveStoredOrder(state.Host.DatabasePath,state.Order?.OrderId,Input(state.Order?.CartBeforeCheckout),"checkout");
                ObserveStoredOrder(state.Host.DatabasePath,state.Order?.SecondOrderId,Input(state.Order?.CartBeforeSecondCheckout),"second");
                ObserveStoredOrder(state.Host.DatabasePath,state.Restart?.OrderIdAfter,Input(state.Restart?.CartBeforeCheckout),"restart");
            }
            else
            {
                Order(db, state.Order?.OrderId, workflow.GetProperty("checkout"), "checkout");
                Order(db, state.Order?.SecondOrderId, workflow.GetProperty("second"), "second");
                Order(db, state.Restart?.OrderIdAfter, workflow.GetProperty("restart"), "restart");
            }
            db.Close();
            var existing = state.Host.DatabasePath;
            state.Host.Stop();
            state.Host.UseDatabase(Path.Combine(state.Host.WorkDir, "fresh-store.sqlite"));
            state.Host.Start();
            var (ready, detail) = state.Host.WaitReady(TimeSpan.FromSeconds(60));
            if (!ready) failures.Add("fresh_import: application did not start: " + detail);
            else Preserved(state.Host.DatabasePath, "fresh_import");
            state.Host.Stop();
            state.Host.UseDatabase(existing);
            SetJudgement();
        }
        catch (SqliteException ex)
        {
            SqlFault(ex,"Stored order contract");
            SetJudgement();
        }
        catch (Exception ex)
        {
            observations.Add("Evaluator observation fault: " + ex.Message);
            if(evaluationVersion=="1.6.0") { ObservationFaults.Add(ex.GetType().Name+": "+ex.Message); UnknownObservations.Add("Migration observation did not finish."); }
            Judgement = MusicStore.Evaluator.Judgement.Error;
        }
    }

    private void SetJudgement() => Judgement=failures.Count>0?MusicStore.Evaluator.Judgement.Fail
        :ObservationFaults.Count>0?MusicStore.Evaluator.Judgement.Error:UnknownObservations.Count>0?MusicStore.Evaluator.Judgement.Blocked:MusicStore.Evaluator.Judgement.Pass;

    private void SqlFault(SqliteException ex,string phase)
    {
        if(evaluationVersion!="1.6.0" || ex.SqliteErrorCode is 1 or 26)
            failures.Add(phase+": stored contract unavailable: "+ex.Message);
        else { ObservationFaults.Add(phase+": SQLite observation fault "+ex.SqliteErrorCode+": "+ex.Message); UnknownObservations.Add(phase+": database predicate not observed."); }
    }

    /// <summary>Read-only exact frozen workflow comparison only after its input quantities existed.</summary>
    public void ObserveStoredOrder(string path,int? id,IReadOnlyList<Html.CartLine> cart,string phase)
    {
        var expected=oracle.RootElement.GetProperty("workflow").GetProperty(phase);
        var wanted=expected.GetProperty("album_quantities").EnumerateObject().Select(x=>(Album:int.Parse(x.Name,CultureInfo.InvariantCulture),Quantity:x.Value.GetInt32())).ToArray();
        if(!Attribution16.CartMatches(cart,wanted) || id is null or <=0)
        { UnknownObservations.Add(phase+": frozen workflow input cart or positive output order ID was not established; no storage mismatch inferred.");SetJudgement();return; }
        try { using var db=Open(path);Order(db,id,expected,phase); }
        catch(SqliteException ex) { SqlFault(ex,phase); }
        catch(Exception ex) { ObservationFaults.Add(phase+": "+ex.GetType().Name+": "+ex.Message);UnknownObservations.Add(phase+": stored order not fully observed."); }
        SetJudgement();
    }

    private void Order(SqliteConnection db, int? id, JsonElement expected, string phase)
    {
        if (!id.HasValue) { failures.Add(phase + ": workflow did not produce an observable order ID."); return; }
        using var total = db.CreateCommand();
        total.CommandText = "SELECT Total FROM Orders WHERE OrderId=$id";
        total.Parameters.AddWithValue("$id", id.Value);
        var amount = total.ExecuteScalar();
        if (!Same(expected.GetProperty("total"), amount)) failures.Add($"{phase}: expected total {expected.GetProperty("total")}; observed {amount ?? "missing"}");
        using var lines = db.CreateCommand();
        lines.CommandText = "SELECT AlbumId,Quantity,UnitPrice FROM OrderDetails WHERE OrderId=$id ORDER BY AlbumId";
        lines.Parameters.AddWithValue("$id", id.Value);
        using var reader = lines.ExecuteReader();
        var seen = new HashSet<string>();
        var quantities = expected.GetProperty("album_quantities");
        var prices = expected.GetProperty("unit_prices");
        while (reader.Read())
        {
            var album = reader.GetInt32(0).ToString(CultureInfo.InvariantCulture);
            if (!seen.Add(album) || !quantities.TryGetProperty(album, out var quantity))
            { failures.Add(phase + ": unexpected or duplicated line for album " + album); continue; }
            if (!Same(quantity, reader[1]) || !Same(prices.GetProperty(album), reader[2]))
                failures.Add($"{phase}: album {album} expected quantity {quantity}, unit {prices.GetProperty(album)}; observed {reader[1]}, {reader[2]}");
        }
        foreach (var line in quantities.EnumerateObject())
            if (!seen.Contains(line.Name)) failures.Add(phase + ": missing stored line for album " + line.Name);
        observations.Add($"{phase}: stored order {id}, {seen.Count} detail rows, total {amount}");
    }

    private SqliteConnection Open(string path)
    {
        var db = new SqliteConnection(new SqliteConnectionStringBuilder
        { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false, DefaultTimeout=evaluationVersion=="1.6.0"?1:30 }.ToString());
        db.Open(); return db;
    }
    private static string Identifier(string name) => Regex.IsMatch(name, @"\A[A-Za-z][A-Za-z0-9_]*\z")
        ? "\"" + name + "\"" : throw new InvalidDataException("Invalid oracle identifier");
    private static object Value(JsonElement item) => item.ValueKind == JsonValueKind.Null ? DBNull.Value
        : item.ValueKind == JsonValueKind.Number ? item.GetDecimal() : item.GetString();
    private static bool Same(JsonElement expected, object actual)
    {
        if (expected.ValueKind == JsonValueKind.Null) return actual is null or DBNull;
        if (actual is null or DBNull) return false;
        var text = Convert.ToString(actual, CultureInfo.InvariantCulture);
        var wanted = expected.ValueKind == JsonValueKind.String ? expected.GetString() : expected.GetRawText();
        if (decimal.TryParse(wanted, NumberStyles.Number, CultureInfo.InvariantCulture, out var a)
            && decimal.TryParse(text, NumberStyles.Number, CultureInfo.InvariantCulture, out var b)) return a == b;
        return wanted == text;
    }
}
