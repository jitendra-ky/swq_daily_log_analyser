from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import uuid

from django.shortcuts import get_object_or_404
from .models.reconciliation import ReconciliationReport
from .models.analytics import AnalyticsReport
from .models.narrative import NarrativeResult
from .report_orchestrator import ReportOrchestrator
from .serializers import DailyReportResponseSerializer

class GenerateReportAPIView(APIView):
    """
    POST /api/v1/reports/generate/
    Ingests a raw billing log (JSON array), validates it, runs reconciliation,
    analytics, and narrative generation, and returns the combined report.
    """
    def post(self, request, *args, **kwargs):
        raw_rows = request.data
        if not isinstance(raw_rows, list):
            return Response({"error": "Expected a JSON array of billing records."}, status=status.HTTP_400_BAD_REQUEST)
        
        if not raw_rows:
            return Response({"error": "Empty list provided."}, status=status.HTTP_400_BAD_REQUEST)

        # Extract clinic_id from the first row. We assume a single file/upload has one clinic.
        clinic_id = raw_rows[0].get("clinic_id")
        if not clinic_id:
            return Response({"error": "Missing clinic_id in the first record."}, status=status.HTTP_400_BAD_REQUEST)

        batch_id = str(uuid.uuid4())
        
        orchestrator = ReportOrchestrator()
        result = orchestrator.generate_daily_report(clinic_id=clinic_id, raw_rows=raw_rows, batch=batch_id)
        
        serializer = DailyReportResponseSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ReportDetailAPIView(APIView):
    """
    GET /api/v1/reports/<clinic_id>/<date>/
    Retrieves the reports generated for a given clinic and date.
    """
    def get(self, request, clinic_id, date, *args, **kwargs):
        try:
            recon_report = ReconciliationReport.objects.prefetch_related('by_payment_mode').get(
                clinic_id=clinic_id, report_date=date
            )
            analytics_report = AnalyticsReport.objects.prefetch_related(
                'revenue_by_hour', 'medicine_ranks'
            ).get(
                clinic_id=clinic_id, report_date=date
            )
            narrative_result = NarrativeResult.objects.prefetch_related('traced_figures').get(
                recon_report=recon_report
            )
        except ReconciliationReport.DoesNotExist:
            return Response({"error": "Report not found."}, status=status.HTTP_404_NOT_FOUND)
        except AnalyticsReport.DoesNotExist:
            return Response({"error": "Analytics report not found."}, status=status.HTTP_404_NOT_FOUND)
        except NarrativeResult.DoesNotExist:
            return Response({"error": "Narrative result not found."}, status=status.HTTP_404_NOT_FOUND)
        
        data = {
            "recon_report": recon_report,
            "analytics_report": analytics_report,
            "narrative_result": narrative_result,
            "errors": None,
            "total_rows_processed": None,
            "valid_records_count": None,
        }
        
        serializer = DailyReportResponseSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
