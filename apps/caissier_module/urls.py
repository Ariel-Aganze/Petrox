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
    
    # Expense Management
    path('api/expenses/', views.CaissierExpensesListView.as_view(), name='expenses_list'),
    path('api/expenses/register/', views.RegisterExpenseView.as_view(), name='register_expense'),
    
    # Salary Payments
    path('api/salary/pay/', views.PaySalaryView.as_view(), name='pay_salary'),
]
