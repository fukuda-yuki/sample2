using System.Globalization;
using System.Text;

namespace MusicStore.Minimal;

/// <summary>
/// HTML を文字列で組み立てる。ビューエンジンを使わない点が正例フィクスチャとの
/// 構造上の違い。ただし外部から観測できる識別子（cart-status / row-* /
/// item-count-* / cart-total / RemoveLink の data-id / 完了画面の文言）は
/// 移行契約なので維持する。
/// </summary>
public static class Pages
{
    public static string Layout(string title, string body, int cartCount, IEnumerable<string> genres)
    {
        var html = new StringBuilder();
        html.Append("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\" />\n");
        html.Append("<title>").Append(Escape(title)).Append("</title>\n</head>\n<body>\n");
        html.Append("<header id=\"header\">\n<h1><a href=\"/\">Music Store</a></h1>\n<nav><ul id=\"navlist\">\n");
        html.Append("<li><a href=\"/\" id=\"current\">Home</a></li>\n");
        html.Append("<li><a href=\"/Store\">Store</a></li>\n");
        html.Append("<li><a href=\"/ShoppingCart\" id=\"cart-status\">Cart (").Append(cartCount.ToString(CultureInfo.InvariantCulture)).Append(")</a></li>\n");
        html.Append("</ul></nav>\n</header>\n");
        html.Append("<aside id=\"categories\">\n<ul id=\"genre-menu\">\n");
        foreach (var genre in genres)
        {
            html.Append("<li><a href=\"/Store/Browse?genre=").Append(Uri.EscapeDataString(genre)).Append("\">").Append(Escape(genre)).Append("</a></li>\n");
        }

        html.Append("</ul>\n</aside>\n<main id=\"main\">\n").Append(body).Append("\n</main>\n");
        html.Append("<footer id=\"footer\">migrated sample</footer>\n</body>\n</html>\n");
        return html.ToString();
    }

    public static string AlbumList(IEnumerable<Album> albums)
    {
        var html = new StringBuilder();
        html.Append("<ul id=\"album-list\">\n");
        foreach (var album in albums)
        {
            html.Append("<li><a href=\"/Store/Details/").Append(album.AlbumId.ToString(CultureInfo.InvariantCulture)).Append("\">");
            html.Append("<span>").Append(Escape(album.Title)).Append("</span></a></li>\n");
        }

        html.Append("</ul>\n");
        return html.ToString();
    }

    public static string GenreList(IEnumerable<string> genres)
    {
        var list = genres.ToList();
        var html = new StringBuilder();
        html.Append("<h3>Browse Genres</h3>\n<p>Select from ").Append(list.Count.ToString(CultureInfo.InvariantCulture)).Append(" genres:</p>\n<ul id=\"genre-list\">\n");
        foreach (var genre in list)
        {
            html.Append("<li><a href=\"/Store/Browse?genre=").Append(Uri.EscapeDataString(genre)).Append("\">").Append(Escape(genre)).Append("</a></li>\n");
        }

        html.Append("</ul>\n");
        return html.ToString();
    }

    public static string Browse(string genre, IEnumerable<Album> albums)
    {
        var html = new StringBuilder();
        html.Append("<h3><em>").Append(Escape(genre)).Append("</em> Albums</h3>\n");
        html.Append(AlbumList(albums));
        return html.ToString();
    }

    public static string Details(Album album)
    {
        var html = new StringBuilder();
        html.Append("<h2>").Append(Escape(album.Title)).Append("</h2>\n");
        html.Append("<div id=\"album-details\">\n");
        html.Append("<p><em>Genre:</em> ").Append(Escape(album.Genre)).Append("</p>\n");
        html.Append("<p><em>Artist:</em> ").Append(Escape(album.Artist)).Append("</p>\n");
        html.Append("<p><em>Price:</em> ").Append(Store.Money(album.Price)).Append("</p>\n");
        html.Append("<p class=\"button\"><a href=\"/ShoppingCart/AddToCart/").Append(album.AlbumId.ToString(CultureInfo.InvariantCulture)).Append("\">Add to cart</a></p>\n");
        html.Append("</div>\n");
        return html.ToString();
    }

    public static string Cart(IEnumerable<CartLine> lines, decimal total)
    {
        var list = lines.ToList();
        var html = new StringBuilder();
        html.Append("<h3>Review your cart:</h3>\n");
        html.Append("<p class=\"button\"><a href=\"/Checkout/AddressAndPayment\">Checkout &gt;&gt;</a></p>\n");
        html.Append("<div id=\"update-message\"></div>\n<table id=\"cart-table\">\n");
        html.Append("<tr><th>Album Name</th><th>Price (each)</th><th>Quantity</th><th></th></tr>\n");
        foreach (var line in list)
        {
            var id = line.RecordId.ToString(CultureInfo.InvariantCulture);
            html.Append("<tr id=\"row-").Append(id).Append("\">\n");
            html.Append("<td><a href=\"/Store/Details/").Append(line.AlbumId.ToString(CultureInfo.InvariantCulture)).Append("\">").Append(Escape(line.Title)).Append("</a></td>\n");
            html.Append("<td>").Append(Store.Money(line.Price)).Append("</td>\n");
            html.Append("<td id=\"item-count-").Append(id).Append("\">").Append(line.Count.ToString(CultureInfo.InvariantCulture)).Append("</td>\n");
            html.Append("<td><a href=\"#\" class=\"RemoveLink\" data-id=\"").Append(id).Append("\">Remove from cart</a></td>\n");
            html.Append("</tr>\n");
        }

        html.Append("<tr><td>Total</td><td></td><td></td><td id=\"cart-total\">").Append(Store.Money(total)).Append("</td></tr>\n");
        html.Append("</table>\n");
        return html.ToString();
    }

    public static string CheckoutForm(IDictionary<string, string> values, string error)
    {
        var html = new StringBuilder();
        html.Append("<h2>Address And Payment</h2>\n");
        if (!string.IsNullOrEmpty(error))
        {
            html.Append("<div id=\"validation-summary\">").Append(Escape(error)).Append("</div>\n");
        }

        html.Append("<form action=\"/Checkout/AddressAndPayment\" method=\"post\">\n<fieldset>\n<legend>Shipping Information</legend>\n");
        foreach (var name in new[] { "FirstName", "LastName", "Address", "City", "State", "PostalCode", "Country", "Phone", "Email" })
        {
            var value = values != null && values.TryGetValue(name, out var current) ? current : string.Empty;
            html.Append("<div class=\"editor-label\"><label for=\"").Append(name).Append("\">").Append(name).Append("</label></div>\n");
            html.Append("<div class=\"editor-field\"><input id=\"").Append(name).Append("\" name=\"").Append(name).Append("\" type=\"text\" value=\"").Append(Escape(value)).Append("\" /></div>\n");
        }

        html.Append("</fieldset>\n<fieldset>\n<legend>Payment</legend>\n");
        html.Append("<p>We're running a promotion: all music is free with the promo code: \"FREE\"</p>\n");
        html.Append("<div class=\"editor-label\"><label for=\"PromoCode\">Promo Code</label></div>\n");
        html.Append("<div class=\"editor-field\"><input id=\"PromoCode\" name=\"PromoCode\" type=\"text\" value=\"\" /></div>\n");
        html.Append("</fieldset>\n<input type=\"submit\" value=\"Submit Order\" />\n</form>\n");
        return html.ToString();
    }

    public static string Complete(int orderId) =>
        "<h2>Checkout Complete</h2>\n<p>Thanks for your order! Your order number is: <span id='order-number'>" +
        orderId.ToString(CultureInfo.InvariantCulture) + "</span></p>\n";

    public static string Error(string message) =>
        "<h2>Error</h2>\n<p>" + Escape(message) + "</p>\n";

    public static string Escape(string value) => string.IsNullOrEmpty(value)
        ? string.Empty
        : value.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
}
