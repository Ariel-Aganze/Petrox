from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render


class NotificationsAPIView(LoginRequiredMixin, View):
    def get(self, request):
        # Ici vous implémenterez la logique pour récupérer les notifications
        # basées sur le rôle et la branche de l'utilisateur
        
        notifications = []
        # La logique sera implémentée quand les modèles de notifications seront créés
        
        return JsonResponse({'notifications': notifications})


def custom_404(request, exception):
    return render(request, 'shared/404.html', status=404)


def custom_500(request):
    return render(request, 'shared/500.html', status=500)


def custom_403(request, exception):
    return render(request, 'shared/403.html', status=403)