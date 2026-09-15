using System;
using System.Linq;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using MusicStore.Web.Data;
using MusicStore.Web.Models;
using MusicStore.Web.Services;

namespace MusicStore.Web.Controllers;

public class CheckoutController : Controller
{
    private const string PromoCode = "FREE";

    private readonly MusicStoreContext db;
    private readonly CartService cart;

    public CheckoutController(MusicStoreContext db, CartService cart)
    {
        this.db = db;
        this.cart = cart;
    }

    public IActionResult AddressAndPayment()
    {
        return View(new Order());
    }

    [HttpPost]
    public IActionResult AddressAndPayment(Order order, string promoCode)
    {
        if (!string.Equals(promoCode, PromoCode, StringComparison.OrdinalIgnoreCase))
        {
            ModelState.AddModelError("promoCode", "We're sorry, but the promo code you entered is not valid.");
            return View(order);
        }

        if (!ModelState.IsValid)
        {
            return View(order);
        }

        order.Username = cart.CartId;
        order.OrderDate = DateTime.Now;

        db.Orders.Add(order);
        db.SaveChanges();

        CreateOrder(order);

        return RedirectToAction("Complete", new { id = order.OrderId });
    }

    public IActionResult Complete(int id)
    {
        var isValid = db.Orders.Any(o => o.OrderId == id && o.Username == cart.CartId);
        if (isValid)
        {
            return View(id);
        }

        return View("Error");
    }

    private void CreateOrder(Order order)
    {
        decimal orderTotal = 0;

        foreach (var item in cart.GetCartItems())
        {
            db.OrderDetails.Add(new OrderDetail
            {
                AlbumId = item.AlbumId,
                OrderId = order.OrderId,
                UnitPrice = item.Album.Price,
                Quantity = item.Count,
            });

            orderTotal += item.Count * item.Album.Price;
        }

        db.SaveChanges();

        order.Total = orderTotal;
        db.SaveChanges();

        cart.EmptyCart();
    }
}
