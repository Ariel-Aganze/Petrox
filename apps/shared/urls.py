from django.urls import path
from . import views

app_name = 'shared'

urlpatterns = [
    path('notifications/', views.NotificationsAPIView.as_view(), name='notifications'),
]