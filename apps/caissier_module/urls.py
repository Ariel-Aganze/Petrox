from django.urls import path
from . import views

app_name = 'caissier_module'

urlpatterns = [
    # Dashboard
    path('', views.CaissierDashboardView.as_view(), name='dashboard'),
    
    # API Endpoints
    path('api/stats/', views.CaissierDashboardStatsAPIView.as_view(), name='dashboard_stats'),
    
    # Sales Validation
    path('api/sales/pending/', views.PendingSalesView.as_view(), name='pending_sales'),
    path('api/sales/validate/', views.ValidateSaleView.as_view(), name='validate_sale'),
    path('api/sales/history/', views.ValidatedSalesHistoryView.as_view(), name='validated_sales_history'),
    
    # Expense Management
    path('api/expenses/', views.CaissierExpensesListView.as_view(), name='expenses_list'),
    path('api/expenses/register/', views.RegisterExpenseView.as_view(), name='register_expense'),
    path('api/expenses/categories/request/', views.RequestExpenseCategoryView.as_view(), name='request_category'),
    
    # Salary Payments
    path('api/salary/pay/', views.PaySalaryView.as_view(), name='pay_salary'),
    path('api/salary/history/', views.SalaryPaymentHistoryView.as_view(), name='salary_history'),
    
    # Abonnés Payments
    path('api/abonnes/payments/', views.AbonnePaymentsView.as_view(), name='abonne_payments'),
    path('api/abonnes/payment/register/', views.RegisterAbonnePaymentView.as_view(), name='register_abonne_payment'),
    
    # Financial Reports
    path('api/financial/daily/', views.DailyFinancialReportView.as_view(), name='daily_financial'),
    path('api/financial/reconciliation/', views.CashReconciliationView.as_view(), name='cash_reconciliation'),
]