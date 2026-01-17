from django.urls import path
from . import views

app_name = 'shared'

urlpatterns = [
    # Common API endpoints
    path('current-rate/', views.CurrentExchangeRateView.as_view(), name='current_rate'),
    path('branches/', views.BranchesSelectView.as_view(), name='branches_select'),
    path('pompistes/', views.PompistesSelectView.as_view(), name='pompistes_select'),
    path('carburants/', views.TypeCarburantSelectView.as_view(), name='carburants_select'),
    path('moyens-paiement/', views.MoyensPaiementSelectView.as_view(), name='moyens_paiement_select'),
    path('categories-depense/', views.CategoriesDepenseSelectView.as_view(), name='categories_depense_select'),
    
    # Document Management
    path('documents/', views.DocumentListView.as_view(), name='documents_list'),
    path('documents/upload/', views.UploadDocumentView.as_view(), name='upload_document'),
    path('documents/<int:document_id>/download/', views.DownloadDocumentView.as_view(), name='download_document'),
    path('documents/categories/', views.DocumentCategoriesListView.as_view(), name='document_categories'),
    
    # Planning/Shifts Management
    path('planning/', views.PlanningShiftListView.as_view(), name='planning_list'),
    path('planning/create/', views.CreatePlanningShiftView.as_view(), name='create_shift'),
    path('planning/<int:shift_id>/update/', views.UpdatePlanningShiftView.as_view(), name='update_shift'),
    path('planning/<int:shift_id>/delete/', views.DeletePlanningShiftView.as_view(), name='delete_shift'),
    
    # Abonnés Management
    path('abonnes/', views.AbonnesListView.as_view(), name='abonnes_list'),
    path('abonnes/consumption/', views.RegisterAbonneConsumptionView.as_view(), name='register_consumption'),
    path('abonnes/<int:abonne_id>/history/', views.AbonneConsumptionHistoryView.as_view(), name='abonne_history'),
    path('abonnes/<int:abonne_id>/payment/', views.RegisterAbonnePaymentView.as_view(), name='register_payment'),
    
    # Notifications
    path('notifications/', views.NotificationListView.as_view(), name='notifications_list'),
    path('notifications/<int:notification_id>/read/', views.MarkNotificationReadView.as_view(), name='mark_notification_read'),
    path('notifications/mark-all-read/', views.MarkAllNotificationsReadView.as_view(), name='mark_all_read'),
    
    # User Profile Management
    path('profile/', views.UserProfileView.as_view(), name='user_profile'),
    path('profile/update/', views.UpdateProfileView.as_view(), name='update_profile'),
    path('profile/change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    
    # Reports & Analytics
    path('reports/sales/', views.SalesReportView.as_view(), name='sales_report'),
    path('reports/expenses/', views.ExpensesReportView.as_view(), name='expenses_report'),
    path('reports/stock/', views.StockReportView.as_view(), name='stock_report'),
    path('reports/export/<str:report_type>/', views.ExportReportView.as_view(), name='export_report'),
]