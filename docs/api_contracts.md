# EOD Billing & Analytics Agent - REST API Contracts

Base URL: `/api/v1`

## 1. Generate Report
**Endpoint:** `POST /reports/generate/`

Ingests a raw billing log (JSON array), validates it, runs reconciliation, analytics, and narrative generation, and returns the combined report.

### Request Body
A JSON array of billing log records.

```json
[
  {
    "clinic_id": "clinic-1",
    "visit_id": "visit-101",
    "timestamp": "2026-07-27T10:15:00Z",
    "doctor_id": "doc-01",
    "payment_mode": "CARD",
    "amount_paid_paise": 150000,
    "discount_paise": 0,
    "is_refund": false,
    "line_items": [
      {
        "drug_name": "PARACETAMOL",
        "qty": 2,
        "unit_price_paise": 75000
      }
    ]
  }
]
```

### Response: `200 OK`
Returns the aggregated and generated dashboards and narrative summary.

```json
{
  "recon_report": {
    "clinic_id": "clinic-1",
    "report_date": "2026-07-27",
    "total_billed_paise": 150000,
    "total_collected_paise": 150000,
    "total_outstanding_paise": 0,
    "total_refunds_paise": 0,
    "visit_count": 1,
    "refund_count": 0,
    "by_payment_mode": [
      {
        "mode": "CARD",
        "billed_paise": 150000,
        "collected_paise": 150000,
        "outstanding_paise": 0,
        "refunds_paise": 0
      }
    ]
  },
  "analytics_report": {
    "clinic_id": "clinic-1",
    "report_date": "2026-07-27",
    "revenue_by_hour": [
      {
        "hour": 10,
        "revenue_paise": 150000
      }
    ],
    "peak_hour": {
      "hour": 10,
      "revenue_paise": 150000
    },
    "top_by_quantity": [
      {
        "rank_type": "qty",
        "drug_name": "PARACETAMOL",
        "value": 2,
        "rank": 1
      }
    ],
    "top_by_revenue": [
      {
        "rank_type": "revenue",
        "drug_name": "PARACETAMOL",
        "value": 150000,
        "rank": 1
      }
    ]
  },
  "narrative_result": {
    "text": "Good evening! Here is today's summary...",
    "status": "SUCCESS",
    "warnings": [],
    "traced_figures": [
      {
        "placeholder": "total_billed",
        "display_value": "₹1,500",
        "source_field": "ReconciliationReport.total_billed_paise"
      }
    ]
  },
  "errors": [],
  "total_rows_processed": 1,
  "valid_records_count": 1
}
```

### Response: `400 Bad Request`
If the JSON payload is not a list, is empty, or is missing the `clinic_id` in the first record.

---

## 2. Get Report Detail
**Endpoint:** `GET /reports/<clinic_id>/<date>/`

Retrieves a previously generated EOD report for a given clinic and date.

### Path Parameters
- `clinic_id` (string): The clinic identifier (e.g., `clinic-1`).
- `date` (string): The report date in `YYYY-MM-DD` format (e.g., `2026-07-27`).

### Response: `200 OK`
Returns the exact same schema structure as the `POST` response, but `errors`, `total_rows_processed`, and `valid_records_count` will be `null`.

### Response: `404 Not Found`
If a report for the specified `clinic_id` and `date` does not exist.
```json
{
  "error": "Report not found."
}
```
