using System;
using System.Linq;
using Microsoft.AspNetCore.Mvc;
using MusicStore.Web.Data;
using MusicStore.Web.Models;
using MusicStore.Web.Services;

namespace MusicStore.Web.Controllers;

public class ShoppingCartController : Controller
{
    private readonly MusicStoreContext db;
    private readonly CartService cart;

    public ShoppingCartController(MusicStoreContext db, CartService cart)
    {
        this.db = db;
        this.cart = cart;
    }

    public IActionResult Index()
    {
        ViewBag.CartTotal = cart.GetTotal();
        return View(cart.GetCartItems());
    }

    public IActionResult AddToCart(int id)
    {
        var cartId = cart.CartId;
        var existing = db.Carts.SingleOrDefault(c => c.CartId == cartId && c.AlbumId == id);

        if (existing == null)
        {
            db.Carts.Add(new Cart
            {
                AlbumId = id,
                CartId = cartId,
                Count = 1,
                DateCreated = DateTime.Now,
            });
        }
        else
        {
            existing.Count++;
        }

        db.SaveChanges();

        return RedirectToAction("Index");
    }

    [HttpPost]
    public IActionResult RemoveFromCart(int id)
    {
        var cartId = cart.CartId;
        var item = db.Carts.SingleOrDefault(c => c.RecordId == id && c.CartId == cartId);
        var remaining = 0;

        if (item != null)
        {
            if (item.Count > 1)
            {
                item.Count--;
                remaining = item.Count;
            }
            else
            {
                db.Carts.Remove(item);
                remaining = 0;
            }

            db.SaveChanges();
        }

        var items = cart.GetCartItems();

        return Json(new
        {
            ItemCount = remaining,
            DeleteId = id,
            CartTotal = items.Sum(i => i.Count * i.Album.Price),
            CartCount = items.Sum(i => i.Count),
            Message = remaining == 0 ? "Removed from cart" : "Quantity decreased",
        });
    }
}
