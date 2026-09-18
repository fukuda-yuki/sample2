using System.Globalization;
using Microsoft.Data.Sqlite;

namespace MusicStore.Evaluator;

/// <summary>
/// 保存契約（SQLite の Orders 表、主キー列 OrderId）に沿って、注文行の存在を
/// 読み取り専用で観測する。成果物の内部スキーマは推測しない。
///
/// 観測できない理由を 3 つに分ける。表や列が無い場合は保存契約違反（成果物の欠陥）、
/// 表と列はあるが行が無い場合は保持の失敗、評価側の事情で読めない場合は判定不能
/// （評価側の障害）である。後者を成果物の欠陥と混同しない（docs/quality-spec.md §4.6）。
/// </summary>
public static class OrderStore
{
    public sealed class Snapshot
    {
        public ProbeStatus Status { get; set; }
        public string Detail { get; set; } = string.Empty;
        public List<long> Ids { get; } = new();
        public bool SameAs(Snapshot other) => Status == ProbeStatus.Found
            && other?.Status == ProbeStatus.Found && Ids.SequenceEqual(other.Ids);
    }

    public static Snapshot ReadIds(string databasePath)
    {
        var result = new Snapshot();
        if (string.IsNullOrEmpty(databasePath) || !File.Exists(databasePath))
        {
            result.Status = ProbeStatus.ContractViolation;
            result.Detail = "Orders snapshot: database missing";
            return result;
        }
        try
        {
            using var connection = new SqliteConnection(new SqliteConnectionStringBuilder
            {
                DataSource = databasePath, Mode = SqliteOpenMode.ReadOnly, Pooling = false,
                DefaultTimeout = 10,
            }.ToString());
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText = "SELECT OrderId FROM Orders ORDER BY OrderId";
            using var reader = command.ExecuteReader();
            while (reader.Read()) result.Ids.Add(reader.GetInt64(0));
            result.Status = ProbeStatus.Found;
            result.Detail = "Orders.OrderId: [" + string.Join(",", result.Ids) + "]";
        }
        catch (SqliteException ex) when (IsContractViolation(ex))
        {
            result.Status = ProbeStatus.ContractViolation;
            result.Detail = "Orders snapshot contract violation: " + ex.Message;
        }
        catch (Exception ex)
        {
            result.Status = ProbeStatus.Unreadable;
            result.Detail = "Orders snapshot unreadable: " + ex.GetType().Name + ": " + ex.Message;
        }
        return result;
    }

    public const string TableName = "Orders";

    public const string OrderIdColumn = "OrderId";

    public enum ProbeStatus
    {
        /// <summary>その注文行が存在する。</summary>
        Found,

        /// <summary>表と列はあるが、その注文行が無い。</summary>
        Missing,

        /// <summary>保存契約（表・列・SQLite ファイル）を満たしていない。</summary>
        ContractViolation,

        /// <summary>評価側の事情で読めない。成果物の欠陥と混同しない。</summary>
        Unreadable,
    }

    public sealed class Probe
    {
        public ProbeStatus Status { get; set; }

        public string Detail { get; set; } = string.Empty;

        public bool Found => Status == ProbeStatus.Found;
    }

    /// <summary>
    /// 指定した注文番号の行が Orders 表にあるかを、読み取り専用で数える。
    /// 書き込みもスキーマ変更も行わない。
    /// </summary>
    public static Probe OrderRowExists(string databasePath, int orderId)
    {
        if (string.IsNullOrEmpty(databasePath) || !File.Exists(databasePath))
        {
            return new Probe
            {
                Status = ProbeStatus.ContractViolation,
                Detail = "保存契約の SQLite ファイルがありません: " + (databasePath ?? "(未設定)"),
            };
        }

        try
        {
            var builder = new SqliteConnectionStringBuilder
            {
                DataSource = databasePath,
                Mode = SqliteOpenMode.ReadOnly,
                            // 接続プールを使うと Close の後もファイルハンドルが残り、DB ファイルを
                            // 作り直す成果物（EnsureDeleted など）を評価器が妨害してしまう。
                            // 観測が成果物の挙動を変えないよう、プールを無効にする。
                            Pooling = false,
                        };

            using var connection = new SqliteConnection(builder.ToString());
            connection.Open();
            using (var pragma = connection.CreateCommand())
            {
                // アプリが書き込み中でも、待ってから読む。読めないことを
                // 成果物の欠陥にしないための待ち時間である。
                pragma.CommandText = "PRAGMA busy_timeout = 10000;";
                pragma.ExecuteNonQuery();
            }

            using var command = connection.CreateCommand();
            command.CommandText = "SELECT COUNT(*) FROM " + TableName + " WHERE " + OrderIdColumn + " = $id";
            command.Parameters.AddWithValue("$id", orderId);
            var count = Convert.ToInt64(command.ExecuteScalar(), CultureInfo.InvariantCulture);
            return count > 0
                ? new Probe
                {
                    Status = ProbeStatus.Found,
                    Detail = TableName + "." + OrderIdColumn + " = " + orderId.ToString(CultureInfo.InvariantCulture) + " の行が " + count.ToString(CultureInfo.InvariantCulture) + " 件あります。",
                }
                : new Probe
                {
                    Status = ProbeStatus.Missing,
                    Detail = TableName + "." + OrderIdColumn + " = " + orderId.ToString(CultureInfo.InvariantCulture) + " の行がありません。",
                };
        }
        catch (SqliteException ex) when (IsContractViolation(ex))
        {
            return new Probe
            {
                Status = ProbeStatus.ContractViolation,
                Detail = "保存契約（" + TableName + " 表の " + OrderIdColumn + " 列）を読めません: " + ex.Message,
            };
        }
        catch (Exception ex)
        {
            return new Probe
            {
                Status = ProbeStatus.Unreadable,
                Detail = ex.GetType().Name + ": " + ex.Message,
            };
        }
    }

    /// <summary>
    /// SQLITE_ERROR（表や列が無い、SQL が通らない）と SQLITE_NOTADB（SQLite の
    /// ファイルではない）は、成果物が保存契約を満たしていないことを表す。
    /// SQLITE_BUSY や SQLITE_LOCKED は評価側の読み取りの事情なので含めない。
    /// </summary>
    private static bool IsContractViolation(SqliteException ex) =>
        ex.SqliteErrorCode == 1 || ex.SqliteErrorCode == 26;
}
