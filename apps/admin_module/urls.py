# apps/admin_module/urls.py
"""
URL Configuration for Admin Module
Handles both template-based views (HTML pages) and API endpoints (JSON responses)
"""

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
    path('api/dashboard/export/pdf/', views.ExportDashboardPDFView.as_view(), name='export_dashboard_pdf'),
path('api/dashboard/export/excel/', views.ExportDashboardExcelView.as_view(), name='export_dashboard_excel'),
    
    # Branches Management
    path('branches/', views_templates.BranchesListView.as_view(), name='branches'),
    path('branches/<int:branch_id>/', views_templates.BranchDetailView.as_view(), name='branch_detail'),
    
    # Sales (Ventes)
    path('ventes/', views_templates.VentesListView.as_view(), name='ventes'),
    
    # Expenses (Dépenses)
    path('depenses/', views_templates.DepensesListView.as_view(), name='depenses'),
    
    # Fuel/Stock (Carburants)
    path('carburants/', views_templates.CarburantsListView.as_view(), name='carburants'),
    
    # Subscribers (Abonnés)
    path('abonnes/', views_templates.AbonnesListView.as_view(), name='abonnes'),
    path('abonnes/<int:abonne_id>/', views_templates.AbonneDetailView.as_view(), name='abonne_detail'),

    # Export Functions
   path('api/abonnes/export/pdf/', views.ExportAbonnesPDFView.as_view(), name='export_abonnes_pdf'),
   path('api/abonnes/export/excel/', views.ExportAbonnesExcelView.as_view(), name='export_abonnes_excel'),

   #  Payment History
   path('api/abonnes/<int:abonne_id>/payment-history/', views.AbonnePaymentHistoryView.as_view(), name='abonne_payment_history'),
    
    # Users Management (Utilisateurs)
    path('utilisateurs/', views_templates.UtilisateursListView.as_view(), name='utilisateurs'),
    
    # Documents
    path('documents/', views_templates.DocumentsListView.as_view(), name='documents'),
    
    # Forex & Exchange Rates
    path('forex/', views_templates.ForexView.as_view(), name='forex'),
    
    # Reports (Rapports)
    path('rapports/', views_templates.RapportsView.as_view(), name='rapports'),
    
    # Notifications
    path('notifications/', views_templates.NotificationsView.as_view(), name='notifications_page'),
    
    # Payroll (Salaires)
    path('salaires/', views_templates.SalairesView.as_view(), name='salaires'),
    
    # System Settings (Paramètres)
    path('parametres/', views_templates.ParametresView.as_view(), name='parametres'),
    
    # ============================================
    # API ENDPOINTS (JSON Responses)
    # ============================================
    
    # ---------- Dashboard APIs ----------
    path('api/stats/', views.DashboardStatsAPIView.as_view(), name='dashboard_stats'),
    
    # ---------- Branches APIs ----------
    # Branches Template Views
   path('branches/', views_templates.BranchesListView.as_view(), name='branches'),
   path('branches/<int:branch_id>/', views_templates.BranchDetailView.as_view(), name='branch_detail'),
   path('api/branches/<int:branch_id>/history/', views.BranchHistoryView.as_view(), name='branch_history'),
   path('api/branches/comparison/', views.BranchComparisonView.as_view(), name='branch_comparison'),

   # Branches API Views
   path('api/branches/create/', views.CreateBranchView.as_view(), name='create_branch'),
   path('api/branches/<int:branch_id>/', views.BranchDetailAPIView.as_view(), name='branch_detail_api'),
   path('api/branches/<int:branch_id>/update/', views.UpdateBranchView.as_view(), name='update_branch'),
   path('api/branches/<int:branch_id>/toggle-active/', views.ToggleBranchActiveView.as_view(), name='toggle_branch_active'),
   path('api/branches/<int:branch_id>/delete/', views.DeleteBranchView.as_view(), name='delete_branch'),
   path('api/branches/<int:branch_id>/stats/', views.BranchStatsView.as_view(), name='branch_stats'),
   path('api/users/', views.UsersListAPIView.as_view(), name='users_api'),
    
    # # ---------- Sales (Ventes) APIs ----------
    # Ventes Template View
   path('ventes/', views_templates.VentesListView.as_view(), name='ventes'),

   # Ventes API Views
   path('api/ventes/', views.VentesListAPIView.as_view(), name='ventes_api'),
   path('api/ventes/<int:vente_id>/', views.VenteDetailAPIView.as_view(), name='vente_detail_api'),
   path('api/ventes/stats/', views.VentesStatsView.as_view(), name='ventes_stats'),
   path('api/ventes/by-pompiste/', views.SalesByPompisteView.as_view(), name='ventes_by_pompiste'),
   path('api/ventes/manquants/', views.ManquantsReportView.as_view(), name='manquants_report'),

   path('api/ventes/export/pdf/', views.BulkExportSalesPDFView.as_view(), name='bulk_export_sales_pdf'),
   path('api/ventes/export/excel/', views.BulkExportSalesExcelView.as_view(), name='bulk_export_sales_excel'),
   path('api/ventes/<int:vente_id>/print/', views.PrintSaleReceiptView.as_view(), name='print_sale_receipt'),
   path('api/ventes/print/', views.BulkPrintSalesView.as_view(), name='bulk_print_sales'),

   # ---------- Manquants Validation URLs ----------
   path('validation-manquants/', views_templates.ValidationManquantsView.as_view(), name='validation_manquants'),
   path('api/manquants/report/', views.ManquantsReportAPIView.as_view(), name='manquants_report_api'),
   path('api/manquants/export/pdf/', views.ExportManquantsPDFView.as_view(), name='export_manquants_pdf'),
   path('api/manquants/export/excel/', views.ExportManquantsExcelView.as_view(), name='export_manquants_excel'),
    
    # # ---------- Expenses (Dépenses) APIs ----------
    # Dépenses (Expenses) Template View
   path('depenses/', views_templates.DepensesListView.as_view(), name='depenses'),

# Dépenses API Views
   path('api/depenses/', views.DepensesListAPIView.as_view(), name='depenses_api'),
   path('api/depenses/create/', views.CreateDepenseView.as_view(), name='create_depense'),
   path('api/depenses/<int:depense_id>/', views.DepenseDetailAPIView.as_view(), name='depense_detail_api'),
   path('api/depenses/<int:depense_id>/update/', views.UpdateDepenseView.as_view(), name='update_depense'),
   path('api/depenses/<int:depense_id>/delete/', views.DeleteDepenseView.as_view(), name='delete_depense'),
   path('api/depenses/stats/', views.ExpensesStatsView.as_view(), name='expenses_stats'),

   # Add in Dépenses API section:
   # Analytics
   path('api/depenses/analytics/', views.ExpensesAnalyticsAPIView.as_view(), name='expenses_analytics'),

   # Bulk Actions
   path('api/depenses/bulk-delete/', views.BulkDeleteExpensesView.as_view(), name='bulk_delete_expenses'),

   #  Export Functions
   path('api/depenses/export/pdf/', views.BulkExportExpensesPDFView.as_view(), name='bulk_export_expenses_pdf'),
   path('api/depenses/export/excel/', views.BulkExportExpensesExcelView.as_view(), name='bulk_export_expenses_excel'),

   # Print Single Expense
   path('api/depenses/<int:expense_id>/print/', views.PrintExpenseReceiptView.as_view(), name='print_expense_receipt'),

# Categories APIs
   path('api/categories/', views.CategoriesListAPIView.as_view(), name='categories_api'),
   path('api/categories/create/', views.CreateCategoryView.as_view(), name='create_category'),
   path('api/categories/<int:category_id>/update/', views.UpdateCategoryView.as_view(), name='update_category'),
   path('api/categories/<int:category_id>/delete/', views.DeleteCategoryView.as_view(), name='delete_category'),
   path('api/categories/<int:category_id>/approve/', views.ApproveCategoryView.as_view(), name='approve_category'),
   path('api/categories/<int:category_id>/toggle/', views.ToggleCategoryView.as_view(), name='toggle_category'),
    
    # # ---------- Categories APIs ----------
    # path('api/categories/', views.CategoriesListAPIView.as_view(), name='categories_api'),
    # path('api/categories/create/', views.CreateCategoryView.as_view(), name='create_category'),
    # path('api/categories/<int:category_id>/update/', views.UpdateCategoryView.as_view(), name='update_category'),
    # path('api/categories/<int:category_id>/delete/', views.DeleteCategoryView.as_view(), name='delete_category'),
    # path('api/categories/<int:category_id>/approve/', views.ApproveCategoryView.as_view(), name='approve_category'),
    
    # # ---------- Stock & Fuel APIs ----------
    # Fuel Types
   path('carburants/', views_templates.CarburantsListView.as_view(), name='carburants'),
   path('api/fuel-types/', views.FuelTypesListAPIView.as_view(), name='fuel_types_api'),
   path('api/fuel-types/create/', views.CreateFuelTypeView.as_view(), name='create_fuel_type'),
   path('api/fuel-types/<int:fuel_id>/', views.FuelTypeDetailAPIView.as_view(), name='fuel_type_detail_api'),
   path('api/fuel-types/<int:fuel_id>/update/', views.UpdateFuelTypeView.as_view(), name='update_fuel_type'),
   path('api/fuel-types/<int:fuel_id>/toggle-active/', views.ToggleFuelTypeStatusView.as_view(), name='toggle_fuel_type_status'),
   path('api/fuel-types/<int:fuel_id>/stats/', views.FuelTypeStatsView.as_view(), name='fuel_type_stats'),

   # Stock Management URLs
   path('api/stock/', views.StockListAPIView.as_view(), name='stock_api'),
   path('api/stock/create/', views.CreateStockView.as_view(), name='create_stock'), 
   path('api/stock/<int:stock_id>/', views.StockDetailAPIView.as_view(), name='stock_detail_api'),
   path('api/stock/<int:stock_id>/settings/', views.UpdateStockSettingsView.as_view(), name='update_stock_settings'),
   path('api/stock/<int:stock_id>/history/', views.StockHistoryView.as_view(), name='stock_history'),
   path('api/stock/alerts/', views.StockAlertsView.as_view(), name='stock_alerts'),
   path('api/stock/summary/', views.StockSummaryView.as_view(), name='stock_summary'),
    # # ---------- Subscribers (Abonnés) APIs ----------
    # Abonnés Management
   path('abonnes/', views_templates.AbonnesListView.as_view(), name='abonnes'),
   path('api/abonnes/', views.AbonnesListAPIView.as_view(), name='abonnes_api'),
   path('api/abonnes/create/', views.CreateAbonneView.as_view(), name='create_abonne'),
   path('api/abonnes/<int:abonne_id>/', views.AbonneDetailAPIView.as_view(), name='abonne_detail_api'),
   path('api/abonnes/<int:abonne_id>/update/', views.UpdateAbonneView.as_view(), name='update_abonne'),
   path('api/abonnes/<int:abonne_id>/toggle-active/', views.ToggleAbonneStatusView.as_view(), name='toggle_abonne_active'),
   path('api/abonnes/<int:abonne_id>/history/', views.AbonneGlobalHistoryView.as_view(), name='abonne_history'),
   path('api/abonnes/<int:abonne_id>/payment/', views.AddPaymentView.as_view(), name='add_abonne_payment'),
   path('api/abonnes/<int:abonne_id>/stats/', views.AbonneConsumptionStatsView.as_view(), name='abonne_stats'),
   path('api/abonnes/by-type/', views.AbonnesByTypeView.as_view(), name='abonnes_by_type'),
   path('api/payments/create/', views.CreatePaymentView.as_view(), name='create_payment'),
    
    # # ---------- Users Management APIs ----------
    # Utilisateurs Template View
   path('utilisateurs/', views_templates.UtilisateursListView.as_view(), name='utilisateurs'),

# System Users API Views
   path('api/users/', views.UsersListAPIView.as_view(), name='users_api'),  # Already exists
   path('api/users/create/', views.CreateUserView.as_view(), name='create_user'),
   path('api/users/<int:user_id>/', views.UserDetailAPIView.as_view(), name='user_detail_api'),
   path('api/users/<int:user_id>/update/', views.UpdateUserView.as_view(), name='update_user'),
   path('api/users/<int:user_id>/toggle-active/', views.ToggleUserActiveView.as_view(), name='toggle_user_active'),
   path('api/users/<int:user_id>/reset-password/', views.ResetPasswordView.as_view(), name='reset_password'),

   # Pompistes API Views
   path('api/pompistes/', views.PompistesListAPIView.as_view(), name='pompistes_api'),
   path('api/pompistes/create/', views.CreatePompisteView.as_view(), name='create_pompiste'),
   path('api/pompistes/<int:pompiste_id>/', views.PompisteDetailAPIView.as_view(), name='pompiste_detail_api'),
   path('api/pompistes/<int:pompiste_id>/update/', views.UpdatePompisteView.as_view(), name='update_pompiste'),
   path('api/pompistes/<int:pompiste_id>/toggle-active/', views.TogglePompisteActiveView.as_view(), name='toggle_pompiste_active'),
    
    # ---------- Pompistes APIs ----------
    path('api/pompistes/', views.PompistesListAPIView.as_view(), name='pompistes_api'),
    path('api/pompistes/create/', views.CreatePompisteView.as_view(), name='create_pompiste'),
    path('api/pompistes/<int:pompiste_id>/', views.PompisteDetailAPIView.as_view(), name='pompiste_detail_api'),
    path('api/pompistes/<int:pompiste_id>/update/', views.UpdatePompisteView.as_view(), name='update_pompiste'),
    path('api/pompistes/<int:pompiste_id>/delete/', views.DeletePompisteView.as_view(), name='delete_pompiste'),
    path('api/pompistes/<int:pompiste_id>/toggle-active/', views.TogglePompisteActiveView.as_view(), name='toggle_pompiste_active'),
    
    # # ---------- Forex & Exchange Rate APIs ----------
   path('forex/', views_templates.ForexView.as_view(), name='forex'),
   path('api/forex/current/', views.CurrentExchangeRateView.as_view(), name='current_exchange_rate'),
   path('api/forex/update-rate/', views.UpdateExchangeRateView.as_view(), name='update_exchange_rate'),
   path('api/forex/history/', views.ExchangeRateHistoryView.as_view(), name='exchange_rate_history'),
   path('api/forex/analysis/', views.ForexAnalysisView.as_view(), name='forex_analysis'),
   path('api/forex/impact/', views.ForexImpactView.as_view(), name='forex_impact'),
    
    # # ---------- Documents APIs ----------
    # Documents URLs
   path('documents/', views_templates.DocumentsView.as_view(), name='documents'),
   path('api/documents/<int:document_id>/', views.GetDocumentDetailView.as_view(), name='get_document_detail'),
   path('api/documents/<int:document_id>/update/', views.UpdateDocumentView.as_view(), name='update_document'),
   path('api/documents/upload/', views.UploadDocumentView.as_view(), name='upload_document'),
   path('api/documents/<int:document_id>/download/', views.DownloadDocumentView.as_view(), name='download_document'),
   path('api/documents/<int:document_id>/delete/', views.DeleteDocumentView.as_view(), name='delete_document'),
   path('api/documents/categories/create/', views.CreateDocumentCategoryView.as_view(), name='create_document_category'),
   path('api/documents/list/', views.DocumentsListAPIView.as_view(), name='documents_list_api'),
    
    # # ---------- Notifications APIs ----------
    # Notifications URLs
   path('notifications/', views.NotificationsView.as_view(), name='notifications'),
   path('api/notifications/<str:notification_id>/read/', views.MarkNotificationReadView.as_view(), name='mark_notification_read'),
   path('api/notifications/mark-all-read/', views.MarkAllNotificationsReadView.as_view(), name='mark_all_read'),
   path('api/notifications/', views.NotificationsAPIView.as_view(), name='notifications_api'),
   path('api/notifications/count/', views.NotificationCountAPIView.as_view(), name='notification_count'),
    
    # # ---------- Payroll (Salaires) APIs ----------
    # Salaires URLs
   path('salaires/', views_templates.SalairesView.as_view(), name='salaires'),
   path('api/payments/<int:payment_id>/', views.PaymentDetailAPIView.as_view(), name='payment_detail'),
   path('api/payments/history/', views.SalaryHistoryAPIView.as_view(), name='salary_history'),
   path('api/payments/report/', views.EmployeeSalaryReportAPIView.as_view(), name='employee_salary_report'),

   path('api/salaries/pay/', views.PaySalaryAdminView.as_view(), name='pay_salary_admin'),
   path('api/salaries/employees/', views.EmployeesListView.as_view(), name='employees_list'),
   path('api/salaries/statistics/', views.SalaryStatisticsView.as_view(), name='salary_statistics'),
   path('api/salaries/employee/<str:employee_type>/<int:employee_id>/history/', views.EmployeeSalaryHistoryView.as_view(), name='employee_salary_history'),
    
    # # ---------- Reports APIs ----------
    # Reports URLs
   path('rapports/', views_templates.RapportsView.as_view(), name='rapports'),

   # Report APIs
   path('api/reports/financial/', views.FinancialReportAPIView.as_view(), name='financial_report'),
   path('api/reports/sales/', views.SalesReportAPIView.as_view(), name='sales_report'),
   path('api/reports/performance/', views.PerformanceReportAPIView.as_view(), name='performance_report'),
   path('api/reports/forex/', views.ForexImpactReportAPIView.as_view(), name='forex_report'),
   path('api/reports/stock/', views.StockReportAPIView.as_view(), name='stock_report'),
   path('api/reports/expenses/', views.ExpensesReportAPIView.as_view(), name='expenses_report'),

   # Export URLs
   path('api/export/pdf/<str:report_type>/', views.ExportPDFReportView.as_view(), name='export_pdf'),
   path('api/export/excel/<str:report_type>/', views.ExportExcelReportView.as_view(), name='export_excel'),
    
    # # ---------- Settings APIs ----------
   path('parametres/', views_templates.ParametresView.as_view(), name='parametres'),
   path('api/settings/payment-methods/create/', views.CreatePaymentMethodView.as_view(), name='create_payment_method'),
   path('api/settings/expense-categories/<int:category_id>/toggle/', views.ToggleExpenseCategoryStatusView.as_view(), name='toggle_expense_category'),
    
    # # ---------- Analytics & Stats APIs ----------
    # path('api/analytics/overview/', views.AnalyticsOverviewView.as_view(), name='analytics_overview'),
    # path('api/analytics/trends/', views.TrendsAnalysisView.as_view(), name='trends_analysis'),
    # path('api/analytics/comparison/', views.ComparisonAnalysisView.as_view(), name='comparison_analysis'),
    
    # # ---------- Utility APIs ----------
    # path('api/search/', views.GlobalSearchView.as_view(), name='global_search'),
    # path('api/export/csv/', views.ExportCSVView.as_view(), name='export_csv'),
    # path('api/export/excel/', views.ExportExcelView.as_view(), name='export_excel'),
    # path('api/export/pdf/', views.ExportPDFView.as_view(), name='export_pdf'),
]

"""
URL PATTERN ORGANIZATION:

1. Template Views (HTML Pages)
   - These render full HTML pages
   - Used for initial page loads
   - Include navigation and full UI structure
   
2. API Endpoints (JSON Responses)
   - Return JSON data for AJAX requests
   - Used for dynamic updates without page refresh
   - Organized by resource type
   
NAMING CONVENTIONS:

Template Views:
   - name='resource_name' (e.g., 'dashboard', 'branches')
   - name='resource_name_detail' (e.g., 'branch_detail')

API Views:
   - name='resource_name_api' (e.g., 'ventes_api')
   - name='action_resource_name' (e.g., 'create_branch')
   - name='resource_name_action' (e.g., 'branch_stats')

URL PATTERNS:

Template Views:
   - Simple paths: '', 'branches/', 'ventes/'
   - Detail views: 'branches/<int:pk>/'

API Views:
   - Prefix with 'api/': 'api/stats/', 'api/branches/'
   - RESTful conventions:
     - List: api/resource/
     - Create: api/resource/create/
     - Detail: api/resource/<id>/
     - Update: api/resource/<id>/update/
     - Delete: api/resource/<id>/delete/
     - Custom actions: api/resource/<id>/action/

USAGE IN TEMPLATES:

{% url 'admin_module:dashboard' %}
{% url 'admin_module:branch_detail' branch_id=branch.id %}
{% url 'admin_module:create_branch' %}

USAGE IN JAVASCRIPT:

fetch('/dashboard/api/stats/')
fetch('/dashboard/api/branches/create/', {...})
fetch(`/dashboard/api/branches/${branchId}/update/`, {...})

REVERSE IN PYTHON:

from django.urls import reverse
url = reverse('admin_module:dashboard')
url = reverse('admin_module:branch_detail', kwargs={'branch_id': 1})
url = reverse('admin_module:dashboard_stats')
"""