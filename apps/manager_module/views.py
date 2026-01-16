from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import datetime, timedelta
from apps.core.models import User, Branche, TauxChange, TypeCarburant
import json


class ManagerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return (self.request.user.is_authenticated and 
                self.request.user.role == 'manager' and 
                self.request.user.branche is not None)


class ManagerDashboardView(ManagerRequiredMixin, TemplateView):
    template_name = 'manager/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_branche'] = self.request.user.branche
        context['types_carburant'] = TypeCarburant.objects.filter(is_active=True)
        return context


class ManagerDashboardStatsAPIView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Statistiques pour la branche du manager
        stats = {
            'branche_nom': branche.nom,
            'branche_code': branche.code,
            'total_sales_today': 0,
            'total_sales_week': 0,
            'total_sales_month': 0,
            'pending_validations': 0,
            'stock_alerts': [],
            'recent_sales': [],
            'current_rate': TauxChange.get_current_rate()
        }
        
        return JsonResponse(stats)


class RegisterSaleView(ManagerRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Ici vous implémenterez la logique pour enregistrer une vente
            # Cette vue sera connectée au modèle Vente quand il sera créé
            
            return JsonResponse({
                'success': True,
                'message': 'Vente enregistrée avec succès',
                'sale_id': 'TEMP_ID'  # Sera remplacé par l'ID réel
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class ManagerSalesListView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Filtres de date
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        
        sales = []
        # Ici vous implémenterez la récupération des ventes pour la branche
        
        return JsonResponse({'sales': sales})


class ConfirmDeliveryView(ManagerRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Ici vous implémenterez la logique pour confirmer une livraison
            # et mettre à jour le stock
            
            return JsonResponse({
                'success': True,
                'message': 'Livraison confirmée avec succès'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class BrancheStockView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        stock_items = []
        # Ici vous implémenterez la récupération du stock pour la branche
        
        return JsonResponse({'stock_items': stock_items})
