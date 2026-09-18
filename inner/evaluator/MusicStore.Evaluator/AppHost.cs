using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace MusicStore.Evaluator;

/// <summary>
/// 成果物のビルドと起動・停止を担う。評価側の障害（dotnet が見つからない等）と
/// 成果物の不具合（ビルドエラー、起動しない等）を区別して報告する。
/// </summary>
public sealed class AppHost : IDisposable
{
    public string ArtifactPath { get; private set; }

    public string WebProjectPath { get; private set; }

    public string PublishDir { get; private set; }

    /// <summary>成果物の複製。発行はこの複製に対して行う（成果物を書き換えないため）。</summary>
    public string SourceDir { get; private set; }

    public string DatabasePath { get; private set; }

    public string WorkDir { get; private set; }

    public string EvidenceDir { get; private set; }

    public int Port { get; private set; }

    public int AppProcessId { get; private set; }

    /// <summary>起動したアプリのプロセス ID（再起動のたびに増える）。</summary>
    public List<int> AppProcessIds { get; } = new List<int>();

    public string BaseUrl => $"http://127.0.0.1:{Port}";

    public string EntryAssembly { get; private set; }

    public bool Started { get; private set; }

    public string LastProcessLog { get; private set; } = string.Empty;

    private Process process;
    private string processLogPath;

    public AppHost(string artifactPath, string workDir, string evidenceDir)
    {
        ArtifactPath = Path.GetFullPath(artifactPath);
        WorkDir = Path.GetFullPath(workDir);
        EvidenceDir = Path.GetFullPath(evidenceDir);
        SourceDir = Path.Combine(WorkDir, "source");
        PublishDir = Path.Combine(WorkDir, "publish");
        DatabasePath = Path.Combine(WorkDir, "store.sqlite");
        Port = FreePort();
    }

    public static int FreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    public static bool DotnetAvailable(out string version)
    {
        version = string.Empty;
        var (exit, stdout, stderr) = RunProcess("dotnet", "--version", Environment.CurrentDirectory, 120);
        version = (stdout + " " + stderr).Trim();
        return exit == 0;
    }

    /// <summary>
    /// 成果物ディレクトリから Web プロジェクト（Microsoft.NET.Sdk.Web）を探す。
    /// 複数ある場合は相対パスが最も短いものを選ぶ（この規則は docs/evaluator.md に記載する）。
    /// </summary>
    public static List<string> FindWebProjects(string artifactPath)
    {
        var candidates = new List<string>();
        foreach (var file in Directory.EnumerateFiles(artifactPath, "*.csproj", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(artifactPath, file);
            var parts = relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (parts.Any(p => p.Equals("bin", StringComparison.OrdinalIgnoreCase) || p.Equals("obj", StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            XDocument project;
            try { project = XDocument.Load(file); }
            catch (System.Xml.XmlException) { continue; }
            var sdk = project.Root?.Attribute("Sdk")?.Value;
            if (sdk == "Microsoft.NET.Sdk.Web" || project.Descendants().Any(e =>
                    e.Name.LocalName == "Sdk" && e.Attribute("Name")?.Value == "Microsoft.NET.Sdk.Web"))
            {
                candidates.Add(file);
            }
        }

        return candidates.OrderBy(c => Path.GetRelativePath(artifactPath, c).Length).ThenBy(c => c, StringComparer.Ordinal).ToList();
    }

    public void SelectProject(string projectPath)
    {
        WebProjectPath = projectPath;
    }

    public (int ExitCode, string StdOut, string StdErr) Publish()
    {
        Directory.CreateDirectory(PublishDir);
        // 成果物は読み取り専用として扱う。`dotnet publish` の既定では中間ファイルと
        // ビルド出力がプロジェクトの下（`obj/` `bin/`）に書かれるため、成果物を直接発行すると
        // 採点の前後で成果物の中身が変わる。作業ディレクトリに複製してから発行する。
        var project = CopySourceProject();
        return RunProcess(
            "dotnet",
            $"publish \"{project}\" -c Release -o \"{PublishDir}\" --nologo",
            Path.GetDirectoryName(project),
            600);
    }

    /// <summary>
    /// 成果物を作業ディレクトリへ複製し、選んだプロジェクトの複製先を返す。
    /// リンクは辿らない（成果物には含まれない。回収が特殊ファイルを拒否する）。
    /// </summary>
    public string CopySourceProject()
    {
        if (Directory.Exists(SourceDir))
        {
            Directory.Delete(SourceDir, true);
        }

        CopyTree(ArtifactPath, SourceDir);
        return Path.Combine(SourceDir, Path.GetRelativePath(ArtifactPath, WebProjectPath));
    }

    private static void CopyTree(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var directory in Directory.GetDirectories(source))
        {
            if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
            {
                continue;
            }

            CopyTree(directory, Path.Combine(destination, Path.GetFileName(directory)));
        }

        foreach (var file in Directory.GetFiles(source))
        {
            File.Copy(file, Path.Combine(destination, Path.GetFileName(file)), true);
        }
    }

    public string FindEntryAssembly()
    {
        var runtimeConfig = Directory.EnumerateFiles(PublishDir, "*.runtimeconfig.json", SearchOption.TopDirectoryOnly)
            .OrderBy(f => f.Length)
            .ThenBy(f => f, StringComparer.Ordinal)
            .FirstOrDefault();
        if (runtimeConfig == null)
        {
            return null;
        }

        var name = Path.GetFileName(runtimeConfig);
        name = name.Substring(0, name.Length - ".runtimeconfig.json".Length);
        var dll = Path.Combine(PublishDir, name + ".dll");
        EntryAssembly = File.Exists(dll) ? dll : null;
        return EntryAssembly;
    }

    public void Start()
    {
        Directory.CreateDirectory(WorkDir);
        processLogPath = Path.Combine(EvidenceDir, "app-process.log");
        var log = new StringBuilder();

        var startInfo = new ProcessStartInfo
        {
            FileName = "dotnet",
            WorkingDirectory = PublishDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        RestrictEnvironment(startInfo);
        startInfo.ArgumentList.Add(EntryAssembly);
        startInfo.ArgumentList.Add("--urls");
        startInfo.ArgumentList.Add(BaseUrl);
        startInfo.Environment["ConnectionStrings__MusicStoreEntities"] = $"Data Source={DatabasePath}";
        startInfo.Environment["ASPNETCORE_ENVIRONMENT"] = "Production";
        startInfo.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1";
        startInfo.Environment["DOTNET_NOLOGO"] = "1";

        process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data != null)
            {
                lock (log)
                {
                    log.AppendLine(e.Data);
                }
            }
        };
        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data != null)
            {
                lock (log)
                {
                    log.AppendLine(e.Data);
                }
            }
        };

        process.Start();
        AppProcessId = process.Id;
        AppProcessIds.Add(process.Id);
        AppendEvidenceHeader();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        Started = true;
        ProcessLogSink = log;
    }

    /// <summary>
    /// アプリのプロセス ID と接続先を起動直後に証跡へ書く。評価器自体が強制終了されると
    /// Stop() に到達しないため、残骸を後から特定できる行は先に書いておく必要がある。
    /// </summary>
    private void AppendEvidenceHeader()
    {
        if (processLogPath == null)
        {
            return;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(processLogPath));
        using var writer = new StreamWriter(processLogPath, append: true, new UTF8Encoding(false));
        writer.Write($"===== app process (pid {AppProcessId}, url {BaseUrl}, started {DateTimeOffset.Now:o}) =====\n");
    }

    private StringBuilder ProcessLogSink;

    public void Stop()
    {
        if (process != null)
        {
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                    process.WaitForExit(20000);
                }
            }
            catch (Exception)
            {
                // 停止の失敗は評価の結論に影響させない。
            }
        }

        FlushLog();
        Started = false;
    }

    public void FlushLog()
    {
        if (ProcessLogSink != null && processLogPath != null)
        {
            lock (ProcessLogSink)
            {
                LastProcessLog = ProcessLogSink.ToString();
            }

            Directory.CreateDirectory(Path.GetDirectoryName(processLogPath));
            // 再起動を挟むと 2 つ目のプロセスのログで上書きされてしまうため追記する。
            using var writer = new StreamWriter(processLogPath, append: true, new UTF8Encoding(false));
            writer.Write($"===== app process log (pid {AppProcessId}, url {BaseUrl}, {DateTimeOffset.Now:o}) =====\n");
            writer.Write(LastProcessLog);
            writer.Write('\n');
        }
    }

    public bool ProcessExited => process == null || process.HasExited;

    /// <summary>
    /// GET / が 200 を返すまで待つ。プロセスが先に終了した場合はその場で失敗とする。
    /// </summary>
    public (bool Ready, string Detail) WaitReady(TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        var lastDetail = "応答なし";

        while (DateTime.UtcNow < deadline)
        {
            if (ProcessExited)
            {
                FlushLog();
                return (false, $"アプリのプロセスが応答前に終了しました（exit code {process?.ExitCode}）。ログ末尾: {Tail(LastProcessLog, 1200)}");
            }

            try
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
                using var response = client.GetAsync(BaseUrl + "/").GetAwaiter().GetResult();
                if ((int)response.StatusCode < 500)
                {
                    return (true, $"GET / が {(int)response.StatusCode} を返しました。");
                }

                lastDetail = $"GET / が {(int)response.StatusCode} を返しました。";
            }
            catch (Exception ex)
            {
                lastDetail = ex.GetType().Name + ": " + ex.Message;
            }

            Thread.Sleep(500);
        }

        FlushLog();
        return (false, $"起動待ちがタイムアウトしました（{timeout.TotalSeconds:0} 秒）。最後の状態: {lastDetail}");
    }

    public void Dispose()
    {
        Stop();
        process?.Dispose();
    }

    public static string Tail(string text, int length)
    {
        if (string.IsNullOrEmpty(text))
        {
            return string.Empty;
        }

        text = text.Replace("\r", " ").Replace("\n", " | ");
        return text.Length <= length ? text : text.Substring(text.Length - length);
    }

    public static (int ExitCode, string StdOut, string StdErr) RunProcess(string fileName, string arguments, string workingDirectory, int timeoutSeconds)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            WorkingDirectory = workingDirectory ?? Environment.CurrentDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        RestrictEnvironment(startInfo);

        using var proc = new Process { StartInfo = startInfo };
        var stdout = new StringBuilder();
        var stderr = new StringBuilder();
        proc.OutputDataReceived += (_, e) => { if (e.Data != null) { lock (stdout) { stdout.AppendLine(e.Data); } } };
        proc.ErrorDataReceived += (_, e) => { if (e.Data != null) { lock (stderr) { stderr.AppendLine(e.Data); } } };
        proc.Start();
        proc.BeginOutputReadLine();
        proc.BeginErrorReadLine();

        if (!proc.WaitForExit(timeoutSeconds * 1000))
        {
            try
            {
                proc.Kill(entireProcessTree: true);
                proc.WaitForExit(30000);
            }
            catch (Exception)
            {
            }

            return (-1, stdout.ToString(), stderr.ToString() + $"\n(タイムアウト: {timeoutSeconds} 秒)");
        }

        proc.WaitForExit();
        return (proc.ExitCode, stdout.ToString(), stderr.ToString());
    }

    public static void RestrictEnvironment(ProcessStartInfo startInfo)
    {
        var allowed = new[] { "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
            "PROGRAMW6432", "DOTNET_ROOT", "DOTNET_ROOT_X64", "NUGET_PACKAGES", "LANG", "LC_ALL" };
        startInfo.Environment.Clear();
        foreach (var name in allowed)
        {
            var value = Environment.GetEnvironmentVariable(name);
            if (value != null) startInfo.Environment[name] = value;
        }
        startInfo.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1";
        startInfo.Environment["DOTNET_NOLOGO"] = "1";
    }
}
