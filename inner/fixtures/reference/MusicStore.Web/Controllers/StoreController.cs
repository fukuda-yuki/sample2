using System.Linq;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using MusicStore.Web.Data;

namespace MusicStore.Web.Controllers;

public class StoreController : Controller
{
    private readonly MusicStoreContext db;

    public StoreController(MusicStoreContext db)
    {
        this.db = db;
    }

    public IActionResult Index()
    {
        var genres = db.Genres.OrderBy(g => g.GenreId).ToList();
        return View(genres);
    }

    public IActionResult Browse(string genre)
    {
        var model = db.Genres
            .Include(g => g.Albums)
            .SingleOrDefault(g => g.Name == genre);

        if (model == null)
        {
            return NotFound();
        }

        return View(model);
    }

    public IActionResult Details(int id)
    {
        var album = db.Albums
            .Include(a => a.Genre)
            .Include(a => a.Artist)
            .SingleOrDefault(a => a.AlbumId == id);

        if (album == null)
        {
            return NotFound();
        }

        return View(album);
    }
}
