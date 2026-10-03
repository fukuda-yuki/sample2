"""Prepare the declared finite case corpus without editing source/task originals."""
import argparse
import json
from pathlib import Path
import shutil


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--task-outputs', type=Path, required=True)
    p.add_argument('--task-assets', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    ignore = shutil.ignore_patterns('bin','obj','.git')
    for variant in ('A','B'):
        shutil.copytree(args.task_assets/f'MS1-CONT-{variant}/evaluation',out/'assets'/variant)
        shutil.copytree(args.task_outputs/f'reference-{variant}',out/f'minimal-{variant}',ignore=ignore)
    shutil.copytree(args.task_outputs/'fixed-A-on-B',out/'withheld-wrong-pricing-B',ignore=ignore)
    shutil.copytree(repo/'inner/fixtures/reference',out/'mvc-A',ignore=ignore)
    view = out/'mvc-A/MusicStore.Web/Views/ShoppingCart/Index.cshtml'
    text = view.read_text(encoding='utf-8')
    text = text.replace('<a href="#" class="RemoveLink" data-id="@item.RecordId">Remove from cart</a>',
        '<button type="button" data-id="@item.RecordId">Remove from cart</button>')
    text += '''
<script>
document.querySelectorAll('button[data-id]').forEach(button => {
  button.addEventListener('click', async () => {
    const id = button.dataset.id;
    const response = await fetch('/ShoppingCart/RemoveFromCart', {
      method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({id})
    });
    const data = await response.json();
    const count = data.itemCount ?? data.ItemCount;
    if (count === 0) document.getElementById('row-' + id).remove();
    else document.getElementById('item-count-' + id).textContent = count;
    document.getElementById('cart-total').textContent = Number(data.cartTotal ?? data.CartTotal).toFixed(2);
    document.getElementById('cart-status').textContent = 'Cart (' + (data.cartCount ?? data.CartCount) + ')';
  });
});
</script>
'''
    view.write_bytes(text.replace('\r\n','\n').encode('utf-8'))
    for name in ('history-delete-A','broken-ui-A','unsupported-control-A'):
        shutil.copytree(out/'minimal-A',out/name)
    program = out/'history-delete-A/MusicStore.Continuity/Program.cs'
    text = program.read_text(encoding='utf-8').replace('app.UseSession();','''
using (var history = new Microsoft.Data.Sqlite.SqliteConnection(connection))
{
    history.Open();
    using var deletion = history.CreateCommand();
    deletion.CommandText = "DELETE FROM OrderDetails WHERE OrderId=7001; DELETE FROM Orders WHERE OrderId=7001";
    deletion.ExecuteNonQuery();
}
app.UseSession();
''')
    program.write_bytes(text.replace('\r\n','\n').encode('utf-8'))
    pages = out/'broken-ui-A/MusicStore.Continuity/Pages.cs'
    pages.write_bytes(pages.read_text(encoding='utf-8').replace("link.addEventListener('click'", "link.addEventListener('obsolete-click'").replace('\r\n','\n').encode('utf-8'))
    pages = out/'unsupported-control-A/MusicStore.Continuity/Pages.cs'
    pages.write_bytes(pages.read_text(encoding='utf-8').replace('RemoveLink','AdjustWidget').replace('Remove from cart','Adjust').replace('\r\n','\n').encode('utf-8'))
    def case(name,variant,artifact,verdict,state='scored',operation='complete',fault=None):
        return {'name':name,'variant':variant,'artifact_path':str(out/artifact),
            'expected':{'verdict':verdict,'scoring_state':state,'operation_status':operation,
                        'aggregate_verdict':verdict if verdict!='blocked' else None},
            **({'fault':fault} if fault else {})}
    cases = [
        case('allowed-minimal-A','A','minimal-A','pass'),
        case('allowed-mvc-button-A','A','mvc-A','pass'),
        case('withheld-allowed-B','B','minimal-B','pass'),
        case('withheld-wrong-pricing-B','B','withheld-wrong-pricing-B','fail_critical'),
        case('critical-history-delete-A','A','history-delete-A','fail_critical'),
        case('defect-browser-update-A','A','broken-ui-A','fail'),
        case('unsupported-control-A','A','unsupported-control-A','blocked','evaluation_incomplete','evaluation_incomplete'),
        case('collector-fault-known-failure-A','A','history-delete-A','fail_critical','evaluator_fault','evaluation_incomplete','collector_unavailable'),
        case('cleanup-fault-known-failure-A','A','history-delete-A','fail_critical','scored','cleanup_failed','cleanup_receipt_failure'),
    ]
    (out/'cases.json').write_bytes((json.dumps(cases,indent=2)+'\n').encode('utf-8'))
    print(out/'cases.json')


if __name__ == '__main__': main()
