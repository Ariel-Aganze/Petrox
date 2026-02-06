from django.urls import path
from . import views

app_name = 'caissier_module'

urlpatterns = [
    # ============================================
    # TEMPLATE-BASED VIEWS (HTML Pages)
    # ============================================
    
    # Dashboard
    path('', views.CaissierDashboardView.as_view(), name='dashboard'),
    
    # Ventes (Sales) Page
    path('ventes/', views.VentesPageView.as_view(), name='ventes'),
    
    # Dépenses (Expenses) Page
    path('depenses/', views.DepensesPageView.as_view(), name='depenses'),
    
    # Salaires (Salary Payments) Page
    path('salaires/', views.SalairesPageView.as_view(), name='salaires'),
    
    # ============================================
    # API ENDPOINTS (JSON Responses)
    # ============================================
    
    # ---------- Dashboard APIs ----------
    path('api/stats/', views.CaissierDashboardStatsAPIView.as_view(), name='dashboard_stats'),
    path('api/chart-data/', views.ChartDataAPIView.as_view(), name='chart_data'),
    path('api/recent-transactions/', views.RecentTransactionsAPIView.as_view(), name='recent_transactions'),
    
    # ---------- Sales Validation APIs ----------
    path('api/sales/pending/', views.PendingSalesView.as_view(), name='pending_sales'),
    path('api/sales/list/', views.SalesListAPIView.as_view(), name='sales_list'),
    path('api/sales/<int:sale_id>/', views.SaleDetailAPIView.as_view(), name='sale_detail'),
    path('api/sales/validate/', views.ValidateSaleView.as_view(), name='validate_sale'),
    path('api/sales/history/', views.ValidatedSalesHistoryView.as_view(), name='validated_sales_history'),
    path('api/sales/export/excel/', views.ExportSalesExcelView.as_view(), name='export_sales_excel'),
    path('api/sales/export/pdf/', views.ExportSalesPDFView.as_view(), name='export_sales_pdf'),
    
    # ---------- Expense Management APIs ----------
    path('api/expenses/list/', views.ExpensesListAPIView.as_view(), name='expenses_list'),
    path('api/expenses/<int:expense_id>/', views.ExpenseDetailAPIView.as_view(), name='expense_detail'),
    path('api/expenses/register/', views.RegisterExpenseView.as_view(), name='register_expense'),
    path('api/expenses/categories/request/', views.RequestExpenseCategoryView.as_view(), name='request_category'),
    path('api/expenses/export/excel/', views.ExportExpensesExcelView.as_view(), name='export_expenses_excel'),
    path('api/expenses/export/pdf/', views.ExportExpensesPDFView.as_view(), name='export_expenses_pdf'),
    
    # ---------- Salary Payment APIs ----------
    path('api/salary/employees/', views.EmployeesListAPIView.as_view(), name='employees_list'),
    path('api/salary/pay/', views.PaySalaryView.as_view(), name='pay_salary'),
    path('api/salary/history/', views.SalaryHistoryAPIView.as_view(), name='salary_history'),
    path('api/salary/export/excel/', views.ExportSalariesExcelView.as_view(), name='export_salaries_excel'),
    
    # ---------- Abonnés Payments APIs (Future) ----------
    path('abonnes/', views.AbonnesPageView.as_view(), name='abonnes'),
    path('api/abonnes/', views.AbonnesListAPIView.as_view(), name='abonnes_api'),
    path('api/abonnes/payment/', views.RegisterPaymentView.as_view(), name='register_payment'),
    path('api/abonnes/history/', views.PaymentHistoryAPIView.as_view(), name='payment_history'),
    path('api/abonnes/export/excel/', views.ExportAbonnesExcelView.as_view(), name='export_abonnes_excel'),

    # ---------- Documents URLs ----------
    path('documents/', views.DocumentsPageView.as_view(), name='documents'),
    path('api/documents/', views.DocumentsAPIView.as_view(), name='documents_api'),
    path('api/documents/upload/', views.UploadDocumentView.as_view(), name='upload_document'),
    path('api/documents/<int:document_id>/view/', views.ViewDocumentView.as_view(), name='view_document'),
    path('api/documents/<int:document_id>/download/', views.DownloadDocumentView.as_view(), name='download_document'),
    
    # # ---------- Financial Reports APIs (Future) ----------
    # path('api/financial/daily/', views.DailyFinancialReportView.as_view(), name='daily_financial'),
    # path('api/financial/reconciliation/', views.CashReconciliationView.as_view(), name='cash_reconciliation'),
]