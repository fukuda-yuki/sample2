using System.Text.Json;

namespace MusicStore.Evaluator;

/// <summary>Compose two observed browser checks with a bound, immutable HTTP evaluation.
/// No application or unrelated scenario is executed in this mode.</summary>
public static class BrowserCartCorrection
{
    public static int Apply(CliOptions options, Ledger ledger, Catalog catalog, string evaluationId,
        string artifactHash, string specHash, DateTimeOffset startedAt)
    {
        var readOptions = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        var baselineFile = Path.Combine(options.BrowserCartBaseline, "evaluation.json");
        var resultsFile = Path.Combine(options.BrowserCartBaseline, "results.jsonl");
        var baseline = JsonSerializer.Deserialize<EvaluationOutput>(File.ReadAllText(baselineFile), readOptions);
        var results = File.ReadLines(resultsFile).Where(s => !string.IsNullOrWhiteSpace(s))
            .Select(s => JsonSerializer.Deserialize<CheckResult>(s, readOptions)).ToList();
        if (baseline.ArtifactSha256 != artifactHash || baseline.SpecSha256 != specHash
            || baseline.TaskId != ledger.TaskId || baseline.SpecVersion != ledger.SpecVersion
            || baseline.EvaluationVersion != options.EvaluationVersion
            || baseline.BrowserCartEvidenceSha256 != null
            || !results.Select(r => r.CheckId).Order().SequenceEqual(ledger.AllCheckIds().Order())
            || results.Any(r => !ledger.Requirements.Single(q => q.Checks.Any(c => c.Id == r.CheckId)).Id.Equals(r.RequirementId))
            || results.Any(r => !new[] { Judgement.Pass, Judgement.Fail, Judgement.Blocked, Judgement.Error }.Contains(r.Judgement)))
            throw new InvalidDataException("Baseline identity, HTTP-only scope or complete check set mismatch.");

        var reconstructed = Program.BuildOutput(ledger, options, evaluationId, specHash, artifactHash, startedAt, results);
        if (reconstructed.Verdict != baseline.Verdict || reconstructed.Quality != baseline.Quality
            || !reconstructed.Requirements.Select(r => (r.Id, r.Judgement)).Order()
                .SequenceEqual(baseline.Requirements.Select(r => (r.Id, r.Judgement)).Order()))
            throw new InvalidDataException("Baseline check results disagree with its evaluation.");

        BrowserCartReview browser = null;
        var faults = new List<string>();
        try { browser = BrowserCartReview.Load(options.BrowserCartEvidence, artifactHash, specHash,
            options.ReviewRunInstanceId, catalog); }
        catch (Exception ex) { faults.Add("Browser evidence: " + ex.Message); }
        if (browser != null) faults.AddRange(browser.Faults);
        foreach (var result in results.Where(r => r.CheckId is "C-015" or "C-016"))
        {
            var observed = browser?.For(result.CheckId);
            // The browser can veto an HTTP pass, but cannot erase a prior HTTP failure.
            if (result.Judgement == Judgement.Pass)
                result.Judgement = observed?.Complete != true ? Judgement.Blocked : observed.Pass ? Judgement.Pass : Judgement.Fail;
            result.Input += "; independent browser assessment (action recorded separately)";
            result.Observation += "\n" + (observed?.Detail ?? "Browser observation unavailable; HTTP failures retained.");
            result.Evidence += "\nbrowser-cart/receipt.json (relative to this evaluation directory)";
        }
        foreach (var failure in browser?.ProductFailures ?? new())
        {
            var result = results.Single(r => r.CheckId == failure.Key);
            if (result.Judgement == Judgement.Pass) result.Judgement = Judgement.Fail;
            result.Observation += "\n" + failure.Value;
            result.Evidence += "\nbrowser-cart/receipt.json";
        }
        var output = Program.BuildOutput(ledger, options, evaluationId, specHash, artifactHash, startedAt, results);
        output.BrowserCartCoverage = browser?.Coverage ?? "evaluator_fault";
        output.BrowserCartCases = browser?.Cases ?? new() { ["C-015"] = "not_run", ["C-016"] = "not_run" };
        output.BrowserCartEvidenceSha256 = browser?.ReceiptSha256;
        output.ReviewRunInstanceId = options.ReviewRunInstanceId;
        output.EvaluatorFaults.AddRange(faults);
        output.ResearchStatus = browser?.Complete == true && output.ErrorCount == 0 && output.BlockedCount == 0 ? "complete" : "incomplete";
        if (output.ResearchStatus != "complete")
        {
            output.Quality = null;
            // A technical gap cannot erase an already verified product failure.
            output.Verdict = output.CriticalFailed.Count > 0 ? "fail_critical" : output.FailedCount > 0 ? "fail"
                : faults.Count > 0 ? "error" : "blocked";
        }
        output.ObservationScope = "C-015/C-016 browser actions or unavailable observations plus saved HTTP checks; "
            + "C-013 may be vetoed by verified two-add quantity evidence; other checks inherited";
        output.BaselineEvaluationSha256 = Program.Sha256File(baselineFile);
        output.BaselineResultsSha256 = Program.Sha256File(resultsFile);
        Program.WriteResults(options, ledger, results, output);
        var manifest = new
        {
            evaluatorVersion = Program.EvaluatorVersion, evaluatorSha256 = Program.Sha256File(typeof(Program).Assembly.Location),
            evaluationVersion = options.EvaluationVersion, artifactSha256 = artifactHash, specSha256 = specHash,
            baselineEvaluationId = baseline.EvaluationId, output.BaselineEvaluationSha256, output.BaselineResultsSha256,
            output.ObservationScope, output.BrowserCartEvidenceSha256, output.ReviewRunInstanceId,
        };
        File.WriteAllText(Path.Combine(options.OutDir, "evaluator-manifest.json"), JsonSerializer.Serialize(manifest, Json.Write));
        Console.WriteLine($"Browser composition: {output.Verdict}, quality {output.Quality}; research {output.ResearchStatus}");
        return output.ResearchStatus != "complete" ? 2 : 0;
    }
}
