from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, Count
from django.utils import timezone
from datetime import datetime, timedelta
from apps.admin_module import models
from apps.core.models import (
    User, Branche, TauxChange, TypeCarburant, CategorieDepense,
    Vente, Depense, Stock, Pompiste
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


class DashboardStatsAPIView(AdminRequiredMixin, View):
    def get(self, request):
        # Get date filters
        period = request.GET.get('period', 'today')
        branche_id = request.GET.get('branche_id')
        
        today = timezone.now().date()
        
        if period == 'today':
            start_date = today
            end_date = today
        elif period == 'week':
            start_date = today - timedelta(days=7)
            end_date = today
        elif period == 'month':
            start_date = today - timedelta(days=30)
            end_date = today
        else:
            start_date = today
            end_date = today
        
        # Base queryset filters
        vente_filters = {
            'created_at__date__gte': start_date,
            'created_at__date__lte': end_date,
            'statut': 'validee'
        }
        
        depense_filters = {
            'created_at__date__gte': start_date,
            'created_at__date__lte': end_date,
            'statut': 'approuvee'
        }
        
        if branche_id and branche_id != 'all':
            vente_filters['branche_id'] = branche_id
            depense_filters['branche_id'] = branche_id
        
        # Calculate sales totals
        ventes = Vente.objects.filter(**vente_filters)
        total_sales_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        total_sales_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        
        # Calculate expenses totals
        depenses_usd = Depense.objects.filter(**depense_filters, devise='USD')
        depenses_fc = Depense.objects.filter(**depense_filters, devise='FC')
        
        total_expenses_usd = depenses_usd.aggregate(Sum('montant'))['montant__sum'] or 0
        total_expenses_fc = depenses_fc.aggregate(Sum('montant'))['montant__sum'] or 0
        
        # Get current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        current_rate_value = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        # Calculate forex impact
        forex_impact = 0
        if current_rate:
            # Simple forex impact calculation - difference between expected and actual FC amounts
            expected_fc = total_sales_usd * current_rate_value
            actual_fc = total_sales_fc
            forex_impact = float(expected_fc - actual_fc)
        
        # Calculate stock totals
        total_stock = Stock.objects.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0
        
        # Determine stock status
        low_stock_items = Stock.objects.filter(
            quantite_actuelle__lte=models.F('seuil_alerte')
        ).count()
        
        if low_stock_items > 0:
            stock_status = f"Alerte ({low_stock_items} items)"
        else:
            stock_status = "Normal"
        
        # Count active branches
        active_branches = Branche.objects.filter(is_active=True).count()
        
        # Calculate trends (comparison with previous period)
        if period == 'today':
            prev_start = start_date - timedelta(days=1)
            prev_end = end_date - timedelta(days=1)
        elif period == 'week':
            prev_start = start_date - timedelta(days=7)
            prev_end = end_date - timedelta(days=7)
        else:  # month
            prev_start = start_date - timedelta(days=30)
            prev_end = end_date - timedelta(days=30)
        
        prev_vente_filters = vente_filters.copy()
        prev_vente_filters.update({
            'created_at__date__gte': prev_start,
            'created_at__date__lte': prev_end
        })
        
        prev_ventes = Vente.objects.filter(**prev_vente_filters)
        prev_total_usd = prev_ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        prev_total_fc = prev_ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        
        # Calculate trend percentages
        sales_usd_trend = 0
        sales_fc_trend = 0
        
        if prev_total_usd > 0:
            sales_usd_trend = ((float(total_sales_usd) - float(prev_total_usd)) / float(prev_total_usd)) * 100
        
        if prev_total_fc > 0:
            sales_fc_trend = ((float(total_sales_fc) - float(prev_total_fc)) / float(prev_total_fc)) * 100
        
        stats = {
            'total_sales_usd': f"{total_sales_usd:.2f}",
            'total_sales_fc': f"{total_sales_fc:.0f}",
            'total_expenses_usd': f"{total_expenses_usd:.2f}",
            'total_expenses_fc': f"{total_expenses_fc:.0f}",
            'total_stock': f"{total_stock:.0f}",
            'forex_impact': f"{forex_impact:.2f}",
            'current_rate': f"{current_rate_value:.2f}",
            'stock_status': stock_status,
            'active_branches': active_branches,
            'sales_usd_trend': round(sales_usd_trend, 1),
            'sales_fc_trend': round(sales_fc_trend, 1),
            'period': period,
            'branche_filter': branche_id or 'all'
        }
        
        return JsonResponse(stats)


class CreateUserView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['username', 'prenom', 'nom', 'role']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False, 
                        'message': f'Le champ {field} est requis'
                    })
            
            # Check if username already exists
            if User.objects.filter(username=data['username']).exists():
                return JsonResponse({
                    'success': False, 
                    'message': 'Ce nom d\'utilisateur existe déjà'
                })
            
            # Create user
            user = User.objects.create_user(
                username=data['username'],
                email=data.get('email', ''),
                password=data.get('password', 'petrox2024'),
                prenom=data['prenom'],
                nom=data['nom'],
                telephone=data.get('telephone', ''),
                role=data['role'],
                salaire=data.get('salaire') if data.get('salaire') else None,
                devise_salaire=data.get('devise_salaire', 'USD')
            )
            
            # Assign branch if role is not admin
            if data.get('branche') and data['role'] != 'admin':
                try:
                    branche = Branche.objects.get(id=data['branche'])
                    user.branche = branche
                    user.save()
                except Branche.DoesNotExist:
                    return JsonResponse({
                        'success': False, 
                        'message': 'Branche introuvable'
                    })
            
            return JsonResponse({
                'success': True,
                'message': 'Utilisateur créé avec succès',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'name': user.get_full_name(),
                    'role': user.get_role_display(),
                    'branche': user.branche.nom if user.branche else None
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False, 
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'message': f'Erreur lors de la création: {str(e)}'
            })


class UsersListView(AdminRequiredMixin, View):
    def get(self, request):
        users = User.objects.filter(is_active=True).select_related('branche')
        
        users_data = []
        for user in users:
            users_data.append({
                'id': user.id,
                'username': user.username,
                'name': user.get_full_name(),
                'role': user.get_role_display(),
                'branche': user.branche.nom if user.branche else 'Toutes',
                'email': user.email,
                'telephone': user.telephone,
                'is_active': user.is_active,
                'created_at': user.created_at.strftime('%d/%m/%Y')
            })
        
        return JsonResponse({'users': users_data})


class UpdateExchangeRateView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            new_rate = data.get('taux_usd_fc')
            if not new_rate:
                return JsonResponse({
                    'success': False, 
                    'message': 'Le taux de change est requis'
                })
            
            try:
                new_rate = Decimal(str(new_rate))
                if new_rate <= 0:
                    return JsonResponse({
                        'success': False, 
                        'message': 'Le taux doit être supérieur à 0'
                    })
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False, 
                    'message': 'Taux de change invalide'
                })
            
            # Deactivate current rate
            TauxChange.objects.filter(is_active=True).update(is_active=False)
            
            # Create new rate
            taux_change = TauxChange.objects.create(
                taux_usd_fc=new_rate,
                date_effective=timezone.now(),
                created_by=request.user,
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Taux de change mis à jour: 1 USD = {new_rate} FC',
                'new_rate': str(new_rate)
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False, 
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'message': f'Erreur lors de la mise à jour: {str(e)}'
            })


class CreateBrancheView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['nom', 'code', 'adresse', 'ville', 'province', 'date_mise_en_service']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False, 
                        'message': f'Le champ {field} est requis'
                    })
            
            # Check if code already exists
            if Branche.objects.filter(code=data['code']).exists():
                return JsonResponse({
                    'success': False, 
                    'message': 'Ce code de station existe déjà'
                })
            
            # Parse date
            try:
                date_mise_en_service = datetime.strptime(
                    data['date_mise_en_service'], '%Y-%m-%d'
                ).date()
            except ValueError:
                return JsonResponse({
                    'success': False, 
                    'message': 'Format de date invalide (YYYY-MM-DD attendu)'
                })
            
            # Create branch
            branche = Branche.objects.create(
                nom=data['nom'],
                code=data['code'],
                adresse=data['adresse'],
                ville=data['ville'],
                province=data['province'],
                date_mise_en_service=date_mise_en_service
            )
            
            # Assign responsable if provided
            if data.get('responsable'):
                try:
                    responsable = User.objects.get(
                        id=data['responsable'], 
                        role='manager'
                    )
                    branche.responsable = responsable
                    branche.save()
                except User.DoesNotExist:
                    pass  # Continue without responsable
            
            return JsonResponse({
                'success': True,
                'message': 'Station créée avec succès',
                'branche': {
                    'id': branche.id,
                    'nom': branche.nom,
                    'code': branche.code,
                    'ville': branche.ville
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False, 
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'message': f'Erreur lors de la création: {str(e)}'
            })


class BranchesListView(AdminRequiredMixin, View):
    def get(self, request):
        branches = Branche.objects.filter(is_active=True).select_related('responsable')
        
        branches_data = []
        for branche in branches:
            branches_data.append({
                'id': branche.id,
                'nom': branche.nom,
                'code': branche.code,
                'ville': branche.ville,
                'province': branche.province,
                'adresse': branche.adresse,
                'responsable': branche.responsable.get_full_name() if branche.responsable else None,
                'date_mise_en_service': branche.date_mise_en_service.strftime('%d/%m/%Y'),
                'is_active': branche.is_active,
                'created_at': branche.created_at.strftime('%d/%m/%Y')
            })
        
        return JsonResponse({'branches': branches_data})


class TauxChangeHistoryView(AdminRequiredMixin, View):
    def get(self, request):
        taux_history = TauxChange.objects.all().select_related('created_by')[:20]
        
        history_data = []
        for taux in taux_history:
            history_data.append({
                'id': taux.id,
                'taux_usd_fc': str(taux.taux_usd_fc),
                'date_effective': taux.date_effective.strftime('%d/%m/%Y %H:%M'),
                'created_by': taux.created_by.get_full_name(),
                'is_active': taux.is_active,
                'created_at': taux.created_at.strftime('%d/%m/%Y %H:%M')
            })
        
        return JsonResponse({'history': history_data})


class TypeCarburantListView(AdminRequiredMixin, View):
    def get(self, request):
        carburants = TypeCarburant.objects.filter(is_active=True)
        
        carburants_data = []
        for carburant in carburants:
            carburants_data.append({
                'id': carburant.id,
                'nom': carburant.nom,
                'code': carburant.code,
                'couleur_hex': carburant.couleur_hex,
                'is_active': carburant.is_active
            })
        
        return JsonResponse({'carburants': carburants_data})


class CreateTypeCarburantView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            if not data.get('nom') or not data.get('code'):
                return JsonResponse({
                    'success': False, 
                    'message': 'Le nom et le code sont requis'
                })
            
            # Check if code already exists
            if TypeCarburant.objects.filter(code=data['code']).exists():
                return JsonResponse({
                    'success': False, 
                    'message': 'Ce code de carburant existe déjà'
                })
            
            carburant = TypeCarburant.objects.create(
                nom=data['nom'],
                code=data['code'],
                couleur_hex=data.get('couleur_hex', '#000000')
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
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False, 
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'message': f'Erreur lors de la création: {str(e)}'
            })


class CategorieDepenseListView(AdminRequiredMixin, View):
    def get(self, request):
        categories = CategorieDepense.objects.filter(is_active=True)
        
        categories_data = []
        for categorie in categories:
            categories_data.append({
                'id': categorie.id,
                'nom': categorie.nom,
                'description': categorie.description,
                'is_active': categorie.is_active
            })
        
        return JsonResponse({'categories': categories_data})


class CreateCategorieDepenseView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            if not data.get('nom'):
                return JsonResponse({
                    'success': False, 
                    'message': 'Le nom de la catégorie est requis'
                })
            
            categorie = CategorieDepense.objects.create(
                nom=data['nom'],
                description=data.get('description', '')
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
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False, 
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'message': f'Erreur lors de la création: {str(e)}'
            })