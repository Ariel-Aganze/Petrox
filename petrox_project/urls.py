"""petrox_project URL Configuration"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

def home_redirect(request):
    """Redirect root URL to login page"""
    return redirect('authentication:login')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home_redirect, name='home'),
    path('auth/', include('apps.authentication.urls')),
    path('dashboard/', include('apps.admin_module.urls')),
    path('manager/', include('apps.manager_module.urls')),
    path('caissier/', include('apps.caissier_module.urls')),
    path('api/', include('apps.shared.urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
