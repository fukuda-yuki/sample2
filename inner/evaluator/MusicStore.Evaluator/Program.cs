using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace MusicStore.Evaluator;

public static class Program
{
    /// <summary>評価器自身の版。ビルドの同一性は evaluator_sha256 が表す。</summary>
    public const string EvaluatorVersion = "1.1.0";

    /// <summary>
    /// 判定の意味（検査集合・合否規則・配点）の既定版。--evaluation-version で上書きできる。
    /// 評価器の版とは別に進める（docs/evaluator.md §6.2）。
    /// </summary>
    public const string DefaultEvaluationVersion = "1.1.0";

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
        var faults = new List<string>();
        try
        {
            ledger = Ledger.Load(options.SpecPath);
            catalog = Catalog.Load(options.CatalogPath);
        }
        catch (Exception ex)
        {
            // 台帳やカタログが読めない場合も、評価側の障害として記録を残す。
            ledger = null;
            catalog = null;
            faults.Add(ex.Message);
        }

        if (ledger != null)
        {
            if ((ledger.SpecVersion == "1.2.0") != (options.EvaluationVersion == "1.2.0"))
                faults.Add("Evaluation 1.2.0 requires the 1.2.0 ledger; historical contracts must not be relabeled.");
            var missing = ledger.AllCheckIds().Where(id => !Checks.Registry.ContainsKey(id)).ToList();
            if (missing.Count > 0)
            {
                faults.Add("台帳の検査が実装されていません: " + string.Join(", ", missing));
            }
        }

        if (!Directory.Exists(options.ArtifactPath))
        {
            faults.Add("成果物ディレクトリが存在しません: " + options.ArtifactPath);
        }

        // 作業ディレクトリは採点ごとに空でなければならない。前の採点の SQLite
        // ファイルや生成物が残っていると、「毎回空のデータベースから始める」という
        // 初期条件を満たしたことにならないため、黙って採点せず障害として記録する。
        if (Directory.Exists(options.WorkDir)
            && Directory.EnumerateFileSystemEntries(options.WorkDir).Any())
        {
            faults.Add("作業ディレクトリが空ではありません。採点ごとに空の作業ディレクトリを"
                       + "用意してください: " + options.WorkDir);
        }

        if (faults.Count > 0)
        {
            // 成果物の品質を判定できない状態。品質点を返さず error とし、
            // 呼び出し側が成果物の欠陥と区別できるよう記録を残す。
            WriteFaultOutput(options, ledger, startedAt, faults);
            Console.Error.WriteLine("評価側の障害: " + string.Join(" / ", faults));
            return 2;
        }

        var ledgerCheckIds = ledger.AllCheckIds().ToList();
        var specHash = Sha256File(options.SpecPath);
        var artifactHash = Sha256Directory(options.ArtifactPath);
        var evaluationId = $"{ledger.TaskId}-{artifactHash.Substring(0, 12)}-{options.EvaluationVersion}-{options.Sequence:000}";

        if (options.BrowserCartBaseline != null)
        {
            try
            {
                return BrowserCartCorrection.Apply(options, ledger, catalog, evaluationId,
                    artifactHash, specHash, startedAt);
            }
            catch (Exception ex)
            {
                WriteFaultOutput(options, ledger, startedAt, new List<string> { "Browser correction: " + ex.Message });
                return 2;
            }
        }

        BrowserCartReview browserReview = null;
        if (options.BrowserCartEvidence != null)
        {
            try
            {
                browserReview = BrowserCartReview.Load(options.BrowserCartEvidence, artifactHash,
                    specHash, options.ReviewRunInstanceId, catalog);
                File.Copy(options.BrowserCartEvidence, Path.Combine(evidenceDir, "browser-cart-receipt.json"));
            }
            catch (Exception ex)
            {
                WriteFaultOutput(options, ledger, startedAt, new List<string> { "Browser evidence: " + ex.Message });
                return 2;
            }
        }

        using var host = new AppHost(options.ArtifactPath, options.WorkDir, evidenceDir);
        using var state = new RunState
        {
            Host = host,
            Ledger = ledger,
            Catalog = catalog,
            ArtifactPath = options.ArtifactPath,
            EvaluationVersion = options.EvaluationVersion,
            BrowserCartReview = browserReview,
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
        output.BrowserCartCoverage = browserReview == null ? "not_run_http_only" : "agent_observed_C-015_C-016";
        output.BrowserCartEvidenceSha256 = browserReview?.ReceiptSha256;
        output.ReviewRunInstanceId = browserReview?.RunInstanceId;
        output.ResearchStatus = browserReview != null && output.ErrorCount == 0 && output.BlockedCount == 0
            ? "complete" : "incomplete";
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
            AppProcessId = host.AppProcessId,
            AppProcessIds = host.AppProcessIds,
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

    /// <summary>
    /// 評価側の障害を記録する。終了コード 2 の経路は必ずここを通り、呼び出し側は
    /// evaluation.json の verdict=error と quality=null で成果物の欠陥と区別できる。
    /// </summary>
    private static void WriteFaultOutput(CliOptions options, Ledger ledger, DateTimeOffset startedAt, List<string> faults)
    {
        var artifactHash = Directory.Exists(options.ArtifactPath) ? Sha256Directory(options.ArtifactPath) : string.Empty;
        var shortHash = artifactHash.Length >= 12 ? artifactHash.Substring(0, 12) : "000000000000";
        var taskId = ledger == null ? "unknown" : ledger.TaskId;

        var output = new EvaluationOutput
        {
            EvaluationId = $"{taskId}-{shortHash}-{options.EvaluationVersion}-{options.Sequence:000}",
            TaskId = taskId,
            TaskTitle = ledger == null ? string.Empty : ledger.TaskTitle,
            EvaluationVersion = options.EvaluationVersion,
            SpecVersion = ledger == null ? string.Empty : ledger.SpecVersion,
            SpecSha256 = Sha256File(options.SpecPath),
            ArtifactPath = options.ArtifactPath,
            ArtifactSha256 = artifactHash,
            SourceRepository = ledger == null ? string.Empty : ledger.SourceRepository,
            SourceCommit = ledger == null ? string.Empty : ledger.SourceCommit,
            Verdict = "error",
            Quality = null,
            EvaluatorFaults = faults,
            StartedAt = startedAt.ToString("o", CultureInfo.InvariantCulture),
            FinishedAt = DateTimeOffset.Now.ToString("o", CultureInfo.InvariantCulture),
        };

        WriteJson(Path.Combine(options.OutDir, "evaluation.json"), output);
        File.WriteAllText(Path.Combine(options.OutDir, "results.jsonl"), string.Empty, new UTF8Encoding(false));
    }

    /// <summary>
    /// 成果物を起動して観測する。証跡はビルドや起動に失敗した場合も残す。
    /// </summary>
    private static void PrepareAndRun(RunState state, CliOptions options, Ledger ledger, string evidenceDir)
    {
        try
        {
            RunScenarios(state, options, evidenceDir);
        }
        finally
        {
            WriteEvidence(state, evidenceDir);
        }
    }

    private static void RunScenarios(RunState state, CliOptions options, string evidenceDir)
    {
        var candidates = AppHost.FindWebProjects(options.ArtifactPath);
        state.WebProjectFound = candidates.Count > 0;
        if (!state.WebProjectFound)
        {
            state.PublishDetail = "Microsoft.NET.Sdk.Web を使う csproj が見つかりませんでした。";
            return;
        }

        state.Host.SelectProject(candidates[0]);

        // 静的検査は csproj・成果物ツリー・DB パスしか見ないので publish より先に実行する。
        // ビルドできない成果物でも R-026 / R-027 / R-029 は観測でき、ビルドの失敗は
        // 評価側の障害ではなく R-001 の不合格として残る（docs/evaluator.md §3）。
        state.Static = Scenarios.RunStatic(state);

        var (exit, stdout, stderr) = state.Host.Publish();
        state.PublishExitCode = exit;
        state.PublishOk = exit == 0;
        state.PublishDetail = $"dotnet publish の終了コード {exit}。標準出力末尾: {AppHost.Tail(stdout, 600)} 標準エラー末尾: {AppHost.Tail(stderr, 1200)}";
        File.WriteAllText(Path.Combine(evidenceDir, "publish.log"),
            "SOURCE\n" + state.Host.SourceDir + "（成果物 " + options.ArtifactPath + " の複製）\n"
            + "STDOUT\n" + stdout + "\nSTDERR\n" + stderr, new UTF8Encoding(false));

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

        foreach (var fault in new ScenarioResult[] { state.Browse, state.Cart, state.Order, state.InvalidCheckout, state.Isolation, state.Restart, state.Static })
        {
            if (fault != null && fault.Fault == Judgement.Error)
            {
                state.Faults.Add(fault.FaultDetail);
            }
        }
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

    internal static EvaluationOutput BuildOutput(
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

    internal static void WriteResults(CliOptions options, Ledger ledger, List<CheckResult> results, EvaluationOutput output)
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
            .OrderBy(rel => rel.Replace('/', '\\'), StringComparer.Ordinal)
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
        Console.Error.WriteLine("usage: MusicStore.Evaluator --artifact <dir> --out <dir> [--spec <requirements.json>] [--catalog <catalog.json>] [--evaluation-version <v>] [--sequence <n>] [--work <dir>] [--browser-cart-evidence <receipt.json> --review-run-instance-id <id>] [--browser-cart-baseline <evaluation-directory>]");
    }
}

public sealed class CliOptions
{
    public string ArtifactPath { get; private set; }

    public string OutDir { get; private set; }

    public string WorkDir { get; private set; }

    public string SpecPath { get; private set; }

    public string CatalogPath { get; private set; }

    public string BrowserCartEvidence { get; private set; }

    public string ReviewRunInstanceId { get; private set; }

    public string BrowserCartBaseline { get; private set; }

    public string EvaluationVersion { get; private set; } = Program.DefaultEvaluationVersion;

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
                case "--browser-cart-evidence":
                    options.BrowserCartEvidence = Next();
                    break;
                case "--browser-cart-baseline":
                    options.BrowserCartBaseline = Next();
                    break;
                case "--review-run-instance-id":
                    options.ReviewRunInstanceId = Next();
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

        if ((options.BrowserCartEvidence == null) != (options.ReviewRunInstanceId == null)) return null;

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
