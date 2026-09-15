using System.Text.Json;
using System.Text.Json.Serialization;

namespace MusicStore.Evaluator;

public sealed class LedgerCheck
{
    public string Id { get; set; }

    public string Observation { get; set; }
}

public sealed class LedgerRequirement
{
    public string Id { get; set; }

    public string Category { get; set; }

    public string Title { get; set; }

    public string Severity { get; set; }

    public string Basis { get; set; }

    public string BasisDetail { get; set; }

    public string Expectation { get; set; }

    public List<LedgerCheck> Checks { get; set; } = new List<LedgerCheck>();
}

public sealed class Ledger
{
    public string SpecVersion { get; set; }

    public string TaskId { get; set; }

    public string TaskTitle { get; set; }

    public string SourceRepository { get; set; }

    public string SourceCommit { get; set; }

    public List<LedgerRequirement> Requirements { get; set; } = new List<LedgerRequirement>();

    public List<string> OutOfScope { get; set; } = new List<string>();

    public List<string> KnownLimits { get; set; } = new List<string>();

    private static readonly JsonSerializerOptions ReadOptions = new JsonSerializerOptions
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    public static Ledger Load(string path)
    {
        var ledger = JsonSerializer.Deserialize<Ledger>(File.ReadAllText(path), ReadOptions);
        if (ledger == null)
        {
            throw new InvalidOperationException($"要件台帳を読み込めません: {path}");
        }

        return ledger;
    }

    public IEnumerable<string> AllCheckIds() => Requirements.SelectMany(r => r.Checks).Select(c => c.Id);
}

public static class Judgement
{
    public const string Pass = "pass";
    public const string Fail = "fail";
    public const string Blocked = "blocked";
    public const string Error = "error";
}

/// <summary>
/// 前提不成立（成果物の不具合ではなく、判定に進めない状態）。判定は blocked になる。
/// </summary>
public sealed class PreconditionException : Exception
{
    public PreconditionException(string message) : base(message)
    {
    }
}

public sealed class CheckResult
{
    public string RequirementId { get; set; }

    public string CheckId { get; set; }

    public string Input { get; set; }

    public string Expectation { get; set; }

    public string Observation { get; set; }

    public string Judgement { get; set; }

    public string Evidence { get; set; }
}

public sealed class RequirementOutcome
{
    public string Id { get; set; }

    public string Category { get; set; }

    public string Title { get; set; }

    public string Severity { get; set; }

    public string Basis { get; set; }

    public string Expectation { get; set; }

    public string Judgement { get; set; }

    public List<string> FailedChecks { get; set; } = new List<string>();
}

public sealed class EvaluationOutput
{
    public string EvaluationId { get; set; }

    public string TaskId { get; set; }

    public string TaskTitle { get; set; }

    public string EvaluationVersion { get; set; }

    public string SpecVersion { get; set; }

    public string SpecSha256 { get; set; }

    public string ArtifactPath { get; set; }

    public string ArtifactSha256 { get; set; }

    public string SourceRepository { get; set; }

    public string SourceCommit { get; set; }

    public string StartedAt { get; set; }

    public string FinishedAt { get; set; }

    public string Verdict { get; set; }

    public double? Quality { get; set; }

    public int RequirementCount { get; set; }

    public int PassedCount { get; set; }

    public int FailedCount { get; set; }

    public int BlockedCount { get; set; }

    public int ErrorCount { get; set; }

    public List<string> CriticalFailed { get; set; } = new List<string>();

    public List<string> UncheckedScope { get; set; } = new List<string>();

    public List<string> EvaluatorFaults { get; set; } = new List<string>();

    public List<RequirementOutcome> Requirements { get; set; } = new List<RequirementOutcome>();
}

public sealed class EvaluatorManifest
{
    public string EvaluatorVersion { get; set; }

    public string EvaluationVersion { get; set; }

    public string EvaluatorSha256 { get; set; }

    public string SpecPath { get; set; }

    public string SpecSha256 { get; set; }

    public string ArtifactPath { get; set; }

    public string ArtifactSha256 { get; set; }

    public string WebProject { get; set; }

    public string PublishDirectory { get; set; }

    public string DatabasePath { get; set; }

    public int Port { get; set; }

    public int AppProcessId { get; set; }

    public List<int> AppProcessIds { get; set; }

    public List<string> LedgerCheckIds { get; set; } = new List<string>();

    public List<string> ImplementedCheckIds { get; set; } = new List<string>();
}

public static class Json
{
    public static readonly JsonSerializerOptions Write = new JsonSerializerOptions
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static readonly JsonSerializerOptions WriteCompact = new JsonSerializerOptions
    {
        WriteIndented = false,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };
}
