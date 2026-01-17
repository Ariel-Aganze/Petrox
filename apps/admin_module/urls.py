from django.urls import path
from . import views

app_name = 'admin_module'

urlpatterns = [
    # Dashboard
    path('', views.AdminDashboardView.as_view(), name='dashboard'),
    
    # API Endpoints
    path('api/stats/', views.DashboardStatsAPIView.as_view(), name='dashboard_stats'),
    
    # Users Management
    path('api/users/', views.UsersListView.as_view(), name='users_list'),
    path('api/users/create/', views.CreateUserView.as_view(), name='create_user'),
    path('api/users/<int:user_id>/update/', views.UpdateUserView.as_view(), name='update_user'),
    path('api/users/<int:user_id>/deactivate/', views.DeactivateUserView.as_view(), name='deactivate_user'),
    
    # Branches Management  
    path('api/branches/', views.BranchesListView.as_view(), name='branches_list'),
    path('api/branches/create/', views.CreateBrancheView.as_view(), name='create_branche'),
    path('api/branches/<int:branche_id>/update/', views.UpdateBrancheView.as_view(), name='update_branche'),
    path('api/branches/<int:branche_id>/performance/', views.BranchePerformanceView.as_view(), name='branche_performance'),
    
    # Exchange Rate Management
    path('api/taux/update/', views.UpdateExchangeRateView.as_view(), name='update_exchange_rate'),
    path('api/taux/history/', views.TauxChangeHistoryView.as_view(), name='taux_history'),
    
    # Fuel Types Management
    path('api/carburants/', views.TypeCarburantListView.as_view(), name='carburants_list'),
    path('api/carburants/create/', views.CreateTypeCarburantView.as_view(), name='create_carburant'),
    path('api/carburants/<int:carburant_id>/update/', views.UpdateTypeCarburantView.as_view(), name='update_carburant'),
    
    # Expense Categories Management
    path('api/categories-depense/', views.CategorieDepenseListView.as_view(), name='categories_depense_list'),
    path('api/categories-depense/create/', views.CreateCategorieDepenseView.as_view(), name='create_categorie_depense'),
    
    # Sales Management (Admin view)
    path('api/sales/', views.AdminSalesListView.as_view(), name='admin_sales_list'),
    path('api/sales/missing/', views.MissingSalesReportView.as_view(), name='missing_sales_report'),
    
    # Stock Management (Global view)
    path('api/stock/global/', views.GlobalStockView.as_view(), name='global_stock'),
    path('api/stock/alerts/', views.StockAlertsView.as_view(), name='stock_alerts'),
    
    # Abonnés Management (Admin)
    path('api/abonnes/create/', views.CreateAbonneView.as_view(), name='create_abonne'),
    path('api/abonnes/<int:abonne_id>/update/', views.UpdateAbonneView.as_view(), name='update_abonne'),
    path('api/abonnes/<int:abonne_id>/global-history/', views.AbonneGlobalHistoryView.as_view(), name='abonne_global_history'),
    
    # Document Management (Admin)
    path('api/documents/categories/create/', views.CreateDocumentCategoryView.as_view(), name='create_document_category'),
    path('api/documents/<int:document_id>/visibility/', views.UpdateDocumentVisibilityView.as_view(), name='update_document_visibility'),
    
    # System Settings
    path('api/settings/', views.SystemSettingsView.as_view(), name='system_settings'),
    path('api/settings/update/', views.UpdateSystemSettingsView.as_view(), name='update_settings'),
    
    # Advanced Reports
    path('api/reports/financial/', views.FinancialReportView.as_view(), name='financial_report'),
    path('api/reports/performance/', views.PerformanceReportView.as_view(), name='performance_report'),
    path('api/reports/audit/', views.AuditReportView.as_view(), name='audit_report'),
]