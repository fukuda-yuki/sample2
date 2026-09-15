using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace MusicStore.Evaluator;

public static class Program
{
    public const string EvaluatorVersion = "1.0.0";

    public static int Main(string[] args)
    {
        var options = CliOptions.Parse(args);
        if (options == null)
        {
            PrintUsage();
            return 1;
        }

        Directory.CreateDirectory(options.OutDir);
        var evidenceDir = Path.Combine(options.OutDir, "evidence");
        Directory.CreateDirectory(evidenceDir);

        var startedAt = DateTimeOffset.Now;

        Ledger ledger;
        Catalog catalog;
        try
        {
            ledger = Ledger.Load(options.SpecPath);
            catalog = Catalog.Load(options.CatalogPath);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("評価側の障害: " + ex.Message);
            return 2;
        }

        var ledgerCheckIds = ledger.AllCheckIds().ToList();
        var missing = ledgerCheckIds.Where(id => !Checks.Registry.ContainsKey(id)).ToList();
        if (missing.Count > 0)
        {
            // 台帳にある検査が実装されていない = 評価側の障害。成果物の失敗として扱わない。
            var faultOutput = new EvaluationOutput
            {
                EvaluationId = $"{ledger.TaskId}-nospec-{options.EvaluationVersion}-{options.Sequence:000}",
                TaskId = ledger.TaskId,
                TaskTitle = ledger.TaskTitle,
                EvaluationVersion = options.EvaluationVersion,
                SpecVersion = ledger.SpecVersion,
                ArtifactPath = options.ArtifactPath,
                Verdict = "error",
                Quality = null,
                EvaluatorFaults = { "台帳の検査が実装されていません: " + string.Join(", ", missing) },
                StartedAt = startedAt.ToString("o", CultureInfo.InvariantCulture),
                FinishedAt = DateTimeOffset.Now.ToString("o", CultureInfo.InvariantCulture),
            };
            WriteJson(Path.Combine(options.OutDir, "evaluation.json"), faultOutput);
            Console.Error.WriteLine("評価側の障害: 未実装の検査 " + string.Join(", ", missing));
            return 2;
        }

        var specHash = Sha256File(options.SpecPath);
        var artifactHash = Sha256Directory(options.ArtifactPath);
        var evaluationId = $"{ledger.TaskId}-{artifactHash.Substring(0, 12)}-{options.EvaluationVersion}-{options.Sequence:000}";

        using var host = new AppHost(options.ArtifactPath, options.WorkDir, evidenceDir);
        using var state = new RunState
        {
            Host = host,
            Ledger = ledger,
            Catalog = catalog,
            ArtifactPath = options.ArtifactPath,
        };

        Console.WriteLine($"[evaluator] evaluation id: {evaluationId}");
        Console.WriteLine($"[evaluator] artifact: {options.ArtifactPath} (sha256 {artifactHash.Substring(0, 12)})");
        Console.WriteLine($"[evaluator] work dir: {options.WorkDir}");

        state.DotnetAvailable = AppHost.DotnetAvailable(out var dotnetVersion);
        state.DotnetVersion = dotnetVersion;
        if (!state.DotnetAvailable)
        {
            state.EvaluatorFault = "dotnet が見つかりません。評価環境の障害です: " + dotnetVersion;
        }
        else
        {
            PrepareAndRun(state, options, ledger, evidenceDir);
        }

        var results = new List<CheckResult>();
        foreach (var requirement in ledger.Requirements)
        {
            foreach (var check in requirement.Checks)
            {
                CheckResult result;
                try
                {
                    result = Checks.Registry[check.Id](state);
                }
                catch (Exception ex)
                {
                    result = new CheckResult
                    {
                        RequirementId = requirement.Id,
                        CheckId = check.Id,
                        Input = "(評価器の内部)",
                        Expectation = requirement.Expectation,
                        Observation = "評価側の障害: " + ex.GetType().Name + ": " + ex.Message,
                        Judgement = Judgement.Error,
                        Evidence = string.Empty,
                    };
                }

                results.Add(result);
            }
        }

        var output = BuildOutput(ledger, options, evaluationId, specHash, artifactHash, startedAt, results);
        WriteResults(options, ledger, results, output);

        var manifest = new EvaluatorManifest
        {
            EvaluatorVersion = EvaluatorVersion,
            EvaluationVersion = options.EvaluationVersion,
            EvaluatorSha256 = Sha256File(typeof(Program).Assembly.Location),
            SpecPath = options.SpecPath,
            SpecSha256 = specHash,
            ArtifactPath = options.ArtifactPath,
            ArtifactSha256 = artifactHash,
            WebProject = host.WebProjectPath,
            PublishDirectory = host.PublishDir,
            DatabasePath = host.DatabasePath,
            Port = host.Port,
            LedgerCheckIds = ledgerCheckIds,
            ImplementedCheckIds = Checks.Registry.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList(),
        };
        WriteJson(Path.Combine(options.OutDir, "evaluator-manifest.json"), manifest);

        Console.WriteLine($"[evaluator] verdict: {output.Verdict}, quality: {(output.Quality.HasValue ? output.Quality.Value.ToString("0.00", CultureInfo.InvariantCulture) : "null")}");
        Console.WriteLine($"[evaluator] requirements: pass {output.PassedCount} / fail {output.FailedCount} / blocked {output.BlockedCount} / error {output.ErrorCount}");
        if (output.CriticalFailed.Count > 0)
        {
            Console.WriteLine("[evaluator] critical failed: " + string.Join(", ", output.CriticalFailed));
        }

        return output.Verdict == "error" ? 2 : 0;
    }

    private static void PrepareAndRun(RunState state, CliOptions options, Ledger ledger, string evidenceDir)
    {
        var candidates = AppHost.FindWebProjects(options.ArtifactPath);
        state.WebProjectFound = candidates.Count > 0;
        if (!state.WebProjectFound)
        {
            state.PublishDetail = "Microsoft.NET.Sdk.Web を使う csproj が見つかりませんでした。";
            return;
        }

        state.Host.SelectProject(candidates[0]);

        var (exit, stdout, stderr) = state.Host.Publish();
        state.PublishExitCode = exit;
        state.PublishOk = exit == 0;
        state.PublishDetail = $"dotnet publish の終了コード {exit}。標準出力末尾: {AppHost.Tail(stdout, 600)} 標準エラー末尾: {AppHost.Tail(stderr, 1200)}";
        File.WriteAllText(Path.Combine(evidenceDir, "publish.log"), "STDOUT\n" + stdout + "\nSTDERR\n" + stderr, new UTF8Encoding(false));

        if (!state.PublishOk)
        {
            return;
        }

        state.EntryAssemblyFound = state.Host.FindEntryAssembly() != null;
        if (!state.EntryAssemblyFound)
        {
            return;
        }

        state.Host.Start();
        var (ready, detail) = state.Host.WaitReady(TimeSpan.FromSeconds(60));
        state.AppReady = ready;
        state.AppStartDetail = detail;
        if (!ready)
        {
            return;
        }

        using (var probe = new WebSession(state.Host.BaseUrl))
        {
            var root = probe.Get("/");
            state.RootStatus = root.Status;
            state.RootBody = root.Body;
        }

        state.Browse = Scenarios.RunBrowse(state);
        state.Cart = Scenarios.RunCart(state);
        state.Order = Scenarios.RunOrder(state);
        state.InvalidCheckout = Scenarios.RunInvalidCheckout(state);
        state.Isolation = Scenarios.RunIsolation(state);
        state.Restart = Scenarios.RunRestart(state, state.Order.OrderId);
        state.Static = Scenarios.RunStatic(state);

        foreach (var fault in new ScenarioResult[] { state.Browse, state.Cart, state.Order, state.InvalidCheckout, state.Isolation, state.Restart, state.Static })
        {
            if (fault != null && fault.Fault == Judgement.Error)
            {
                state.Faults.Add(fault.FaultDetail);
            }
        }

        WriteEvidence(state, evidenceDir);
    }

    private static void WriteEvidence(RunState state, string evidenceDir)
    {
        foreach (var name in new[] { "browse", "redirect", "cart", "order", "other", "invalid", "isolation-a", "isolation-b", "restart" })
        {
            var transcript = state.Transcript(name);
            if (!string.IsNullOrWhiteSpace(transcript))
            {
                File.WriteAllText(Path.Combine(evidenceDir, $"http-{name}.log"), transcript, new UTF8Encoding(false));
            }
        }
    }

    private static EvaluationOutput BuildOutput(
        Ledger ledger,
        CliOptions options,
        string evaluationId,
        string specHash,
        string artifactHash,
        DateTimeOffset startedAt,
        List<CheckResult> results)
    {
        var output = new EvaluationOutput
        {
            EvaluationId = evaluationId,
            TaskId = ledger.TaskId,
            TaskTitle = ledger.TaskTitle,
            EvaluationVersion = options.EvaluationVersion,
            SpecVersion = ledger.SpecVersion,
            SpecSha256 = specHash,
            ArtifactPath = options.ArtifactPath,
            ArtifactSha256 = artifactHash,
            SourceRepository = ledger.SourceRepository,
            SourceCommit = ledger.SourceCommit,
            StartedAt = startedAt.ToString("o", CultureInfo.InvariantCulture),
            FinishedAt = DateTimeOffset.Now.ToString("o", CultureInfo.InvariantCulture),
        };

        foreach (var requirement in ledger.Requirements)
        {
            var own = results.Where(r => r.RequirementId == requirement.Id).ToList();
            var judgement = Judgement.Pass;
            if (own.Any(r => r.Judgement == Judgement.Error))
            {
                judgement = Judgement.Error;
            }
            else if (own.Any(r => r.Judgement == Judgement.Fail))
            {
                judgement = Judgement.Fail;
            }
            else if (own.Any(r => r.Judgement == Judgement.Blocked))
            {
                judgement = Judgement.Blocked;
            }

            var outcome = new RequirementOutcome
            {
                Id = requirement.Id,
                Category = requirement.Category,
                Title = requirement.Title,
                Severity = requirement.Severity,
                Basis = requirement.Basis,
                Expectation = requirement.Expectation,
                Judgement = judgement,
                FailedChecks = own.Where(r => r.Judgement != Judgement.Pass).Select(r => r.CheckId).ToList(),
            };

            output.Requirements.Add(outcome);

            switch (judgement)
            {
                case Judgement.Pass:
                    output.PassedCount++;
                    break;
                case Judgement.Fail:
                    output.FailedCount++;
                    if (requirement.Severity == "critical")
                    {
                        output.CriticalFailed.Add(requirement.Id);
                    }

                    break;
                case Judgement.Blocked:
                    output.BlockedCount++;
                    output.UncheckedScope.Add(requirement.Id + "（前提不成立のため未評価）");
                    break;
                default:
                    output.ErrorCount++;
                    output.UncheckedScope.Add(requirement.Id + "（評価側の障害のため判定不能）");
                    break;
            }
        }

        output.RequirementCount = ledger.Requirements.Count;
        output.EvaluatorFaults.AddRange(results.Where(r => r.Judgement == Judgement.Error).Select(r => r.CheckId + ": " + r.Observation).Distinct());

        if (output.ErrorCount > 0)
        {
            // 評価側の障害があるときは品質点を返さない。0 に置き換えない。
            output.Verdict = "error";
            output.Quality = null;
        }
        else
        {
            output.Quality = Math.Round(output.PassedCount * 100.0 / output.RequirementCount, 2);
            if (output.CriticalFailed.Count > 0)
            {
                output.Verdict = "fail_critical";
            }
            else if (output.FailedCount > 0)
            {
                output.Verdict = "fail";
            }
            else if (output.BlockedCount > 0)
            {
                output.Verdict = "blocked";
            }
            else
            {
                output.Verdict = "pass";
            }
        }

        return output;
    }

    private static void WriteResults(CliOptions options, Ledger ledger, List<CheckResult> results, EvaluationOutput output)
    {
        WriteJson(Path.Combine(options.OutDir, "evaluation.json"), output);

        var builder = new StringBuilder();
        foreach (var result in results)
        {
            builder.Append(System.Text.Json.JsonSerializer.Serialize(result, Json.WriteCompact)).Append('\n');
        }

        File.WriteAllText(Path.Combine(options.OutDir, "results.jsonl"), builder.ToString(), new UTF8Encoding(false));
    }

    private static void WriteJson<T>(string path, T value)
    {
        File.WriteAllText(path, System.Text.Json.JsonSerializer.Serialize(value, Json.Write) + "\n", new UTF8Encoding(false));
    }

    public static string Sha256File(string path)
    {
        if (string.IsNullOrEmpty(path) || !File.Exists(path))
        {
            return string.Empty;
        }

        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    /// <summary>
    /// 成果物の同一性を表すハッシュ。bin/obj/.git を除いた全ファイルの
    /// 「相対パス + 内容ハッシュ」を並べたもののハッシュ。
    /// </summary>
    public static string Sha256Directory(string root)
    {
        root = Path.GetFullPath(root);
        var builder = new StringBuilder();
        var files = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
            .Select(f => Path.GetRelativePath(root, f))
            .Where(rel => !rel.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                .Any(p => p.Equals("bin", StringComparison.OrdinalIgnoreCase)
                    || p.Equals("obj", StringComparison.OrdinalIgnoreCase)
                    || p.Equals(".git", StringComparison.OrdinalIgnoreCase)))
            .OrderBy(rel => rel, StringComparer.Ordinal)
            .ToList();

        foreach (var rel in files)
        {
            using var stream = File.OpenRead(Path.Combine(root, rel));
            var hash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            builder.Append(rel.Replace('\\', '/')).Append(' ').Append(hash).Append('\n');
        }

        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(builder.ToString()))).ToLowerInvariant();
    }

    private static void PrintUsage()
    {
        Console.Error.WriteLine("usage: MusicStore.Evaluator --artifact <dir> --out <dir> [--spec <requirements.json>] [--catalog <catalog.json>] [--evaluation-version <v>] [--sequence <n>] [--work <dir>]");
    }
}

public sealed class CliOptions
{
    public string ArtifactPath { get; private set; }

    public string OutDir { get; private set; }

    public string WorkDir { get; private set; }

    public string SpecPath { get; private set; }

    public string CatalogPath { get; private set; }

    public string EvaluationVersion { get; private set; } = Program.EvaluatorVersion;

    public int Sequence { get; private set; } = 1;

    public static CliOptions Parse(string[] args)
    {
        var options = new CliOptions();
        for (var i = 0; i < args.Length; i++)
        {
            var key = args[i];
            string Next()
            {
                return i + 1 < args.Length ? args[++i] : null;
            }

            switch (key)
            {
                case "--artifact":
                    options.ArtifactPath = Next();
                    break;
                case "--out":
                    options.OutDir = Next();
                    break;
                case "--work":
                    options.WorkDir = Next();
                    break;
                case "--spec":
                    options.SpecPath = Next();
                    break;
                case "--catalog":
                    options.CatalogPath = Next();
                    break;
                case "--evaluation-version":
                    options.EvaluationVersion = Next();
                    break;
                case "--sequence":
                    if (!int.TryParse(Next(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var sequence))
                    {
                        return null;
                    }

                    options.Sequence = sequence;
                    break;
                default:
                    return null;
            }
        }

        if (string.IsNullOrEmpty(options.ArtifactPath) || string.IsNullOrEmpty(options.OutDir))
        {
            return null;
        }

        options.ArtifactPath = Path.GetFullPath(options.ArtifactPath);
        options.OutDir = Path.GetFullPath(options.OutDir);
        options.WorkDir = Path.GetFullPath(options.WorkDir ?? Path.Combine(options.OutDir, "work"));

        if (string.IsNullOrEmpty(options.SpecPath))
        {
            var found = FindUpward("inner/spec/requirements.json");
            if (found == null)
            {
                return null;
            }

            options.SpecPath = found;
        }

        if (string.IsNullOrEmpty(options.CatalogPath))
        {
            options.CatalogPath = Path.Combine(Path.GetDirectoryName(options.SpecPath), "catalog.json");
        }

        return options;
    }

    private static string FindUpward(string relative)
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory != null)
        {
            var candidate = Path.Combine(directory.FullName, relative.Replace('/', Path.DirectorySeparatorChar));
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        return null;
    }
}
