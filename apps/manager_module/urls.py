from django.urls import path
from . import views

app_name = 'manager_module'

urlpatterns = [
    # Dashboard
    path('', views.ManagerDashboardView.as_view(), name='dashboard'),
    
    # API Endpoints
    path('api/stats/', views.ManagerDashboardStatsAPIView.as_view(), name='dashboard_stats'),
    
    # Sales Management
    path('api/sales/', views.ManagerSalesListView.as_view(), name='sales_list'),
    path('api/sales/register/', views.RegisterSaleView.as_view(), name='register_sale'),
    
    # Inventory Management
    path('api/stock/', views.BrancheStockView.as_view(), name='branche_stock'),
    path('api/delivery/confirm/', views.ConfirmDeliveryView.as_view(), name='confirm_delivery'),
]
