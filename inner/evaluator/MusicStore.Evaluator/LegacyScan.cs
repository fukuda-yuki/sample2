using System.Text;
using System.Text.RegularExpressions;

namespace MusicStore.Evaluator;

/// <summary>
/// 旧実装への「参照・起動」と、単なる「言及」を分ける静的走査。
///
/// コメントや説明文での言及は、旧実装への依存の根拠にしない。名前空間・アセンブリ名も
/// 同様である。根拠にするのは、対象フレームワーク設定・参照設定・起動処理という、
/// 実際に旧実装を参照または起動する記述である。ヒューリスティックであり、間接的な
/// ラッパー化を証明しない（docs/quality-spec.md §7.2）。
/// </summary>
public static class LegacyScan
{
    public sealed class Result
    {
        /// <summary>旧実装を参照・起動する記述。設定・参照・起動処理の根拠。</summary>
        public List<string> References { get; } = new List<string>();

        /// <summary>コメント・説明文での言及。診断情報であり、依存の根拠にしない。</summary>
        public List<string> Mentions { get; } = new List<string>();
    }

    private static readonly string[] ScannedExtensions =
    {
        ".csproj", ".sln", ".cs", ".cshtml", ".config", ".props", ".targets", ".json",
    };

    /// <summary>
    /// 旧実装を「参照または起動する」記述。名前空間やアセンブリ名に旧名称を使うこと自体は
    /// 移行の妨げではないので、名前の一致ではなく参照・起動の記述を見る。
    /// </summary>
    private static readonly Regex[] Signals =
    {
        new Regex(@"MvcMusicStore\.(?:exe|dll|pdb|csproj|sln)\b", RegexOptions.IgnoreCase),
        new Regex(@"\bMVC-Music-Store\b", RegexOptions.IgnoreCase),
        new Regex(@"\biisexpress\b", RegexOptions.IgnoreCase),
        new Regex(@"\bSystem\.Web\b", RegexOptions.IgnoreCase),
        new Regex(@"\bnet4[0-9]{0,2}\b", RegexOptions.IgnoreCase),
        new Regex(@"\bTargetFrameworkVersion\b", RegexOptions.IgnoreCase),
        new Regex(@"\bGlobal\.asax\b", RegexOptions.IgnoreCase),
        new Regex(@"\bpackages\.config\b", RegexOptions.IgnoreCase),
    };

    /// <summary>
    /// 旧実装のプロジェクト・アセンブリ・実行ファイル、および旧実装の構成ファイルそのもの。
    /// ファイル名は、内容の言及ではなく成果物に残った実体である。
    /// </summary>
    private static readonly Regex LegacyFileName = new Regex(
        @"^(?:MvcMusicStore\.(?:exe|dll|pdb|csproj|sln)|Global\.asax|packages\.config)$",
        RegexOptions.IgnoreCase);

    public static Result Scan(string artifactPath)
    {
        var result = new Result();
        foreach (var file in Directory.EnumerateFiles(artifactPath, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(artifactPath, file);
            var parts = relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (parts.Any(p => p.Equals("bin", StringComparison.OrdinalIgnoreCase)
                               || p.Equals("obj", StringComparison.OrdinalIgnoreCase)
                               || p.Equals("wwwroot", StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            if (LegacyFileName.IsMatch(Path.GetFileName(file)))
            {
                result.References.Add(relative + " :: 旧実装のファイルそのもの");
                continue;
            }

            var extension = Path.GetExtension(file);
            if (!ScannedExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase))
            {
                continue;
            }

            string text;
            try
            {
                text = File.ReadAllText(file);
            }
            catch (Exception)
            {
                continue;
            }

            var (code, comments) = SplitComments(text, extension);
            Collect(result.References, relative, code, "記述");
            Collect(result.Mentions, relative, comments, "コメント");
        }

        result.References.Sort(StringComparer.Ordinal);
        result.Mentions.Sort(StringComparer.Ordinal);
        return result;
    }

    private static void Collect(List<string> into, string relative, string text, string where)
    {
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        foreach (var signal in Signals)
        {
            foreach (Match match in signal.Matches(text))
            {
                var entry = relative + " :: " + match.Value + "（" + where + "）";
                if (!into.Contains(entry))
                {
                    into.Add(entry);
                }
            }
        }
    }

    /// <summary>
    /// コメントと、コメントを除いた本文に分ける。文字列リテラルは本文として残す。
    /// 文字列の中の起動コマンドは実際の起動処理であり、コメントの中の同じ語は言及である。
    /// </summary>
    private static (string Code, string Comments) SplitComments(string text, string extension)
    {
        switch (extension.ToLowerInvariant())
        {
            case ".cs":
                return SplitCSharp(text);
            case ".cshtml":
                return SplitDelimited(text, new[] { ("@*", "*@"), ("<!--", "-->") });
            case ".csproj":
            case ".props":
            case ".targets":
            case ".config":
                return SplitDelimited(text, new[] { ("<!--", "-->") });
            case ".sln":
                return SplitLineComments(text, "#");
            default:
                // .json にコメントはない。本文をそのまま見る。
                return (text, string.Empty);
        }
    }

    private static (string Code, string Comments) SplitLineComments(string text, string marker)
    {
        var code = new StringBuilder(text.Length);
        var comments = new StringBuilder();
        var index = 0;
        while (index < text.Length)
        {
            if (text[index] == '\n')
            {
                code.Append('\n');
                index++;
                continue;
            }

            var lineEnd = text.IndexOf('\n', index);
            if (lineEnd < 0)
            {
                lineEnd = text.Length;
            }

            var line = text.Substring(index, lineEnd - index);
            var at = line.IndexOf(marker, StringComparison.Ordinal);
            if (at >= 0)
            {
                code.Append(line, 0, at);
                comments.Append(line, at, line.Length - at).Append('\n');
            }
            else
            {
                code.Append(line);
            }

            index = lineEnd;
        }

        return (code.ToString(), comments.ToString());
    }

    private static (string Code, string Comments) SplitDelimited(
        string text, (string Open, string Close)[] markers)
    {
        var code = new StringBuilder(text.Length);
        var comments = new StringBuilder();
        var index = 0;
        while (index < text.Length)
        {
            var best = -1;
            var bestMarker = default((string Open, string Close));
            foreach (var marker in markers)
            {
                var at = text.IndexOf(marker.Open, index, StringComparison.Ordinal);
                if (at >= 0 && (best < 0 || at < best))
                {
                    best = at;
                    bestMarker = marker;
                }
            }

            if (best < 0)
            {
                code.Append(text, index, text.Length - index);
                break;
            }

            code.Append(text, index, best - index);
            var close = text.IndexOf(bestMarker.Close, best + bestMarker.Open.Length,
                                     StringComparison.Ordinal);
            var end = close < 0 ? text.Length : close + bestMarker.Close.Length;
            comments.Append(text, best, end - best).Append('\n');
            index = end;
        }

        return (code.ToString(), comments.ToString());
    }

    /// <summary>
    /// C# のコメントを除く。文字列・逐語的文字列・生文字列・文字リテラルの中の
    /// 「//」や「/*」はコメントではないので、本文として残す。
    /// </summary>
    private static (string Code, string Comments) SplitCSharp(string text)
    {
        var code = new StringBuilder(text.Length);
        var comments = new StringBuilder();
        var index = 0;
        while (index < text.Length)
        {
            var current = text[index];

            if (current == '/' && index + 1 < text.Length && text[index + 1] == '/')
            {
                var end = text.IndexOf('\n', index);
                if (end < 0)
                {
                    end = text.Length;
                }

                comments.Append(text, index, end - index).Append('\n');
                index = end;
                continue;
            }

            if (current == '/' && index + 1 < text.Length && text[index + 1] == '*')
            {
                var close = text.IndexOf("*/", index + 2, StringComparison.Ordinal);
                var end = close < 0 ? text.Length : close + 2;
                comments.Append(text, index, end - index).Append('\n');
                index = end;
                continue;
            }

            if (current == '@' && index + 1 < text.Length && text[index + 1] == '"')
            {
                var end = index + 2;
                while (end < text.Length)
                {
                    if (text[end] != '"')
                    {
                        end++;
                        continue;
                    }

                    if (end + 1 < text.Length && text[end + 1] == '"')
                    {
                        end += 2;
                        continue;
                    }

                    end++;
                    break;
                }

                code.Append(text, index, end - index);
                index = end;
                continue;
            }

            if (current == '"' && index + 2 < text.Length
                && text[index + 1] == '"' && text[index + 2] == '"')
            {
                var close = text.IndexOf("\"\"\"", index + 3, StringComparison.Ordinal);
                var end = close < 0 ? text.Length : close + 3;
                code.Append(text, index, end - index);
                index = end;
                continue;
            }

            if (current == '"' || current == '\'')
            {
                var end = index + 1;
                while (end < text.Length)
                {
                    if (text[end] == '\\')
                    {
                        end += 2;
                        continue;
                    }

                    if (text[end] == current)
                    {
                        end++;
                        break;
                    }

                    if (text[end] == '\n')
                    {
                        break;
                    }

                    end++;
                }

                end = Math.Min(end, text.Length);
                code.Append(text, index, end - index);
                index = end;
                continue;
            }

            code.Append(current);
            index++;
        }

        return (code.ToString(), comments.ToString());
    }
}