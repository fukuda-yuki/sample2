using Microsoft.EntityFrameworkCore;
using MusicStore.Web.Models;

namespace MusicStore.Web.Data;

public class MusicStoreContext : DbContext
{
    public MusicStoreContext(DbContextOptions<MusicStoreContext> options) : base(options)
    {
    }

    public DbSet<Album> Albums { get; set; }

    public DbSet<Genre> Genres { get; set; }

    public DbSet<Artist> Artists { get; set; }

    public DbSet<Cart> Carts { get; set; }

    public DbSet<Order> Orders { get; set; }

    public DbSet<OrderDetail> OrderDetails { get; set; }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Genre>().Property(g => g.Name).IsRequired();
        modelBuilder.Entity<Album>().Property(a => a.Title).IsRequired();
        modelBuilder.Entity<Album>().Property(a => a.Price).HasColumnType("decimal(18,2)");
        modelBuilder.Entity<Cart>().Property(c => c.CartId).IsRequired();

        // CartId は <型名>Id 規約に一致するため、明示しないと主キーに選ばれてしまい
        // 1 かご 1 行しか持てなくなる。旧実装と同じく RecordId を主キーにする。
        modelBuilder.Entity<Cart>().HasKey(c => c.RecordId);
        modelBuilder.Entity<Cart>().Property(c => c.RecordId).ValueGeneratedOnAdd();
        modelBuilder.Entity<Order>().Property(o => o.Total).HasColumnType("decimal(18,2)");
        modelBuilder.Entity<OrderDetail>().Property(d => d.UnitPrice).HasColumnType("decimal(18,2)");

        modelBuilder.Entity<Cart>()
            .HasOne(c => c.Album)
            .WithMany()
            .HasForeignKey(c => c.AlbumId);

        modelBuilder.Entity<Album>()
            .HasOne(a => a.Genre)
            .WithMany(g => g.Albums)
            .HasForeignKey(a => a.GenreId);

        modelBuilder.Entity<Album>()
            .HasOne(a => a.Artist)
            .WithMany(x => x.Albums)
            .HasForeignKey(a => a.ArtistId);

        modelBuilder.Entity<OrderDetail>()
            .HasOne(d => d.Order)
            .WithMany()
            .HasForeignKey(d => d.OrderId);

        modelBuilder.Entity<OrderDetail>()
            .HasOne(d => d.Album)
            .WithMany()
            .HasForeignKey(d => d.AlbumId);
    }
}
