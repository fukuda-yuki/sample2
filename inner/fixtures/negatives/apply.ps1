<#
.SYNOPSIS
  正例フィクスチャに既知の誤りを 1 つだけ重ねて負例を作る。

.DESCRIPTION
  負例は成果物そのものではなく「正例 + 差分」として表現する。差分は文字列の
  置換で与え、置換対象が見つからなければエラーで止める。正例が変わって差分が
  当たらなくなった状態を、静かに「何も壊れていない負例」として通さないため。

.EXAMPLE
  ./apply.ps1 -Name remove-count-pre-decrement -Out ../../runs/neg-001/artifact
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
    'remove-count-pre-decrement' {
        # 数量 2 からの削除で「減らす前」の数量を返す。R-014 の ItemCount が 2 になり不合格になる。
        Edit-File 'MusicStore.Web\Controllers\ShoppingCartController.cs' `
            ('                item.Count--;' + $nl + '                remaining = item.Count;') `
            ('                remaining = item.Count;' + $nl + '                item.Count--;') `
            '削除応答の数量を減算前に読む'
    }

    'no-quantity-multiply' {
        # かご合計で数量を掛けない。R-013 R-014 R-015 R-016 の金額がずれて不合格になる。
        Edit-File 'MusicStore.Web\Services\CartService.cs' `
            'return GetCartItems().Sum(item => item.Count * item.Album.Price);' `
            'return GetCartItems().Sum(item => item.Album.Price);' `
            'かご合計で数量を掛けない'
    }

    'duplicate-cart-lines' {
        # 同じアルバムでも常に新しい明細を足す。R-012 R-013 が不合格になる。
        Edit-File 'MusicStore.Web\Controllers\ShoppingCartController.cs' `
            'var existing = db.Carts.SingleOrDefault(c => c.CartId == cartId && c.AlbumId == id);' `
            'Cart existing = null;' `
            '既存明細の探索をやめて常に追加する'
    }

    'no-seed' {
        # 初期カタログを投入しない。R-002 を筆頭に閲覧・かご・注文の要件が連鎖して不合格になる。
        Edit-File 'MusicStore.Web\Program.cs' `
            'CatalogSeeder.Seed(db, catalogPath);' `
            '_ = catalogPath;' `
            '初期カタログの投入をやめる'
    }

    'destructive-seed' {
        # 起動のたびに DB を作り直す。R-005 が不合格になる（注文が保持されない）。
        Edit-File 'MusicStore.Web\Program.cs' `
            'db.Database.EnsureCreated();' `
            ('db.Database.EnsureDeleted();' + $nl + '    db.Database.EnsureCreated();') `
            '起動のたびに DB を作り直す'
    }

    'unknown-album-500' {
        # 存在しないアルバムを 404 ではなくビューへ渡す。R-009 が不合格になる（500 を返す）。
        Edit-File 'MusicStore.Web\Controllers\StoreController.cs' `
            'if (album == null)' `
            'if (false && album == null)' `
            '存在しないアルバムを 404 にしない'
    }

    'compile-error' {
        # 成果物に構文エラーを入れる。publish が失敗して R-001 が不合格になる。
        # 起動できないために観測できない要件は「未評価（blocked）」であり、
        # 評価器の故障（error）にしてはならない（docs/quality-spec.md §4.1）。
        Add-File 'MusicStore.Web\BrokenSyntax.cs' `
            @'
namespace MusicStore.Web;

// 校正用: わざと構文エラーを含む。
internal static class BrokenSyntax
{
    public static int Value => ;
}
'@ `
            '成果物に構文エラーを入れる'
    }

    'wipe-orders-only' {
            # 再起動のたびに注文だけを消す（カタログは残す）。**期待する判定は fail_critical である。**
            # 注文番号は AUTOINCREMENT で増えるため再起動後の番号は変わるが、再起動前の注文は
            # 消えている。保存契約の Orders 表で再起動前の注文行を観測するため、R-005 が不合格に
            # なる（docs/quality-spec.md §7.3）。
            Edit-File 'MusicStore.Web\Program.cs' `
                '    db.Database.EnsureCreated();' `
                ('    db.Database.EnsureCreated();' + $nl + '    db.Orders.RemoveRange(db.Orders);' + $nl + '    db.SaveChanges();') `
                '再起動時に注文を消す'
        }

        'whitespace-wrong-quantity' {
        # 空白表記の許容が値の誤りを見逃す検査になってはならない（docs/quality-spec.md §4.6）。
        # 数量セルを = の前後の空白付きで書き、同時に数量の値そのものを誤らせる。
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '<td id="item-count-@item.RecordId">' `
            "<td id = `"item-count-@item.RecordId`">" `
            '数量セルの id を = の前後の空白で書く'
        Edit-File 'MusicStore.Web\Views\ShoppingCart\Index.cshtml' `
            '@item.Count' `
            '@(item.Count + 1)' `
            '明細行の数量を実際と違う値にする'
    }

    'legacy-wrapper' {
        # 旧実装を起動する記述を残す。R-029 が不合格になる（静的な検査のみ）。
        Add-File 'MusicStore.Web\LegacyBridge.cs' `
            @'
namespace MusicStore.Web;

// 移行が終わるまでの暫定ブリッジ。旧実装をそのまま起動して逃げる。
//   iisexpress /path:MvcMusicStore\ /port:1234
//   MvcMusicStore.exe を直接起動する場合もある。
internal static class LegacyBridge
{
    public static string FallbackCommand = "iisexpress /path:MvcMusicStore\\";
}
'@ `
            '旧実装を起動する記述を残す'
    }

    'order-marker-wrong' {
        Edit-File 'MusicStore.Web\Views\Checkout\Complete.cshtml' `
            '<span id="order-number">@Model</span>' '<span id="order-number">@(Model + 1)</span>' 'Display a wrong order ID'
    }

    'order-marker-comment' {
        Edit-File 'MusicStore.Web\Views\Checkout\Complete.cshtml' `
            '<span id="order-number">@Model</span>' '<!-- <span id="order-number">@Model</span> -->' 'Hide the marker in a comment'
    }

    'order-marker-duplicate' {
        Edit-File 'MusicStore.Web\Views\Checkout\Complete.cshtml' `
            '<span id="order-number">@Model</span>' '<span id="order-number">@Model</span><b id="order-number">@(Model + 1)</b>' 'Conflicting order identifiers'
    }

    'other-session-alternate-label' {
        Edit-File 'MusicStore.Web\Controllers\CheckoutController.cs' `
            'return NotFound();' 'return Content("Order ID: " + id);' 'Leak the order through a different label with HTTP 200'
    }

    { $_ -in 'invalid-promo-mutates-cart', 'missing-field-mutates-cart', 'invalid-promo-stores-order', 'missing-field-stores-order' } {
        if ($Name.StartsWith('invalid-promo')) {
            $anchor = '            ModelState.AddModelError("promoCode", "We''re sorry, but the promo code you entered is not valid.");'
        }
        else {
            $anchor = '        if (!ModelState.IsValid)' + $nl + '        {'
        }
        if ($Name.EndsWith('mutates-cart')) {
            $mutation = '            foreach (var item in cart.GetCartItems()) item.Count += 1;' + $nl + '            db.SaveChanges();'
        }
        else {
            $mutation = '            order.Username = cart.CartId;' + $nl + '            order.OrderDate = DateTime.Now;' + $nl + '            db.Orders.Add(order);' + $nl + '            db.SaveChanges();'
        }
        Edit-File 'MusicStore.Web\Controllers\CheckoutController.cs' $anchor ($anchor + $nl + $mutation) $Name
    }

    default {
        throw "未知の負例です: $Name"
    }
}

Write-Host "負例 '$Name' を $Out に作成しました。"
foreach ($line in $log) {
    Write-Host "  - $line"
}
