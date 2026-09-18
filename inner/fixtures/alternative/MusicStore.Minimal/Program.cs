using System.Globalization;
using MusicStore.Minimal;

// 移行課題の外部契約だけを共有し、実装方式は正例フィクスチャと意図的に変えている。
//   - コントローラ／ビューを使わず最小 API で経路を直接定義する
//   - EF Core を使わず Microsoft.Data.Sqlite で SQL を直接書く
//   - HTML は文字列で組み立てる
var builder = WebApplication.CreateBuilder(args);

builder.Services.AddDistributedMemoryCache();
builder.Services.AddSession(options =>
{
    options.IdleTimeout = TimeSpan.FromHours(2);
    options.Cookie.HttpOnly = true;
    options.Cookie.IsEssential = true;
});

builder.Services.AddSingleton(new Store(
    builder.Configuration.GetConnectionString("MusicStoreEntities"),
    Path.Combine(builder.Environment.ContentRootPath, "Data", "catalog.json")));

var app = builder.Build();

var store = app.Services.GetRequiredService<Store>();
store.Initialize();

app.UseSession();

static string CartId(HttpContext context)
{
    var id = context.Session.GetString("CartId");
    if (string.IsNullOrEmpty(id))
    {
        id = Guid.NewGuid().ToString();
        context.Session.SetString("CartId", id);
    }

    return id;
}

static IResult Html(HttpContext context, string body, string title = "Music Store")
{
    var store = context.RequestServices.GetRequiredService<Store>();
    var cartCount = Store.Count(store.CartLines(CartId(context)));
    return Results.Content(Pages.Layout(title, body, cartCount, store.Genres), "text/html; charset=utf-8");
}

app.MapGet("/", (HttpContext context) => Html(context, Pages.AlbumList(store.NewestAlbums(6)), "Music Store"));

app.MapGet("/Store", (HttpContext context) => Html(context, Pages.GenreList(store.Genres), "Store"));

app.MapGet("/Store/Browse", (HttpContext context, string genre) =>
{
    if (string.IsNullOrEmpty(genre) || !store.Genres.Contains(genre))
    {
        return Results.NotFound();
    }

    return Html(context, Pages.Browse(genre, store.AlbumsByGenre(genre)), "Browse Albums");
});

app.MapGet("/Store/Details/{id:int}", (HttpContext context, int id) =>
{
    var album = store.FindAlbum(id);
    if (album == null)
    {
        return Results.NotFound();
    }

    return Html(context, Pages.Details(album), "Album - " + album.Title);
});

app.MapGet("/ShoppingCart", (HttpContext context) =>
{
    var lines = store.CartLines(CartId(context));
    return Html(context, Pages.Cart(lines, Store.Total(lines)), "Shopping Cart");
});

app.MapGet("/ShoppingCart/AddToCart/{id:int}", (HttpContext context, int id) =>
{
    if (!store.AddToCart(CartId(context), id))
    {
        return Results.NotFound();
    }

    return Results.Redirect("/ShoppingCart");
});

app.MapPost("/ShoppingCart/RemoveFromCart", async (HttpContext context) =>
{
    var form = await context.Request.ReadFormAsync();
    var recordId = int.TryParse(form["id"], NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed) ? parsed : 0;
    var cartId = CartId(context);
    var remaining = store.RemoveFromCart(cartId, recordId);
    var lines = store.CartLines(cartId);

    return Results.Json(new
    {
        ItemCount = remaining,
        DeleteId = recordId,
        CartTotal = Store.Total(lines),
        CartCount = Store.Count(lines),
        Message = remaining == 0 ? "Removed from cart" : "Quantity decreased",
    });
});

app.MapGet("/Checkout/AddressAndPayment", (HttpContext context) =>
    Html(context, Pages.CheckoutForm(null, null), "Address And Payment"));

app.MapPost("/Checkout/AddressAndPayment", async (HttpContext context) =>
{
    var form = await context.Request.ReadFormAsync();
    var fields = form.ToDictionary(f => f.Key, f => f.Value.ToString(), StringComparer.OrdinalIgnoreCase);

    if (!string.Equals(fields.TryGetValue("PromoCode", out var promo) ? promo : null, "FREE", StringComparison.OrdinalIgnoreCase))
    {
        return Html(context, Pages.CheckoutForm(fields, "We're sorry, but the promo code you entered is not valid."), "Address And Payment");
    }

    if (string.IsNullOrWhiteSpace(fields.TryGetValue("FirstName", out var firstName) ? firstName : null))
    {
        return Html(context, Pages.CheckoutForm(fields, "The FirstName field is required."), "Address And Payment");
    }

    var orderId = store.CreateOrder(CartId(context), fields);
    return Results.Redirect("/Checkout/Complete/" + orderId.ToString(CultureInfo.InvariantCulture));
});

app.MapGet("/Checkout/Complete/{id:int}", (HttpContext context, int id) =>
{
    if (!store.OwnsOrder(CartId(context), id))
    {
        return Results.NotFound();
    }

    return Html(context, Pages.Complete(id), "Checkout Complete");
});

app.Run();
