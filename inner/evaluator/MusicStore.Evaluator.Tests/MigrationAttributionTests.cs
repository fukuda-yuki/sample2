using System.Text.Json;
using Microsoft.Data.Sqlite;
using MusicStore.Evaluator;

static class MigrationAttributionTests
{
    public static void Run(Action<string,bool> check)
    {
        var root=Path.Combine(Path.GetTempPath(),"music16-migration-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
        try
        {
            var initial=Path.Combine(root,"initial.sqlite");
            using(var db=new SqliteConnection("Data Source="+initial+";Pooling=False"))
            {db.Open();using var command=db.CreateCommand();command.CommandText="CREATE TABLE Orders(OrderId INTEGER PRIMARY KEY,Total TEXT);CREATE TABLE OrderDetails(OrderDetailId INTEGER PRIMARY KEY,OrderId INTEGER,AlbumId INTEGER,Quantity INTEGER,UnitPrice TEXT);INSERT INTO Orders VALUES(7,'10.00');INSERT INTO Orders VALUES(42,'21.75');INSERT INTO OrderDetails VALUES(1,42,1,2,'7.25');INSERT INTO OrderDetails VALUES(2,42,2,1,'7.25');";command.ExecuteNonQuery();}
            var oracle=new {schema_version=1,authority=new[]{"synthetic finite oracle"},tables=new {Orders=new {key="OrderId",rows=new[]{new {OrderId=7,Total="10.00"}}}},workflow=new {
                checkout=new {total="21.75",album_quantities=new Dictionary<string,int>{{"1",2},{"2",1}},unit_prices=new Dictionary<string,string>{{"1","7.25"},{"2","7.25"}}},
                second=new {total="7.25",album_quantities=new Dictionary<string,int>{{"2",1}},unit_prices=new Dictionary<string,string>{{"2","7.25"}}},
                restart=new {total="5.00",album_quantities=new Dictionary<string,int>{{"3",1}},unit_prices=new Dictionary<string,string>{{"3","5.00"}}}}};
            File.WriteAllText(Path.Combine(root,"oracle.json"),JsonSerializer.Serialize(oracle));
            var contract=new MigrationContract {InitialDatabase="initial.sqlite",Oracle="oracle.json"};
            MigrationContinuity Load()=>MigrationContinuity.Load(contract,root,"1.6.0");
            var lines=new List<Html.CartLine> {new() {RecordId=1,AlbumId=1,Count=2},new() {RecordId=2,AlbumId=2,Count=1}};
            var good=Load();good.ObserveStoredOrder(initial,42,lines,"checkout");
            check("1.6 exact independent order detail/total comparison can pass",good.Judgement==Judgement.Pass && !good.HasConfirmedFailure);
            var empty=Load();empty.ObserveStoredOrder(initial,42,new List<Html.CartLine>(),"checkout");
            check("1.6 existing data preserved plus empty workflow input does not invent a stored-total failure",!empty.HasConfirmedFailure && empty.Judgement==Judgement.Blocked && empty.UnknownObservations.Count==1);
            var absent=Load();absent.ObserveStoredOrder(initial,null,lines,"checkout");
            check("1.6 valid basket but absent output order leaves storage comparison unknown",!absent.HasConfirmedFailure && absent.UnknownObservations.Count==1);
            var wrongQuantity=Load();wrongQuantity.ObserveStoredOrder(initial,42,new List<Html.CartLine> {new() {RecordId=1,AlbumId=1,Count=1},new() {RecordId=2,AlbumId=2,Count=2}},"checkout");
            check("1.6 frozen workflow comparison requires exact per-album input quantities",wrongQuantity.Judgement==Judgement.Blocked);
            var mutation=Path.Combine(root,"mutation.sqlite");File.Copy(initial,mutation);
            using(var db=new SqliteConnection("Data Source="+mutation+";Pooling=False"))
            {db.Open();using var command=db.CreateCommand();command.CommandText="UPDATE Orders SET Total='0.00' WHERE OrderId=42";command.ExecuteNonQuery();}
            var bad=Load();bad.ObserveStoredOrder(mutation,42,lines,"checkout");bad.ObserveStoredOrder(mutation,null,lines,"second");
            check("1.6 real stored-total error survives another unknown workflow",bad.HasConfirmedFailure && bad.Judgement==Judgement.Fail && bad.UnknownObservations.Count>0);
            var disappeared=Path.Combine(root,"disappeared.sqlite");File.Copy(initial,disappeared);
            using(var db=new SqliteConnection("Data Source="+disappeared+";Pooling=False"))
            {db.Open();using var command=db.CreateCommand();command.CommandText="DELETE FROM Orders WHERE OrderId=7";command.ExecuteNonQuery();}
            var lost=Load();lost.Preserved(disappeared,"after_restart");lost.ObserveStoredOrder(disappeared,null,new List<Html.CartLine>(),"checkout");
            check("1.6 independent original-row loss survives unknown new purchases",lost.HasConfirmedFailure && lost.Judgement==Judgement.Fail && lost.UnknownObservations.Count>0);
            var unreadable=Load();unreadable.Preserved(Path.Combine(root,"absent-parent","db.sqlite"),"observation");
            check("1.6 inability to open SQLite is an observer fault rather than data-destruction proof",!unreadable.HasConfirmedFailure && unreadable.ObservationFaults.Count>0);
            var tableMissing=Path.Combine(root,"table-missing.sqlite");File.Copy(initial,tableMissing);
            using(var db=new SqliteConnection("Data Source="+tableMissing+";Pooling=False"))
            {db.Open();using var command=db.CreateCommand();command.CommandText="DROP TABLE Orders";command.ExecuteNonQuery();}
            var schema=Load();schema.Preserved(tableMissing,"after_restart");
            check("1.6 observed missing contracted SQLite table remains finite product failure",schema.HasConfirmedFailure && schema.ObservationFaults.Count==0);
            var locked=Load();
            using(var writer=new SqliteConnection("Data Source="+initial+";Pooling=False"))
            {
                writer.Open();using var begin=writer.CreateCommand();begin.CommandText="BEGIN EXCLUSIVE";begin.ExecuteNonQuery();
                locked.Preserved(initial,"concurrent_read");
                check("1.6 actual SQLite BUSY read is observer fault and unknown, never product data loss",!locked.HasConfirmedFailure && locked.ObservationFaults.Count==1 && locked.UnknownObservations.Count==1);
                begin.CommandText="ROLLBACK";begin.ExecuteNonQuery();
            }
        }
        finally {Directory.Delete(root,true);}
    }
}
