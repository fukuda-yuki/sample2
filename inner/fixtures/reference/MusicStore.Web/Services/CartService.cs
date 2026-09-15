using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using MusicStore.Web.Data;
using MusicStore.Web.Models;

namespace MusicStore.Web.Services;

/// <summary>
/// Resolves the cart identity from the session, mirroring the legacy HttpContextBase.Session["CartId"].
/// </summary>
public class CartService
{
    private const string CartSessionKey = "CartId";

    private readonly MusicStoreContext db;
    private readonly IHttpContextAccessor httpContextAccessor;

    public CartService(MusicStoreContext db, IHttpContextAccessor httpContextAccessor)
    {
        this.db = db;
        this.httpContextAccessor = httpContextAccessor;
    }

    public string CartId
    {
        get
        {
            var session = httpContextAccessor.HttpContext.Session;
            var id = session.GetString(CartSessionKey);
            if (string.IsNullOrEmpty(id))
            {
                id = Guid.NewGuid().ToString();
                session.SetString(CartSessionKey, id);
            }

            return id;
        }
    }

    public List<Cart> GetCartItems()
    {
        return db.Carts.Include(c => c.Album).Where(c => c.CartId == CartId).ToList();
    }

    public decimal GetTotal()
    {
        return GetCartItems().Sum(item => item.Count * item.Album.Price);
    }

    public int GetCount()
    {
        return db.Carts.Where(c => c.CartId == CartId).Sum(c => (int?)c.Count) ?? 0;
    }

    public void EmptyCart()
    {
        foreach (var item in GetCartItems())
        {
            db.Carts.Remove(item);
        }

        db.SaveChanges();
    }
}
