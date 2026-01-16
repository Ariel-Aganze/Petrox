from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import datetime, timedelta
from apps.core.models import User, Branche, TauxChange, CategorieDepense
import json


class CaissierRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return (self.request.user.is_authenticated and 
                self.request.user.role == 'caissier' and 
                self.request.user.branche is not None)


class CaissierDashboardView(CaissierRequiredMixin, TemplateView):
    template_name = 'caissier/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_branche'] = self.request.user.branche
        context['categories_depense'] = CategorieDepense.objects.filter(is_active=True)
        return context


class CaissierDashboardStatsAPIView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Statistiques financières pour la branche du caissier
        stats = {
            'branche_nom': branche.nom,
            'branche_code': branche.code,
            'total_entries_today': 0,
            'total_expenses_today': 0,
            'balance_today': 0,
            'pending_validations': 0,
            'missing_reports': 0,
            'recent_transactions': [],
            'current_rate': TauxChange.get_current_rate()
        }
        
        return JsonResponse(stats)


class ValidateSaleView(CaissierRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            sale_id = data.get('sale_id')
            action = data.get('action')  # 'validate' or 'report_missing'
            
            # Ici vous implémenterez la logique pour valider ou signaler un manquant
            
            return JsonResponse({
                'success': True,
                'message': f'Vente {action} avec succès'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RegisterExpenseView(CaissierRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Ici vous implémenterez la logique pour enregistrer une dépense
            
            return JsonResponse({
                'success': True,
                'message': 'Dépense enregistrée avec succès'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class PaySalaryView(CaissierRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Ici vous implémenterez la logique pour payer un salaire
            
            return JsonResponse({
                'success': True,
                'message': 'Salaire payé avec succès'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class CaissierExpensesListView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        expenses = []
        # Ici vous implémenterez la récupération des dépenses pour la branche
        
        return JsonResponse({'expenses': expenses})


class PendingSalesView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        pending_sales = []
        # Ici vous implémenterez la récupération des ventes en attente de validation
        
        return JsonResponse({'pending_sales': pending_sales})