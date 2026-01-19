from django.urls import path
from . import views
from . import views_templates

app_name = 'admin_module'

urlpatterns = [
    # ============================================
    # TEMPLATE-BASED VIEWS (HTML Pages)
    # ============================================
    
    # Dashboard
    path('', views_templates.AdminDashboardView.as_view(), name='dashboard'),
    
    # Branches
    path('branches/', views_templates.BranchesListView.as_view(), name='branches'),
    path('branches/<int:branch_id>/', views_templates.BranchDetailView.as_view(), name='branch_detail'),
    
    # Ventes (Sales)
    path('ventes/', views_templates.VentesListView.as_view(), name='ventes'),
    
    # Dépenses (Expenses)
    path('depenses/', views_templates.DepensesListView.as_view(), name='depenses'),
    
    # Carburants (Fuel/Stock)
    path('carburants/', views_templates.CarburantsListView.as_view(), name='carburants'),
    
    # Abonnés (Subscribers)
    path('abonnes/', views_templates.AbonnesListView.as_view(), name='abonnes'),
    path('abonnes/<int:abonne_id>/', views_templates.AbonneDetailView.as_view(), name='abonne_detail'),
    
    # Utilisateurs (Users)
    path('utilisateurs/', views_templates.UtilisateursListView.as_view(), name='utilisateurs'),
    
    # Documents
    path('documents/', views_templates.DocumentsListView.as_view(), name='documents'),
    
    # Forex
    path('forex/', views_templates.ForexView.as_view(), name='forex'),
    
    # Rapports (Reports)
    path('rapports/', views_templates.RapportsView.as_view(), name='rapports'),
    
    # Notifications
    path('notifications/', views_templates.NotificationsView.as_view(), name='notifications_page'),
    
    # Salaires (Payroll)
    path('salaires/', views_templates.SalairesView.as_view(), name='salaires'),
    
    # Paramètres (Settings)
    path('parametres/', views_templates.ParametresView.as_view(), name='parametres'),
    
    # ============================================
    # API ENDPOINTS (JSON responses)
    # ============================================
    
    # Dashboard API
    path('api/stats/', views.DashboardStatsAPIView.as_view(), name='dashboard_stats'),
    
    # Forex & Exchange Rate Management
    path('api/forex/analysis/', views.ForexAnalysisView.as_view(), name='forex_analysis'),
    path('api/forex/update-rate/', views.UpdateExchangeRateView.as_view(), name='update_exchange_rate'),
    path('api/forex/history/', views.ExchangeRateHistoryView.as_view(), name='exchange_rate_history'),
    
    # Sales Management
    path('api/ventes/manquants/', views.MissingsSalesView.as_view(), name='missing_sales'),
    
    # Stock Management
    path('api/stock/', views.GlobalStockView.as_view(), name='global_stock'),
    path('api/stock/alerts/', views.StockAlertsView.as_view(), name='stock_alerts'),
    
    # Abonnés API
    path('api/abonnes/', views.AbonnesListView.as_view(), name='api_abonnes_list'),
    path('api/abonnes/create/', views.CreateAbonneView.as_view(), name='create_abonne'),
    path('api/abonnes/<int:abonne_id>/update/', views.UpdateAbonneView.as_view(), name='update_abonne'),
    path('api/abonnes/<int:abonne_id>/global-history/', views.AbonneGlobalHistoryView.as_view(), name='abonne_global_history'),
    
    # Document API
    path('api/documents/categories/create/', views.CreateDocumentCategoryView.as_view(), name='create_document_category'),
    path('api/documents/<int:document_id>/visibility/', views.UpdateDocumentVisibilityView.as_view(), name='update_document_visibility'),
    
    # System Settings
    path('api/settings/', views.SystemSettingsView.as_view(), name='system_settings'),
    path('api/settings/update/', views.UpdateSystemSettingsView.as_view(), name='update_settings'),
    
    # Reports API
    path('api/reports/financial/', views.FinancialReportView.as_view(), name='financial_report'),
    path('api/reports/performance/', views.PerformanceReportView.as_view(), name='performance_report'),
    path('api/reports/audit/', views.AuditReportView.as_view(), name='audit_report'),
    
    # Export
    path('api/export/pdf/<str:report_type>/', views.ExportPDFReportView.as_view(), name='export_pdf'),
    path('api/export/excel/<str:report_type>/', views.ExportExcelReportView.as_view(), name='export_excel'),
]