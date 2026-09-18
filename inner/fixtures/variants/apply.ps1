<#
.SYNOPSIS
  正例と同じ要件を満たす別表現を作る（表現の違いで落とさないことの校正用）。

.DESCRIPTION
  負例と同じく「正例 + 差分」として表現する。違うのは期待する判定で、こちらは
  **すべて pass でなければならない**。差分は等価な表現への書き換えに限り、
  観測される値（識別子・金額・件数）は変えない。表現の違いを誤って不合格に
  する状態を、静かに「正例だけが通る評価器」として通さないため。

.EXAMPLE
  ./apply.ps1 -Name single-quoted-attributes -Out ../../runs/var-001/artifact
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Out
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$reference = Join-Path (Split-Path -Parent $here) 'reference'

if (-not (Test-Path $reference)) {
    throw "正例フィクスチャが見つかりません: $reference"
}

if (Test-Path $Out) {
    throw 'Fixture output already exists; choose a new path to preserve prior evidence.'
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null

# bin/obj を除いてコピーする（成果物ハッシュもこの 2 つを無視する）。
robocopy $reference $Out /E /XD bin obj /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "robocopy が失敗しました（終了コード $LASTEXITCODE）"
}

# 成果物のソースは .gitattributes により LF に固定されている。差分のアンカーも LF で組む。
$nl = "`n"
$log = New-Object System.Collections.Generic.List[string]

function Edit-File {
    param(
        [string]$RelativePath,
        [string]$Old,
        [string]$New,
        [string]$Description
    )

    $path = Join-Path $Out $RelativePath
    if (-not (Test-Path $path)) {
        throw "対象ファイルがありません: $RelativePath"
    }

    $text = [System.IO.File]::ReadAllText($path)
    if (-not $text.Contains($Old)) {
        throw "置換対象が見つかりません（$Description）: $RelativePath"
    }

    if (([regex]::Matches($text, [regex]::Escape($Old))).Count -ne 1) {
        throw "置換対象が一意ではありません（$Description）: $RelativePath"
    }

    [System.IO.File]::WriteAllText($path, $text.Replace($Old, $New))
    $log.Add("$Description ($RelativePath)")
}

function Add-File {
    param(
        [string]$RelativePath,
        [string]$Content,
        [string]$Description
    )

    $path = Join-Path $Out $RelativePath
    $parent = Split-Path -Parent $path
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    [System.IO.File]::WriteAllText($path, $Content)
    $log.Add("$Description ($RelativePath)")
}

switch ($Name) {
    'xml-sdk-notation' {
        Edit-File 'MusicStore.Web\MusicStore.Web.csproj' `
            '<Project Sdk="Microsoft.NET.Sdk.Web">' `
            ("<Project Sdk = 'Microsoft.NET.Sdk.Web'>" + $nl + '<!-- <TargetFramework>net48</TargetFramework><Reference Include="System.Web" /> -->') `
            'Equivalent XML quoting and an inert legacy comment'
    }

    'html-entity-nesting' {
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<tr id="row-@item.RecordId">' `
            '<tr id="row&#45;@item.RecordId">' `
            'HTML entity in an equivalent row identifier'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '@item.Count' '<span>@item.Count</span>' `
            'Quantity inside a text-preserving child element'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<td id="cart-total">' `
            '<!-- <td id="cart-total">9999.00</td> --><td id="cart-total">' `
            'Commented markup must not replace the real total'
    }

    'single-quoted-attributes' {
        # 観測される識別子の属性値を、等価な単一引用符へ変える。
        # 引用符の種類は HTML として等価であり、判定に影響させてはならない（docs/quality-spec.md §4.6）。
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<tr id="row-@item.RecordId">' `
            "<tr id='row-@item.RecordId'>" `
            '明細行の id を単一引用符で書く'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<a href="/Store/Details/@item.AlbumId">@item.Album.Title</a>' `
            "<a href='/Store/Details/@item.AlbumId'>@item.Album.Title</a>" `
            'アルバムリンクを単一引用符で書く'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<td id="item-count-@item.RecordId">' `
            "<td id='item-count-@item.RecordId'>" `
            '数量セルの id を単一引用符で書く'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<td id="cart-total">' `
            "<td id='cart-total'>" `
            '合計セルの id を単一引用符で書く'
        Edit-File 'MusicStore.Web\Views\Shared\_Layout.cshtml' `
            '<a href="/ShoppingCart" id="cart-status">' `
            "<a href='/ShoppingCart' id='cart-status'>" `
            'かご件数の id を単一引用符で書く'
    }

    'whitespace-notation' {
        # 属性名と属性値の間の空白・タブ・改行、および属性順を、等価な表記へ変える。
        # 契約は識別子と値であり、空白の表記は判定に影響させてはならない
        # （docs/quality-spec.md §4.6）。観測される値は変えない。
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<tr id="row-@item.RecordId">' `
            ("<tr`t id`n     = `"row-@item.RecordId`">") `
            '明細行の id を = の前後の空白・タブ・改行で書く'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<a href="/Store/Details/@item.AlbumId">@item.Album.Title</a>' `
            "<a href = '/Store/Details/@item.AlbumId'>@item.Album.Title</a>" `
            'アルバムリンクを単一引用符と = の前後の空白で書く'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<td id="item-count-@item.RecordId">' `
            "<td id = `"item-count-@item.RecordId`">" `
            '数量セルの id を = の前後の空白で書く'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<td id="cart-total">' `
            "<td id`t=`"cart-total`">" `
            '合計セルの id をタブで書く'
        Edit-File 'MusicStore.Web\Views\Shared\_Layout.cshtml' `
            '<a href="/ShoppingCart" id="cart-status">' `
            "<a id = 'cart-status' href=`"/ShoppingCart`">" `
            'かご件数の属性順を変え、= の前後に空白を入れる'
    }

    'legacy-comment-mention' {
        # 旧実装への言及を説明コメントにだけ残す。実際の参照・起動はないため、
        # 合格しなければならない（docs/quality-spec.md §7.2）。
        Edit-File 'MusicStore.Web\Program.cs' `
            'var builder = WebApplication.CreateBuilder(args);' `
            ('// Migrated from net48 to net8.0; no legacy process is used.' + $nl + '// MvcMusicStore は旧実装の名前であり、参照も起動もしない。' + $nl + 'var builder = WebApplication.CreateBuilder(args);') `
            '旧実装への言及を説明コメントに残す'
    }

    'legacy-name-kept' {
        # 旧名称を名前空間・アセンブリ名に残したまま移行を完了させる。
        # 名前の一致は旧実装への依存ではない。参照・起動の記述だけを不合格にする
        # （docs/quality-spec.md §7.2）。
        Edit-File 'MusicStore.Web\MusicStore.Web.csproj' `
            '<RootNamespace>MusicStore.Web</RootNamespace>' `
            '<RootNamespace>MvcMusicStore</RootNamespace>' `
            'ルート名前空間に旧名称を使う'
        Edit-File 'MusicStore.Web\MusicStore.Web.csproj' `
            '<AssemblyName>MusicStore.Web</AssemblyName>' `
            '<AssemblyName>MvcMusicStore</AssemblyName>' `
            'アセンブリ名に旧名称を使う'
        Add-File 'MusicStore.Web\LegacyName.cs' `
            @'
namespace MvcMusicStore.Web;

// 旧名称を引き継ぐ。名前は識別子であり、旧実装の呼び出しではない。
internal static class LegacyName
{
    public const string DisplayName = "MVC Music Store";
}
'@ `
            '旧名称の名前空間を宣言する'
    }

    'aspnetcore-launch-profile' {
        Add-File 'MusicStore.Web\Properties\launchSettings.json' `
            @'
{
  "iisSettings": { "iisExpress": { "applicationUrl": "http://localhost:1486", "sslPort": 0 } },
  "profiles": {
    "http": { "commandName": "Project", "applicationUrl": "http://localhost:5270" },
    "IIS Express": { "commandName": "IISExpress", "launchBrowser": true }
  }
}
'@ `
            'Standard ASP.NET Core launch profiles do not call a legacy application'
    }

    'japanese-order-label' {
        Edit-File 'MusicStore.Web\Views\Checkout\Complete.cshtml' `
            '<p>Thanks for your order! Your order number is: <span id="order-number">@Model</span></p>' `
            '<p>ご注文番号： <strong id=''order-number''><span> @Model </span></strong></p>' `
            'Localize the label and nest the order number'
    }

    'order-denied-403' {
        Edit-File 'MusicStore.Web\Controllers\CheckoutController.cs' `
            'return NotFound();' 'return StatusCode(403);' 'Use the other permitted denial status'
    }

    'modern-project-legacy-name' {
        $originalProject = (Resolve-Path -LiteralPath (Join-Path $Out 'MusicStore.Web\MusicStore.Web.csproj')).Path
        # Rename exactly the generated fixture file; never a computed directory tree.
        Rename-Item -LiteralPath $originalProject -NewName 'MvcMusicStore.csproj'
        $log.Add('A modern net8.0 project retains the historical project filename')
    }

    default {
        throw "未知の別表現です: $Name"
    }
}

Write-Host "別表現 '$Name' を $Out に作成しました。"
foreach ($line in $log) {
    Write-Host "  - $line"
}
