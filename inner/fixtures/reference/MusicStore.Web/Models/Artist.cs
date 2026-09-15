using System.Collections.Generic;

namespace MusicStore.Web.Models;

public class Artist
{
    public int ArtistId { get; set; }

    public string Name { get; set; }

    public List<Album> Albums { get; set; } = new List<Album>();
}
