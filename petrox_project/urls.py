from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

def home_redirect(request):
    """Redirect to appropriate dashboard based on user role"""
    if request.user.is_authenticated:
        if request.user.role == 'admin':
            return redirect('admin_module:dashboard')
        elif request.user.role == 'manager':
            return redirect('manager_module:dashboard')
        elif request.user.role == 'caissier':
            return redirect('caissier_module:dashboard')
    
    return redirect('authentication:login')

urlpatterns = [
    # Admin interface
    path('admin/', admin.site.urls),
    
    # Root redirect
    path('', home_redirect, name='home'),
    
    # Authentication
    path('auth/', include('apps.authentication.urls')),
    
    # Dashboard modules
    path('dashboard/', include('apps.admin_module.urls')),
    path('manager/', include('apps.manager_module.urls')),
    path('caissier/', include('apps.caissier_module.urls')),
    
    # API endpoints (if needed for shared functionality)
    path('api/shared/', include('apps.shared.urls')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom admin site headers
admin.site.site_header = 'PETROX Administration'
admin.site.site_title = 'PETROX Admin'
admin.site.index_title = 'Administration PETROX'