from rest_framework import serializers
from .models.reconciliation import ReconciliationReport, PaymentModeBreakdown
from .models.billing import ValidationError
from .models.analytics import AnalyticsReport, HourlyRevenue, MedicineRankEntry
from .models.narrative import NarrativeResult, TracedFigure

class PaymentModeBreakdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentModeBreakdown
        fields = ['mode', 'billed_paise', 'collected_paise', 'outstanding_paise', 'refunds_paise']

class ReconciliationReportSerializer(serializers.ModelSerializer):
    by_payment_mode = PaymentModeBreakdownSerializer(many=True, read_only=True)

    class Meta:
        model = ReconciliationReport
        fields = [
            'clinic_id', 'report_date', 'total_billed_paise', 'total_collected_paise', 
            'total_outstanding_paise', 'total_refunds_paise', 'visit_count', 'refund_count',
            'by_payment_mode'
        ]

class HourlyRevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = HourlyRevenue
        fields = ['hour', 'revenue_paise']

class MedicineRankEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicineRankEntry
        fields = ['rank_type', 'drug_name', 'value', 'rank']

class AnalyticsReportSerializer(serializers.ModelSerializer):
    revenue_by_hour = HourlyRevenueSerializer(many=True, read_only=True)
    medicine_ranks = MedicineRankEntrySerializer(many=True, read_only=True)

    class Meta:
        model = AnalyticsReport
        fields = ['clinic_id', 'report_date', 'revenue_by_hour', 'medicine_ranks']

class TracedFigureSerializer(serializers.ModelSerializer):
    class Meta:
        model = TracedFigure
        fields = ['placeholder', 'display_value', 'source_field']

class ValidationErrorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValidationError
        fields = ['row_ref', 'field', 'reason', 'raw_value']

class NarrativeResultSerializer(serializers.ModelSerializer):
    traced_figures = TracedFigureSerializer(many=True, read_only=True)

    class Meta:
        model = NarrativeResult
        fields = ['text', 'status', 'warnings', 'traced_figures']

class DailyReportResponseSerializer(serializers.Serializer):
    recon_report = ReconciliationReportSerializer(allow_null=True)
    analytics_report = AnalyticsReportSerializer(allow_null=True)
    narrative_result = NarrativeResultSerializer(allow_null=True)
    errors = ValidationErrorSerializer(many=True, required=False, allow_null=True)
    total_rows_processed = serializers.IntegerField(required=False, allow_null=True)
    valid_records_count = serializers.IntegerField(required=False, allow_null=True)
