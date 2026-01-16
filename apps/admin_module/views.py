from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import datetime, timedelta
from apps.core.models import (
    User, Branche, TauxChange, TypeCarburant, CategorieDepense
)
from decimal import Decimal
import json


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == 'admin'


class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = 'admin/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['all_branches'] = Branche.objects.filter(is_active=True)
        return context


class CreateUserView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            user = User.objects.create_user(
                username=data['username'],
                email=data['email'],
                password=data.get('password', 'petrox2024'),
                prenom=data['prenom'],
                nom=data['nom'],
                telephone=data.get('telephone', ''),
                role=data['role'],
                salaire=data.get('salaire'),
                devise_salaire=data.get('devise_salaire', 'USD')
            )
            
            if data.get('branche') and data['role'] != 'admin':
                user.branche_id = data['branche']
                user.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Utilisateur créé avec succès',
                'user': {
                    'id': user.id,
                    'name': user.get_full_name(),
                    'role': user.get_role_display(),
                    'branche': user.branche.nom if user.branche else None
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class UpdateExchangeRateView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Désactiver l'ancien taux
            TauxChange.objects.filter(is_active=True).update(is_active=False)
            
            # Créer le nouveau taux
            nouveau_taux = TauxChange.objects.create(
                taux_usd_fc=Decimal(data['nouveau_taux']),
                date_effective=datetime.fromisoformat(data['date_effective'].replace('Z', '+00:00')),
                created_by=request.user,
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Taux de change mis à jour avec succès',
                'new_rate': float(nouveau_taux.taux_usd_fc)
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class DashboardStatsAPIView(AdminRequiredMixin, View):
    def get(self, request):
        # Filtrage par branche si spécifié
        branche_id = request.GET.get('branche')
        
        # Ici vous implémenterez la logique pour récupérer les vraies statistiques
        # depuis vos modèles de ventes, dépenses, stocks, etc.
        
        stats = {
            'total_sales_usd': 0,
            'total_sales_fc': 0,
            'total_stock': 0,
            'forex_impact': 0,
            'current_rate': TauxChange.get_current_rate(),
            'sales_usd_trend': 0,
            'sales_fc_trend': 0,
            'stock_status': 'Normal',
            'active_branches': Branche.objects.filter(is_active=True).count(),
            'recent_transactions': [],
            'fuel_prices': []
        }
        
        return JsonResponse(stats)


class BranchesListView(AdminRequiredMixin, View):
    def get(self, request):
        branches = []
        for branche in Branche.objects.filter(is_active=True):
            branches.append({
                'id': branche.id,
                'nom': branche.nom,
                'code': branche.code,
                'ville': branche.ville,
                'province': branche.province,
                'responsable': branche.responsable.get_full_name() if branche.responsable else None,
                'date_creation': branche.date_mise_en_service.strftime('%d/%m/%Y'),
                'is_active': branche.is_active
            })
        
        return JsonResponse({'branches': branches})


class CreateBrancheView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            branche = Branche.objects.create(
                nom=data['nom'],
                code=data['code'],
                adresse=data['adresse'],
                ville=data['ville'],
                province=data['province'],
                date_mise_en_service=datetime.strptime(data['date_mise_en_service'], '%Y-%m-%d').date(),
                is_active=data.get('is_active', True)
            )
            
            if data.get('responsable'):
                branche.responsable_id = data['responsable']
                branche.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Branche créée avec succès',
                'branche': {
                    'id': branche.id,
                    'nom': branche.nom,
                    'code': branche.code
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class UsersListView(AdminRequiredMixin, View):
    def get(self, request):
        users = []
        for user in User.objects.all().order_by('prenom', 'nom'):
            users.append({
                'id': user.id,
                'username': user.username,
                'prenom': user.prenom,
                'nom': user.nom,
                'email': user.email,
                'telephone': user.telephone,
                'role': user.role,
                'role_display': user.get_role_display(),
                'branche': user.branche.nom if user.branche else None,
                'branche_id': user.branche.id if user.branche else None,
                'salaire': float(user.salaire) if user.salaire else None,
                'devise_salaire': user.devise_salaire,
                'is_active': user.is_active,
                'date_joined': user.date_joined.strftime('%d/%m/%Y')
            })
        
        return JsonResponse({'users': users})


class TypeCarburantListView(AdminRequiredMixin, View):
    def get(self, request):
        carburants = []
        for carburant in TypeCarburant.objects.filter(is_active=True):
            carburants.append({
                'id': carburant.id,
                'nom': carburant.nom,
                'code': carburant.code,
                'couleur_hex': carburant.couleur_hex,
                'is_active': carburant.is_active
            })
        
        return JsonResponse({'carburants': carburants})


class CreateTypeCarburantView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            carburant = TypeCarburant.objects.create(
                nom=data['nom'],
                code=data['code'],
                couleur_hex=data['couleur_hex'],
                is_active=data.get('is_active', True)
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Type de carburant créé avec succès',
                'carburant': {
                    'id': carburant.id,
                    'nom': carburant.nom,
                    'code': carburant.code
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class CategorieDepenseListView(AdminRequiredMixin, View):
    def get(self, request):
        categories = []
        for categorie in CategorieDepense.objects.filter(is_active=True):
            categories.append({
                'id': categorie.id,
                'nom': categorie.nom,
                'description': categorie.description,
                'created_by': categorie.created_by.get_full_name(),
                'created_at': categorie.created_at.strftime('%d/%m/%Y'),
                'is_active': categorie.is_active
            })
        
        return JsonResponse({'categories': categories})


class CreateCategorieDepenseView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            categorie = CategorieDepense.objects.create(
                nom=data['nom'],
                description=data.get('description', ''),
                created_by=request.user,
                is_active=data.get('is_active', True)
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Catégorie de dépense créée avec succès',
                'categorie': {
                    'id': categorie.id,
                    'nom': categorie.nom,
                    'description': categorie.description
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class TauxChangeHistoryView(AdminRequiredMixin, View):
    def get(self, request):
        taux_history = []
        for taux in TauxChange.objects.all().order_by('-date_effective')[:20]:
            taux_history.append({
                'id': taux.id,
                'taux_usd_fc': float(taux.taux_usd_fc),
                'date_effective': taux.date_effective.strftime('%d/%m/%Y %H:%M'),
                'created_by': taux.created_by.get_full_name(),
                'created_at': taux.created_at.strftime('%d/%m/%Y %H:%M'),
                'is_active': taux.is_active
            })
        
        return JsonResponse({'taux_history': taux_history})
