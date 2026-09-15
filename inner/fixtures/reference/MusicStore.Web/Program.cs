using Microsoft.EntityFrameworkCore;
using MusicStore.Web.Data;
using MusicStore.Web.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllersWithViews();
builder.Services.AddHttpContextAccessor();
builder.Services.AddDistributedMemoryCache();
builder.Services.AddSession(options =>
{
    options.IdleTimeout = TimeSpan.FromHours(2);
    options.Cookie.HttpOnly = true;
    options.Cookie.IsEssential = true;
});

var connectionString = builder.Configuration.GetConnectionString("MusicStoreEntities");
builder.Services.AddDbContext<MusicStoreContext>(options => options.UseSqlite(connectionString));
builder.Services.AddScoped<CartService>();

var app = builder.Build();

using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<MusicStoreContext>();
    db.Database.EnsureCreated();
    var catalogPath = Path.Combine(app.Environment.ContentRootPath, "Data", "catalog.json");
    CatalogSeeder.Seed(db, catalogPath);
}

app.UseStaticFiles();
app.UseRouting();
app.UseSession();
app.MapControllerRoute("default", "{controller=Home}/{action=Index}/{id?}");

app.Run();
