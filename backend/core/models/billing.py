"""
Billing layer models — BillingRecord, LineItem, ValidationError.

LLD reference: §1 Data Models (billing cluster).
"""

from django.db import models


class PaymentMode(models.TextChoices):
    """LLD: PaymentMode enumeration — CASH | CARD | UPI."""

    CASH = "CASH", "Cash"
    CARD = "CARD", "Card"
    UPI = "UPI", "UPI"


class BillingRecord(models.Model):
    """
    LLD: BillingRecord — one patient visit / billing event.

    Fields map to LLD:
      clinic_id         → clinicId
      visit_id          → visitId
      timestamp         → timestamp
      doctor_id         → doctorId
      payment_mode      → paymentMode
      amount_paid_paise → amountPaidPaise  (negative when is_refund=True)
      discount_paise    → discountPaise
      is_refund         → isRefund
    """

    clinic_id = models.CharField(max_length=100, db_index=True)
    visit_id = models.CharField(max_length=100, unique=True)
    timestamp = models.DateTimeField()
    doctor_id = models.CharField(max_length=100, db_index=True)
    payment_mode = models.CharField(max_length=10, choices=PaymentMode)
    # Signed integer — negative for refunds (LLD §1 design note)
    amount_paid_paise = models.IntegerField()
    discount_paise = models.IntegerField(default=0)
    is_refund = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["clinic_id", "timestamp"]),
        ]

    def gross_billed_paise(self) -> int:
        """LLD: grossBilledPaise() — sum of all line item totals."""
        return sum(item.line_total_paise() for item in self.line_items.all())

    def __str__(self) -> str:
        return f"BillingRecord(visit={self.visit_id}, clinic={self.clinic_id})"


class LineItem(models.Model):
    """
    LLD: LineItem — one drug dispensed on a billing record.

    Fields map to LLD:
      drug_name        → drugName
      qty              → qty
      unit_price_paise → unitPricePaise
    """

    billing_record = models.ForeignKey(
        BillingRecord,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    drug_name = models.CharField(max_length=200)
    qty = models.PositiveIntegerField()
    # Stored as integer paise — never float (LLD §1 design constraint)
    unit_price_paise = models.IntegerField()

    def line_total_paise(self) -> int:
        """LLD: lineTotalPaise() = qty × unit_price_paise."""
        return self.qty * self.unit_price_paise

    def __str__(self) -> str:
        return f"LineItem({self.drug_name} ×{self.qty})"


class ValidationError(models.Model):
    """
    LLD: ValidationError — a single row-level parse failure.

    Stored for audit: every bad row in every upload is persisted so the
    clinic can review exactly which rows were rejected and why.

    Fields map to LLD:
      row_ref   → rowRef
      field     → field
      reason    → reason
      raw_value → rawValue

    Extra field:
      upload_batch — groups all errors from one log-file upload together.
    """

    upload_batch = models.CharField(max_length=100, db_index=True)
    row_ref = models.CharField(max_length=50)
    field = models.CharField(max_length=100)
    reason = models.TextField()
    raw_value = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["upload_batch", "row_ref"]

    def __str__(self) -> str:
        return (
            f"ValidationError(batch={self.upload_batch}, "
            f"row={self.row_ref}, field={self.field})"
        )
