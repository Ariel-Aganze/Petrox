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
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, Count, F
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import datetime, timedelta
from apps.core.models import (
    User, Branche, TauxChange, TypeCarburant, CategorieDepense,
    Vente, Depense, Stock, Pompiste, Abonne, ConsommationAbonne,
    Document, DocumentCategory, Notification
)
from decimal import Decimal
import json
import csv

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


class UpdateUserView(AdminRequiredMixin, View):
    def post(self, request, user_id):
        try:
            data = json.loads(request.body)
            
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Utilisateur introuvable'
                })
            
            # Update user fields
            user.prenom = data.get('prenom', user.prenom)
            user.nom = data.get('nom', user.nom)
            user.email = data.get('email', user.email)
            user.telephone = data.get('telephone', user.telephone)
            user.role = data.get('role', user.role)
            
            if data.get('salaire'):
                user.salaire = Decimal(str(data['salaire']))
            
            user.devise_salaire = data.get('devise_salaire', user.devise_salaire)
            
            # Update branch if role is not admin
            if data.get('branche') and user.role != 'admin':
                try:
                    branche = Branche.objects.get(id=data['branche'])
                    user.branche = branche
                except Branche.DoesNotExist:
                    pass
            
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Utilisateur mis à jour avec succès',
                'user': {
                    'id': user.id,
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
                'message': f'Erreur lors de la mise à jour: {str(e)}'
            })


class DeactivateUserView(AdminRequiredMixin, View):
    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.is_active = False
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {user.get_full_name()} désactivé'
            })
            
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Utilisateur introuvable'
            })


class UpdateBrancheView(AdminRequiredMixin, View):
    def post(self, request, branche_id):
        try:
            data = json.loads(request.body)
            
            try:
                branche = Branche.objects.get(id=branche_id)
            except Branche.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Branche introuvable'
                })
            
            # Update branche fields
            branche.nom = data.get('nom', branche.nom)
            branche.adresse = data.get('adresse', branche.adresse)
            branche.ville = data.get('ville', branche.ville)
            branche.province = data.get('province', branche.province)
            
            if data.get('responsable'):
                try:
                    responsable = User.objects.get(
                        id=data['responsable'],
                        role='manager'
                    )
                    branche.responsable = responsable
                except User.DoesNotExist:
                    pass
            
            branche.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Branche mise à jour avec succès'
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


class BranchePerformanceView(AdminRequiredMixin, View):
    def get(self, request, branche_id):
        try:
            branche = Branche.objects.get(id=branche_id)
        except Branche.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Branche introuvable'})
        
        # Get date range
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        
        if not date_start or not date_end:
            today = timezone.now().date()
            date_start = today - timedelta(days=30)
            date_end = today
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Calculate performance metrics
        ventes = Vente.objects.filter(
            branche=branche,
            created_at__date__gte=date_start,
            created_at__date__lte=date_end,
            statut='validee'
        )
        
        depenses = Depense.objects.filter(
            branche=branche,
            created_at__date__gte=date_start,
            created_at__date__lte=date_end,
            statut='approuvee'
        )
        
        total_ventes_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        total_ventes_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        
        total_depenses_usd = depenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        total_depenses_fc = depenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        manquants_count = Vente.objects.filter(
            branche=branche,
            created_at__date__gte=date_start,
            created_at__date__lte=date_end,
            statut='manquant'
        ).count()
        
        performance_data = {
            'branche': {
                'id': branche.id,
                'nom': branche.nom,
                'code': branche.code,
                'ville': branche.ville
            },
            'period': {
                'start': date_start.strftime('%Y-%m-%d'),
                'end': date_end.strftime('%Y-%m-%d')
            },
            'metrics': {
                'total_ventes_usd': str(total_ventes_usd),
                'total_ventes_fc': str(total_ventes_fc),
                'total_depenses_usd': str(total_depenses_usd),
                'total_depenses_fc': str(total_depenses_fc),
                'profit_usd': str(total_ventes_usd - total_depenses_usd),
                'profit_fc': str(total_ventes_fc - total_depenses_fc),
                'manquants_count': manquants_count,
                'transactions_count': ventes.count()
            }
        }
        
        return JsonResponse(performance_data)


class UpdateTypeCarburantView(AdminRequiredMixin, View):
    def post(self, request, carburant_id):
        try:
            data = json.loads(request.body)
            
            try:
                carburant = TypeCarburant.objects.get(id=carburant_id)
            except TypeCarburant.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Type de carburant introuvable'
                })
            
            carburant.nom = data.get('nom', carburant.nom)
            carburant.couleur_hex = data.get('couleur_hex', carburant.couleur_hex)
            carburant.is_active = data.get('is_active', carburant.is_active)
            carburant.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Type de carburant mis à jour avec succès'
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


class AdminSalesListView(AdminRequiredMixin, View):
    def get(self, request):
        # Get filters
        branche_id = request.GET.get('branche_id')
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        statut = request.GET.get('statut')
        pompiste_id = request.GET.get('pompiste_id')
        devise = request.GET.get('devise')
        
        # Base query
        sales = Vente.objects.select_related(
            'branche', 'pompiste', 'manager', 'caissier', 'type_carburant'
        )
        
        # Apply filters
        if branche_id and branche_id != 'all':
            sales = sales.filter(branche_id=branche_id)
        
        if date_start:
            try:
                start_date = datetime.strptime(date_start, '%Y-%m-%d').date()
                sales = sales.filter(created_at__date__gte=start_date)
            except ValueError:
                pass
        
        if date_end:
            try:
                end_date = datetime.strptime(date_end, '%Y-%m-%d').date()
                sales = sales.filter(created_at__date__lte=end_date)
            except ValueError:
                pass
        
        if statut:
            sales = sales.filter(statut=statut)
        
        if pompiste_id:
            sales = sales.filter(pompiste_id=pompiste_id)
        
        # Order and paginate
        sales = sales.order_by('-created_at')
        paginator = Paginator(sales, 50)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        sales_data = []
        for sale in page_obj:
            sales_data.append({
                'id': sale.id,
                'branche': sale.branche.nom,
                'branche_code': sale.branche.code,
                'pompiste': sale.pompiste.get_full_name(),
                'manager': sale.manager.get_full_name(),
                'caissier': sale.caissier.get_full_name() if sale.caissier else None,
                'type_carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'statut': sale.statut,
                'statut_display': sale.get_statut_display(),
                'manquant_usd': str(sale.manquant_usd) if sale.manquant_usd else None,
                'manquant_fc': str(sale.manquant_fc) if sale.manquant_fc else None,
                'raison_manquant': sale.raison_manquant,
                'created_at': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                'validated_at': sale.validated_at.strftime('%d/%m/%Y %H:%M') if sale.validated_at else None
            })
        
        return JsonResponse({
            'sales': sales_data,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'total_count': paginator.count
            }
        })


class MissingSalesReportView(AdminRequiredMixin, View):
    def get(self, request):
        # Get filters
        branche_id = request.GET.get('branche_id')
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        
        # Base query for missing sales
        missing_sales = Vente.objects.filter(statut='manquant').select_related(
            'branche', 'pompiste', 'manager', 'caissier', 'type_carburant'
        )
        
        # Apply filters
        if branche_id and branche_id != 'all':
            missing_sales = missing_sales.filter(branche_id=branche_id)
        
        if date_start:
            try:
                start_date = datetime.strptime(date_start, '%Y-%m-%d').date()
                missing_sales = missing_sales.filter(created_at__date__gte=start_date)
            except ValueError:
                pass
        
        if date_end:
            try:
                end_date = datetime.strptime(date_end, '%Y-%m-%d').date()
                missing_sales = missing_sales.filter(created_at__date__lte=end_date)
            except ValueError:
                pass
        
        # Calculate totals
        total_manquant_usd = missing_sales.aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or 0
        total_manquant_fc = missing_sales.aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or 0
        
        # Group by branch
        branches_summary = {}
        for sale in missing_sales:
            branch_code = sale.branche.code
            if branch_code not in branches_summary:
                branches_summary[branch_code] = {
                    'branche_nom': sale.branche.nom,
                    'count': 0,
                    'total_usd': 0,
                    'total_fc': 0
                }
            branches_summary[branch_code]['count'] += 1
            branches_summary[branch_code]['total_usd'] += float(sale.manquant_usd)
            branches_summary[branch_code]['total_fc'] += float(sale.manquant_fc)
        
        # Get detailed list
        missing_sales = missing_sales.order_by('-created_at')[:100]
        missing_data = []
        
        for sale in missing_sales:
            missing_data.append({
                'id': sale.id,
                'branche': sale.branche.nom,
                'pompiste': sale.pompiste.get_full_name(),
                'manager': sale.manager.get_full_name(),
                'caissier': sale.caissier.get_full_name() if sale.caissier else None,
                'type_carburant': sale.type_carburant.nom,
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'manquant_usd': str(sale.manquant_usd),
                'manquant_fc': str(sale.manquant_fc),
                'raison_manquant': sale.raison_manquant,
                'created_at': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                'validated_at': sale.validated_at.strftime('%d/%m/%Y %H:%M') if sale.validated_at else None
            })
        
        return JsonResponse({
            'summary': {
                'total_count': missing_sales.count(),
                'total_manquant_usd': str(total_manquant_usd),
                'total_manquant_fc': str(total_manquant_fc),
                'branches_summary': branches_summary
            },
            'missing_sales': missing_data
        })


class GlobalStockView(AdminRequiredMixin, View):
    def get(self, request):
        # Get all stock items
        stock_items = Stock.objects.select_related(
            'branche', 'type_carburant'
        ).order_by('branche__nom', 'type_carburant__nom')
        
        # Group by fuel type for summary
        fuel_summary = {}
        branch_summary = {}
        
        total_stock = 0
        alert_count = 0
        
        stock_data = []
        
        for stock in stock_items:
            # Individual stock item
            is_alert = stock.quantite_actuelle <= stock.seuil_alerte
            if is_alert:
                alert_count += 1
            
            total_stock += float(stock.quantite_actuelle)
            
            stock_data.append({
                'id': stock.id,
                'branche': stock.branche.nom,
                'branche_code': stock.branche.code,
                'type_carburant': stock.type_carburant.nom,
                'carburant_couleur': stock.type_carburant.couleur_hex,
                'quantite_actuelle': str(stock.quantite_actuelle),
                'capacite_max': str(stock.capacite_max),
                'seuil_alerte': str(stock.seuil_alerte),
                'pourcentage_rempli': round(stock.pourcentage_rempli, 1),
                'niveau_alerte': stock.niveau_alerte,
                'is_alert': is_alert,
                'prix_achat': str(stock.prix_achat) if stock.prix_achat else None,
                'updated_at': stock.updated_at.strftime('%d/%m/%Y %H:%M')
            })
            
            # Fuel type summary
            fuel_name = stock.type_carburant.nom
            if fuel_name not in fuel_summary:
                fuel_summary[fuel_name] = {
                    'total_quantity': 0,
                    'total_capacity': 0,
                    'branches_count': 0,
                    'alert_branches': 0
                }
            
            fuel_summary[fuel_name]['total_quantity'] += float(stock.quantite_actuelle)
            fuel_summary[fuel_name]['total_capacity'] += float(stock.capacite_max)
            fuel_summary[fuel_name]['branches_count'] += 1
            if is_alert:
                fuel_summary[fuel_name]['alert_branches'] += 1
            
            # Branch summary
            branch_name = stock.branche.nom
            if branch_name not in branch_summary:
                branch_summary[branch_name] = {
                    'total_quantity': 0,
                    'fuel_types': 0,
                    'alerts': 0
                }
            
            branch_summary[branch_name]['total_quantity'] += float(stock.quantite_actuelle)
            branch_summary[branch_name]['fuel_types'] += 1
            if is_alert:
                branch_summary[branch_name]['alerts'] += 1
        
        return JsonResponse({
            'summary': {
                'total_stock': total_stock,
                'total_branches': len(branch_summary),
                'total_fuel_types': len(fuel_summary),
                'alert_count': alert_count
            },
            'fuel_summary': fuel_summary,
            'branch_summary': branch_summary,
            'stock_items': stock_data
        })


class StockAlertsView(AdminRequiredMixin, View):
    def get(self, request):
        # Get stock items with alerts
        alert_stocks = Stock.objects.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).select_related('branche', 'type_carburant').order_by('quantite_actuelle')
        
        alerts_data = []
        for stock in alert_stocks:
            severity = 'critical' if stock.quantite_actuelle <= (stock.seuil_alerte * 0.5) else 'warning'
            
            alerts_data.append({
                'id': stock.id,
                'branche': stock.branche.nom,
                'branche_code': stock.branche.code,
                'type_carburant': stock.type_carburant.nom,
                'quantite_actuelle': str(stock.quantite_actuelle),
                'seuil_alerte': str(stock.seuil_alerte),
                'capacite_max': str(stock.capacite_max),
                'pourcentage_rempli': round(stock.pourcentage_rempli, 1),
                'severity': severity,
                'updated_at': stock.updated_at.strftime('%d/%m/%Y %H:%M')
            })
        
        return JsonResponse({
            'alerts_count': len(alerts_data),
            'alerts': alerts_data
        })


class CreateAbonneView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['nom_entreprise', 'code_client', 'contact_nom', 'contact_telephone', 'type_abonnement']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Check if code_client already exists
            if Abonne.objects.filter(code_client=data['code_client']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce code client existe déjà'
                })
            
            # Create abonne
            abonne = Abonne.objects.create(
                nom_entreprise=data['nom_entreprise'],
                code_client=data['code_client'],
                contact_nom=data['contact_nom'],
                contact_telephone=data['contact_telephone'],
                contact_email=data.get('contact_email', ''),
                adresse=data.get('adresse', ''),
                type_abonnement=data['type_abonnement'],
                solde_usd=Decimal(str(data.get('solde_usd', 0))),
                solde_fc=Decimal(str(data.get('solde_fc', 0))),
                limite_credit=Decimal(str(data.get('limite_credit', 0)))
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Abonné créé avec succès',
                'abonne': {
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client,
                    'type_abonnement': abonne.get_type_abonnement_display()
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


class UpdateAbonneView(AdminRequiredMixin, View):
    def post(self, request, abonne_id):
        try:
            data = json.loads(request.body)
            
            try:
                abonne = Abonne.objects.get(id=abonne_id)
            except Abonne.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Abonné introuvable'
                })
            
            # Update fields
            abonne.nom_entreprise = data.get('nom_entreprise', abonne.nom_entreprise)
            abonne.contact_nom = data.get('contact_nom', abonne.contact_nom)
            abonne.contact_telephone = data.get('contact_telephone', abonne.contact_telephone)
            abonne.contact_email = data.get('contact_email', abonne.contact_email)
            abonne.adresse = data.get('adresse', abonne.adresse)
            abonne.type_abonnement = data.get('type_abonnement', abonne.type_abonnement)
            
            if data.get('limite_credit') is not None:
                abonne.limite_credit = Decimal(str(data['limite_credit']))
            
            abonne.is_active = data.get('is_active', abonne.is_active)
            abonne.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Abonné mis à jour avec succès'
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


class AbonneGlobalHistoryView(AdminRequiredMixin, View):
    def get(self, request, abonne_id):
        try:
            abonne = Abonne.objects.get(id=abonne_id)
        except Abonne.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Abonné introuvable'})
        
        # Get consumption history across all branches
        consumptions = ConsommationAbonne.objects.filter(
            abonne=abonne
        ).select_related('branche', 'type_carburant').order_by('-created_at')[:100]
        
        history_data = []
        for consumption in consumptions:
            history_data.append({
                'id': consumption.id,
                'branche': consumption.branche.nom,
                'type_carburant': consumption.type_carburant.nom,
                'quantite': str(consumption.quantite),
                'montant': str(consumption.montant),
                'devise': consumption.devise,
                'created_at': consumption.created_at.strftime('%d/%m/%Y %H:%M')
            })
        
        # Calculate summary by branch
        branch_summary = {}
        for consumption in consumptions:
            branch_name = consumption.branche.nom
            if branch_name not in branch_summary:
                branch_summary[branch_name] = {
                    'count': 0,
                    'total_usd': 0,
                    'total_fc': 0
                }
            
            branch_summary[branch_name]['count'] += 1
            if consumption.devise == 'USD':
                branch_summary[branch_name]['total_usd'] += float(consumption.montant)
            else:
                branch_summary[branch_name]['total_fc'] += float(consumption.montant)
        
        return JsonResponse({
            'abonne': {
                'id': abonne.id,
                'nom_entreprise': abonne.nom_entreprise,
                'code_client': abonne.code_client,
                'type_abonnement': abonne.get_type_abonnement_display(),
                'solde_usd': str(abonne.solde_usd),
                'solde_fc': str(abonne.solde_fc)
            },
            'branch_summary': branch_summary,
            'history': history_data
        })


class CreateDocumentCategoryView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            if not data.get('nom'):
                return JsonResponse({
                    'success': False,
                    'message': 'Le nom de la catégorie est requis'
                })
            
            # Check if category already exists
            if DocumentCategory.objects.filter(nom=data['nom']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Cette catégorie existe déjà'
                })
            
            category = DocumentCategory.objects.create(
                nom=data['nom'],
                description=data.get('description', ''),
                created_by=request.user
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Catégorie créée avec succès',
                'category': {
                    'id': category.id,
                    'nom': category.nom,
                    'description': category.description
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


class UpdateDocumentVisibilityView(AdminRequiredMixin, View):
    def post(self, request, document_id):
        try:
            data = json.loads(request.body)
            
            try:
                document = Document.objects.get(id=document_id)
            except Document.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Document introuvable'
                })
            
            document.visibilite = data.get('visibilite', document.visibilite)
            document.save()
            
            # Handle branch permissions
            if data.get('branches_autorisees'):
                document.branches_autorisees.clear()
                for branch_id in data['branches_autorisees']:
                    try:
                        branche = Branche.objects.get(id=branch_id)
                        document.branches_autorisees.add(branche)
                    except Branche.DoesNotExist:
                        continue
            
            return JsonResponse({
                'success': True,
                'message': 'Visibilité du document mise à jour'
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


class SystemSettingsView(AdminRequiredMixin, View):
    def get(self, request):
        # Get current system settings
        current_rate = TauxChange.objects.filter(is_active=True).first()
        
        settings_data = {
            'exchange_rate': str(current_rate.taux_usd_fc) if current_rate else '2800.00',
            'total_branches': Branche.objects.filter(is_active=True).count(),
            'total_users': User.objects.filter(is_active=True).count(),
            'total_fuel_types': TypeCarburant.objects.filter(is_active=True).count(),
            'total_expense_categories': CategorieDepense.objects.filter(is_active=True).count(),
            'system_status': 'operational'
        }
        
        return JsonResponse({'settings': settings_data})


class UpdateSystemSettingsView(AdminRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # This would handle system-wide settings updates
            # For now, we'll just return success
            
            return JsonResponse({
                'success': True,
                'message': 'Paramètres système mis à jour'
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


class FinancialReportView(AdminRequiredMixin, View):
    def get(self, request):
        # Get date range
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        branche_id = request.GET.get('branche_id')
        
        if not date_start or not date_end:
            today = timezone.now().date()
            date_start = today.replace(day=1)  # First day of current month
            date_end = today
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Base filters
        vente_filters = {
            'created_at__date__gte': date_start,
            'created_at__date__lte': date_end,
            'statut': 'validee'
        }
        
        depense_filters = {
            'created_at__date__gte': date_start,
            'created_at__date__lte': date_end,
            'statut': 'approuvee'
        }
        
        if branche_id and branche_id != 'all':
            vente_filters['branche_id'] = branche_id
            depense_filters['branche_id'] = branche_id
        
        # Calculate financial metrics
        ventes = Vente.objects.filter(**vente_filters)
        depenses = Depense.objects.filter(**depense_filters)
        
        total_revenue_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        total_revenue_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        
        total_expenses_usd = depenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        total_expenses_fc = depenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        profit_usd = total_revenue_usd - total_expenses_usd
        profit_fc = total_revenue_fc - total_expenses_fc
        
        # Calculate missing amounts
        missing_sales = Vente.objects.filter(
            created_at__date__gte=date_start,
            created_at__date__lte=date_end,
            statut='manquant'
        )
        
        total_missing_usd = missing_sales.aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or 0
        total_missing_fc = missing_sales.aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or 0
        
        financial_report = {
            'period': {
                'start': date_start.strftime('%Y-%m-%d'),
                'end': date_end.strftime('%Y-%m-%d')
            },
            'revenue': {
                'usd': str(total_revenue_usd),
                'fc': str(total_revenue_fc)
            },
            'expenses': {
                'usd': str(total_expenses_usd),
                'fc': str(total_expenses_fc)
            },
            'profit': {
                'usd': str(profit_usd),
                'fc': str(profit_fc)
            },
            'missing_amounts': {
                'usd': str(total_missing_usd),
                'fc': str(total_missing_fc)
            },
            'transactions': {
                'sales_count': ventes.count(),
                'expenses_count': depenses.count(),
                'missing_count': missing_sales.count()
            }
        }
        
        return JsonResponse(financial_report)


class PerformanceReportView(AdminRequiredMixin, View):
    def get(self, request):
        # Get date range
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        
        if not date_start or not date_end:
            today = timezone.now().date()
            date_start = today - timedelta(days=30)
            date_end = today
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Branch performance
        branches = Branche.objects.filter(is_active=True)
        branch_performance = []
        
        for branche in branches:
            ventes = Vente.objects.filter(
                branche=branche,
                created_at__date__gte=date_start,
                created_at__date__lte=date_end,
                statut='validee'
            )
            
            revenue_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
            revenue_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
            transactions = ventes.count()
            
            missing_count = Vente.objects.filter(
                branche=branche,
                created_at__date__gte=date_start,
                created_at__date__lte=date_end,
                statut='manquant'
            ).count()
            
            branch_performance.append({
                'branche': branche.nom,
                'code': branche.code,
                'revenue_usd': str(revenue_usd),
                'revenue_fc': str(revenue_fc),
                'transactions': transactions,
                'missing_count': missing_count,
                'efficiency': round((transactions / (transactions + missing_count) * 100), 2) if (transactions + missing_count) > 0 else 100
            })
        
        # Sort by revenue
        branch_performance.sort(key=lambda x: float(x['revenue_usd']), reverse=True)
        
        return JsonResponse({
            'period': {
                'start': date_start.strftime('%Y-%m-%d'),
                'end': date_end.strftime('%Y-%m-%d')
            },
            'branch_performance': branch_performance
        })


class AuditReportView(AdminRequiredMixin, View):
    def get(self, request):
        # Get recent activity for audit
        date_start = request.GET.get('date_start')
        if not date_start:
            date_start = timezone.now().date() - timedelta(days=7)
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
        
        # Recent sales
        recent_sales = Vente.objects.filter(
            created_at__date__gte=date_start
        ).select_related(
            'branche', 'manager', 'caissier', 'pompiste'
        ).order_by('-created_at')[:50]
        
        # Recent user activity
        recent_users = User.objects.filter(
            last_login__date__gte=date_start
        ).order_by('-last_login')[:20]
        
        # Recent missing reports
        recent_missing = Vente.objects.filter(
            validated_at__date__gte=date_start,
            statut='manquant'
        ).select_related('branche', 'caissier', 'pompiste')[:20]
        
        sales_data = []
        for sale in recent_sales:
            sales_data.append({
                'id': sale.id,
                'branche': sale.branche.nom,
                'manager': sale.manager.get_full_name(),
                'caissier': sale.caissier.get_full_name() if sale.caissier else 'En attente',
                'pompiste': sale.pompiste.get_full_name(),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'statut': sale.get_statut_display(),
                'created_at': sale.created_at.strftime('%d/%m/%Y %H:%M')
            })
        
        users_data = []
        for user in recent_users:
            users_data.append({
                'id': user.id,
                'name': user.get_full_name(),
                'role': user.get_role_display(),
                'branche': user.branche.nom if user.branche else 'Toutes',
                'last_login': user.last_login.strftime('%d/%m/%Y %H:%M') if user.last_login else 'Jamais'
            })
        
        missing_data = []
        for sale in recent_missing:
            missing_data.append({
                'id': sale.id,
                'branche': sale.branche.nom,
                'pompiste': sale.pompiste.get_full_name(),
                'caissier': sale.caissier.get_full_name() if sale.caissier else None,
                'manquant_usd': str(sale.manquant_usd),
                'manquant_fc': str(sale.manquant_fc),
                'raison': sale.raison_manquant,
                'validated_at': sale.validated_at.strftime('%d/%m/%Y %H:%M') if sale.validated_at else None
            })
        
        return JsonResponse({
            'period_start': date_start.strftime('%Y-%m-%d'),
            'recent_sales': sales_data,
            'recent_users': users_data,
            'recent_missing': missing_data
        })