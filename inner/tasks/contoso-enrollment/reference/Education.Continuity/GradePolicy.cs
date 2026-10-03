public static class GradePolicy
{
    static readonly string[] Labels = ["A", "B", "C", "D", "F"];
    public static string Display(int? code) => code.HasValue ? Labels[code.Value] : "No grade";
}
