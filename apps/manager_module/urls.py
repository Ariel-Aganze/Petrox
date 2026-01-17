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
    path('api/sales/<int:sale_id>/details/', views.SaleDetailsView.as_view(), name='sale_details'),
    
    # Inventory Management
    path('api/stock/', views.BrancheStockView.as_view(), name='branche_stock'),
    path('api/delivery/confirm/', views.ConfirmDeliveryView.as_view(), name='confirm_delivery'),
    path('api/stock/history/', views.StockHistoryView.as_view(), name='stock_history'),
    
    # Planning Management
    path('api/planning/pompistes/', views.PompistesPlanningView.as_view(), name='pompistes_planning'),
    path('api/pompistes/', views.BranchePompistesView.as_view(), name='branche_pompistes'),
    path('api/pompistes/create/', views.CreatePompisteView.as_view(), name='create_pompiste'),
    
    # Abonnés (Branch-specific)
    path('api/abonnes/branch/', views.BrancheAbonnesView.as_view(), name='branche_abonnes'),
    path('api/abonnes/consumption/', views.RegisterAbonneConsumptionView.as_view(), name='register_abonne_consumption'),
]