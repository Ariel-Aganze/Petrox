# apps/manager_module/urls.py
"""
URL Configuration for Manager Module
Handles both template-based views (HTML pages) and API endpoints (JSON responses)

MANAGER MODULE SCOPE:
- Branch-specific operations only
- Cannot access other branches
- Cannot validate sales (Caissier role)
- Cannot manage users or global settings
"""

from django.urls import path
from . import views

app_name = 'manager_module'

urlpatterns = [
    # ============================================
    # TEMPLATE-BASED VIEWS (HTML Pages)
    # ============================================
    
    # Dashboard
    path('', views.ManagerDashboardView.as_view(), name='dashboard'),
    
    # Sales Management (Ventes)
    path('ventes/', views.VentesListView.as_view(), name='ventes'),
    
    # Stock & Deliveries (Carburants)
    path('carburants/', views.CarburantsView.as_view(), name='carburants'),
    
    # Subscribers (Abonnés)
    path('abonnes/', views.AbonnesView.as_view(), name='abonnes'),
    
    # Shift Planning (Planning)
    path('planning/', views.PlanningView.as_view(), name='planning'),
    
    # Documents
    path('documents/', views.DocumentsView.as_view(), name='documents'),
    
    # Notifications
    path('notifications/', views.NotificationsView.as_view(), name='notifications'),
    
    # Profile
    path('profil/', views.ProfilView.as_view(), name='profil'),
    
    # ============================================
    # API ENDPOINTS (JSON Responses)
    # ============================================
    
    # ---------- Dashboard APIs ----------
    path('api/stats/', views.DashboardStatsAPIView.as_view(), name='dashboard_stats'),
    path('api/chart-data/', views.ChartDataAPIView.as_view(), name='chart_data'),
    path('api/recent-transactions/', views.RecentTransactionsAPIView.as_view(), name='recent_transactions'),
    path('api/forex-impact/', views.ForexImpactAPIView.as_view(), name='forex_impact'),
    
    # ---------- Sales (Ventes) APIs ----------
    path('api/ventes/create/', views.CreateVenteAPIView.as_view(), name='create_vente'),
    path('api/ventes/', views.VentesListAPIView.as_view(), name='ventes_api'),
    path('api/ventes/<int:vente_id>/', views.VenteDetailAPIView.as_view(), name='vente_detail'),
    
    # ---------- Stock & Deliveries APIs ----------
    path('api/stock/', views.StockListAPIView.as_view(), name='stock_api'),
    path('api/deliveries/confirm/', views.ConfirmDeliveryAPIView.as_view(), name='confirm_delivery'),
    path('api/stock/movements/', views.StockMovementsAPIView.as_view(), name='stock_movements'),
    
    # ---------- Subscribers (Abonnés) APIs ----------
    path('api/abonnes/', views.AbonnesListAPIView.as_view(), name='abonnes_api'),
    path('api/abonnes/<int:abonne_id>/', views.AbonneDetailAPIView.as_view(), name='abonne_detail'),
    path('api/abonnes/consumption/', views.RecordConsumptionView.as_view(), name='record_consumption'),  # NEW

    
    # ---------- Planning APIs ----------
    path('api/planning/', views.PlanningAPIView.as_view(), name='planning_api'),
    path('api/planning/assign/', views.AssignShiftAPIView.as_view(), name='assign_shift'),

    # Planning (Shifts) URLs
    path('planning/', views.PlanningView.as_view(), name='planning'),
    path('api/planning/', views.PlanningAPIView.as_view(), name='planning_api'),
    path('api/planning/create/', views.CreateShiftView.as_view(), name='create_shift'),
    path('api/planning/<int:shift_id>/update/', views.UpdateShiftView.as_view(), name='update_shift'),
    path('api/planning/<int:shift_id>/delete/', views.DeleteShiftView.as_view(), name='delete_shift'),

    # Planning & Attendance URLs
    path('planning/', views.PlanningView.as_view(), name='planning'),
    path('api/planning/', views.PlanningAPIView.as_view(), name='planning_api'),
    path('api/planning/create/', views.CreateShiftView.as_view(), name='create_shift'),
    path('api/planning/<int:shift_id>/update/', views.UpdateShiftView.as_view(), name='update_shift'),
    path('api/planning/<int:shift_id>/delete/', views.DeleteShiftView.as_view(), name='delete_shift'),
    path('api/attendance/', views.AttendanceAPIView.as_view(), name='attendance_api'),
    path('api/attendance/mark/', views.MarkAttendanceView.as_view(), name='mark_attendance'),
    path('planning/download/', views.DownloadPlanningView.as_view(), name='download_planning'),
    
    # ---------- Pompistes APIs ----------
    path('api/pompistes/', views.PompistesListAPIView.as_view(), name='pompistes_api'),

    # Documents URLs
    path('documents/', views.DocumentsView.as_view(), name='documents'),
    path('api/documents/', views.DocumentsAPIView.as_view(), name='documents_api'),
    path('api/documents/upload/', views.UploadDocumentView.as_view(), name='upload_document'),
    path('api/documents/<int:document_id>/view/', views.ViewDocumentView.as_view(), name='view_document'),
    path('api/documents/<int:document_id>/download/', views.DownloadDocumentView.as_view(), name='download_document'),
]