// Stands in for the Unity app in the SpacetimeDB spike (pass criterion 2).
//
// Subscribes to the lease table with the official C# client SDK and prints one line per row
// callback, stamped with the wall clock in Unix microseconds:
//
//   ready
//   insert <lease_id> <unix_us>
//   delete <lease_id> <unix_us>
//
// spacetime/measure.py starts it, calls reducers from Python and matches the lines to its own
// timestamps taken just before each call. Both run on one PC, so they share the clock.
// FrameTick() runs every <tick_ms>; Unity calls it once per frame, so 11 ms is a 90 Hz frame.
//
// Usage: dotnet run -c Release -- [url] [database] [tick_ms]

using System;
using System.Threading;
using SpacetimeDB;
using SpacetimeDB.Types;

static class Program
{
    static long NowMicros() => (DateTime.UtcNow.Ticks - DateTime.UnixEpoch.Ticks) / 10;

    static void Emit(string line)
    {
        lock (Console.Out)
        {
            Console.Out.WriteLine(line);
            Console.Out.Flush();
        }
    }

    static int Main(string[] args)
    {
        string url = args.Length > 0 ? args[0] : "http://127.0.0.1:3000";
        string database = args.Length > 1 ? args[1] : "spatial-modeling";
        int tickMs = args.Length > 2 ? int.Parse(args[2]) : 1;

        bool stop = false;
        int exitCode = 0;
        var conn = DbConnection.Builder()
            .WithUri(url)
            .WithDatabaseName(database)
            .OnConnect((c, identity, token) =>
            {
                c.Db.Lease.OnInsert += (ctx, row) => Emit($"insert {row.LeaseId} {NowMicros()}");
                c.Db.Lease.OnDelete += (ctx, row) => Emit($"delete {row.LeaseId} {NowMicros()}");
                c.SubscriptionBuilder()
                    .OnApplied(ctx => Emit("ready"))
                    .OnError((ctx, e) =>
                    {
                        Emit($"error subscription {e.Message}");
                        exitCode = 1;
                        stop = true;
                    })
                    .Subscribe(new[] { "SELECT * FROM lease" });
            })
            .OnConnectError(e =>
            {
                Emit($"error connect {e.Message}");
                exitCode = 1;
                stop = true;
            })
            .OnDisconnect((c, e) => stop = true)
            .Build();

        // Quit when the parent closes stdin.
        new Thread(() =>
        {
            while (Console.In.ReadLine() != null) { }
            stop = true;
        }) { IsBackground = true }.Start();

        while (!stop)
        {
            conn.FrameTick();
            Thread.Sleep(tickMs);
        }
        if (conn.IsActive)
        {
            conn.Disconnect();
        }
        return exitCode;
    }
}
