using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using MusicStore.Web.Models;

namespace MusicStore.Web.Data;

/// <summary>
/// Seeds the initial catalog exactly once. Seeding is skipped when genres already exist,
/// so an existing database is never destroyed by a restart.
/// </summary>
public static class CatalogSeeder
{
    public static void Seed(MusicStoreContext db, string catalogPath)
    {
        if (db.Genres.Any())
        {
            return;
        }

        using var document = JsonDocument.Parse(File.ReadAllText(catalogPath));
        var root = document.RootElement;

        foreach (var genre in root.GetProperty("genres").EnumerateArray())
        {
            var name = genre.GetString();
            db.Genres.Add(new Genre { Name = name, Description = name });
        }

        db.SaveChanges();

        var genreIds = db.Genres.ToDictionary(g => g.Name, g => g.GenreId);

        var artistNames = new List<string>();
        foreach (var artist in root.GetProperty("artists").EnumerateArray())
        {
            var name = artist.GetString();
            if (!artistNames.Contains(name))
            {
                artistNames.Add(name);
            }
        }

        foreach (var name in artistNames)
        {
            db.Artists.Add(new Artist { Name = name });
        }

        db.SaveChanges();

        var artistIds = db.Artists.ToDictionary(a => a.Name, a => a.ArtistId);

        var albums = new List<Album>();
        foreach (var album in root.GetProperty("albums").EnumerateArray())
        {
            albums.Add(new Album
            {
                Title = album.GetProperty("title").GetString(),
                GenreId = genreIds[album.GetProperty("genre").GetString()],
                ArtistId = artistIds[album.GetProperty("artist").GetString()],
                Price = album.GetProperty("price").GetDecimal(),
                AlbumArtUrl = album.GetProperty("albumArtUrl").GetString(),
            });
        }

        db.Albums.AddRange(albums);
        db.SaveChanges();
    }
}
