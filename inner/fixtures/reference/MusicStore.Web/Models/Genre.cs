using System.Collections.Generic;

namespace MusicStore.Web.Models;

public class Genre
{
    public int GenreId { get; set; }

    public string Name { get; set; }

    public string Description { get; set; }

    public List<Album> Albums { get; set; } = new List<Album>();
}
