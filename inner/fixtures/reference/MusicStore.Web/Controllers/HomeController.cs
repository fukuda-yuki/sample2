using System.Linq;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using MusicStore.Web.Data;

namespace MusicStore.Web.Controllers;

public class HomeController : Controller
{
    private readonly MusicStoreContext db;

    public HomeController(MusicStoreContext db)
    {
        this.db = db;
    }

    public IActionResult Index()
    {
        var albums = db.Albums
            .Include(a => a.Genre)
            .Include(a => a.Artist)
            .OrderBy(a => a.AlbumId)
            .Take(5)
            .ToList();

        return View(albums);
    }

    public IActionResult Error()
    {
        return View();
    }
}
