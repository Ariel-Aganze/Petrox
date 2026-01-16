from django.apps import AppConfig


class AdminModuleConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.admin_module'
    verbose_name = 'Admin Module'