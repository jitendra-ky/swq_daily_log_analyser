"""
Analytics layer models — AnalyticsReport, HourlyRevenue, MedicineRankEntry.

LLD reference: §1 Data Models (analytics cluster).
"""

from django.db import models


class AnalyticsReport(models.Model):
    """
    LLD: AnalyticsReport — clinic-level daily analytics summary.

    Revenue-by-hour and medicine rankings are stored as related rows
    (HourlyRevenue, MedicineRankEntry) rather than JSON blobs so they
    remain queryable.

    Fields map to LLD:
      clinic_id   → clinicId
      report_date → reportDate
    """

    clinic_id = models.CharField(max_length=100)
    report_date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("clinic_id", "report_date")
        ordering = ["-report_date"]

    def __str__(self) -> str:
        return f"AnalyticsReport(clinic={self.clinic_id}, date={self.report_date})"


class HourlyRevenue(models.Model):
    """
    LLD: HourlyRevenue — revenue for one hour of the day.

    Fields map to LLD:
      hour          → hour   (0–23)
      revenue_paise → revenuePaise
    """

    analytics_report = models.ForeignKey(
        AnalyticsReport,
        on_delete=models.CASCADE,
        related_name="revenue_by_hour",
    )
    # 0–23 representing the hour of day
    hour = models.PositiveSmallIntegerField()
    revenue_paise = models.IntegerField()

    class Meta:
        ordering = ["hour"]
        unique_together = ("analytics_report", "hour")

    def __str__(self) -> str:
        return f"HourlyRevenue(hour={self.hour}, revenue={self.revenue_paise})"


class MedicineRankEntry(models.Model):
    """
    LLD: MedicineRankEntry — a drug's position in a ranked list.

    Both top-by-quantity and top-by-revenue rankings are stored in this
    single table, differentiated by rank_type. This maps to LLD's:
      topByQuantity → rank_type="qty"
      topByRevenue  → rank_type="revenue"

    Fields map to LLD:
      drug_name → drugName
      value     → value
      rank      → rank
    """

    RANK_TYPE_QUANTITY = "qty"
    RANK_TYPE_REVENUE = "revenue"
    RANK_TYPE_CHOICES = [
        (RANK_TYPE_QUANTITY, "By Quantity"),
        (RANK_TYPE_REVENUE, "By Revenue"),
    ]

    analytics_report = models.ForeignKey(
        AnalyticsReport,
        on_delete=models.CASCADE,
        related_name="medicine_ranks",
    )
    rank_type = models.CharField(max_length=10, choices=RANK_TYPE_CHOICES)
    drug_name = models.CharField(max_length=200)
    value = models.IntegerField()
    rank = models.PositiveIntegerField()

    class Meta:
        ordering = ["rank_type", "rank"]
        unique_together = ("analytics_report", "rank_type", "rank")

    def __str__(self) -> str:
        return (
            f"MedicineRankEntry({self.rank_type}, "
            f"rank={self.rank}, drug={self.drug_name})"
        )
