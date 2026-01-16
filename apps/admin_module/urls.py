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
    
    # Branches Management  
    path('api/branches/', views.BranchesListView.as_view(), name='branches_list'),
    path('api/branches/create/', views.CreateBrancheView.as_view(), name='create_branche'),
    
    # Exchange Rate Management
    path('api/taux/update/', views.UpdateExchangeRateView.as_view(), name='update_exchange_rate'),
    path('api/taux/history/', views.TauxChangeHistoryView.as_view(), name='taux_history'),
    
    # Fuel Types Management
    path('api/carburants/', views.TypeCarburantListView.as_view(), name='carburants_list'),
    path('api/carburants/create/', views.CreateTypeCarburantView.as_view(), name='create_carburant'),
    
    # Expense Categories Management
    path('api/categories-depense/', views.CategorieDepenseListView.as_view(), name='categories_depense_list'),
    path('api/categories-depense/create/', views.CreateCategorieDepenseView.as_view(), name='create_categorie_depense'),
]
