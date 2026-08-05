"""
Reconciliation layer models — ReconciliationReport, PaymentModeBreakdown.

LLD reference: §1 Data Models (reconciliation cluster).
"""

from django.db import models

from .billing import PaymentMode


class ReconciliationReport(models.Model):
    """
    LLD: ReconciliationReport — clinic-level daily financial summary.

    Fields map to LLD:
      clinic_id               → clinicId
      report_date             → reportDate
      total_billed_paise      → totalBilledPaise
      total_collected_paise   → totalCollectedPaise
      total_outstanding_paise → totalOutstandingPaise
      total_refunds_paise     → totalRefundsPaise
      visit_count             → visitCount
      refund_count            → refundCount
    """

    clinic_id = models.CharField(max_length=100)
    report_date = models.DateField()
    total_billed_paise = models.IntegerField()
    total_collected_paise = models.IntegerField()
    total_outstanding_paise = models.IntegerField()
    total_refunds_paise = models.IntegerField()
    visit_count = models.PositiveIntegerField()
    refund_count = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("clinic_id", "report_date")
        ordering = ["-report_date"]

    def __str__(self) -> str:
        return f"ReconciliationReport(clinic={self.clinic_id}, date={self.report_date})"


class PaymentModeBreakdown(models.Model):
    """
    LLD: PaymentModeBreakdown — per-payment-mode totals within a report.

    Fields map to LLD:
      mode              → mode
      billed_paise      → billedPaise
      collected_paise   → collectedPaise
      outstanding_paise → outstandingPaise
      refunds_paise     → refundsPaise
    """

    report = models.ForeignKey(
        ReconciliationReport,
        on_delete=models.CASCADE,
        related_name="by_payment_mode",
    )
    mode = models.CharField(max_length=10, choices=PaymentMode)
    billed_paise = models.IntegerField()
    collected_paise = models.IntegerField()
    outstanding_paise = models.IntegerField()
    refunds_paise = models.IntegerField()

    def __str__(self) -> str:
        return f"PaymentModeBreakdown({self.mode}, report={self.report_id})"
