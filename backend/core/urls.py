from django.urls import path
from .views import GenerateReportAPIView, ReportDetailAPIView

urlpatterns = [
    path('reports/generate/', GenerateReportAPIView.as_view(), name='generate-report'),
    path('reports/<str:clinic_id>/<str:date>/', ReportDetailAPIView.as_view(), name='report-detail'),
]
