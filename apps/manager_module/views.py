from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from apps.core.models import (
    User, Branche, TauxChange, TypeCarburant, Vente, Stock, 
    Pompiste, Livraison, MoyenPaiement
)
from decimal import Decimal
import json
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from apps.core.models import (
    User, Branche, TauxChange, TypeCarburant, Vente, Stock, 
    Pompiste, Livraison, MoyenPaiement, Abonne, ConsommationAbonne,
    PlanningShift
)
from decimal import Decimal
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
        context['pompistes'] = Pompiste.objects.filter(
            branche=self.request.user.branche, 
            is_active=True
        )
        context['moyens_paiement'] = MoyenPaiement.objects.filter(is_active=True)
        return context


class ManagerDashboardStatsAPIView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        today = timezone.now().date()
        
        # Sales statistics for today
        today_ventes = Vente.objects.filter(
            branche=branche,
            created_at__date=today
        )
        
        total_sales_today_usd = today_ventes.aggregate(
            Sum('montant_usd')
        )['montant_usd__sum'] or 0
        
        total_sales_today_fc = today_ventes.aggregate(
            Sum('montant_fc')
        )['montant_fc__sum'] or 0
        
        # Count pending validations
        pending_validations = Vente.objects.filter(
            branche=branche,
            statut='en_attente'
        ).count()
        
        # Stock information
        stock_items = Stock.objects.filter(branche=branche)
        total_stock = stock_items.aggregate(
            Sum('quantite_actuelle')
        )['quantite_actuelle__sum'] or 0
        
        # Stock alerts
        stock_alerts = stock_items.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).count()
        
        # Active pompistes for current shift
        active_pompistes = Pompiste.objects.filter(
            branche=branche,
            is_active=True
        ).count()
        
        # Transaction count for today
        transactions_count = today_ventes.count()
        
        # Determine stock status
        if stock_alerts > 0:
            stock_status = f"Alerte ({stock_alerts} items)"
        else:
            stock_status = "Normal"
        
        # Current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        current_rate_value = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        # Determine current shift based on time
        current_hour = timezone.now().hour
        if 6 <= current_hour < 18:
            current_shift = "Service jour"
        else:
            current_shift = "Service nuit"
        
        stats = {
            'branche_nom': branche.nom,
            'branche_code': branche.code,
            'total_sales_today': f"{total_sales_today_usd:.2f}",
            'total_sales_today_fc': f"{total_sales_today_fc:.0f}",
            'pending_validations': pending_validations,
            'total_stock': f"{total_stock:.0f}",
            'active_pompistes': active_pompistes,
            'transactions_count': transactions_count,
            'stock_status': stock_status,
            'current_shift': current_shift,
            'current_rate': f"{current_rate_value:.2f}",
            'stock_alerts': stock_alerts
        }
        
        return JsonResponse(stats)


class RegisterSaleView(ManagerRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['pompiste_id', 'type_carburant_id', 'quantite', 
                             'moyen_paiement_id', 'montant_usd', 'montant_fc']
            
            for field in required_fields:
                if not data.get(field) and data.get(field) != 0:
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Get related objects
            try:
                pompiste = Pompiste.objects.get(
                    id=data['pompiste_id'],
                    branche=request.user.branche
                )
                type_carburant = TypeCarburant.objects.get(
                    id=data['type_carburant_id'],
                    is_active=True
                )
                moyen_paiement = MoyenPaiement.objects.get(
                    id=data['moyen_paiement_id'],
                    is_active=True
                )
            except (Pompiste.DoesNotExist, TypeCarburant.DoesNotExist, MoyenPaiement.DoesNotExist):
                return JsonResponse({
                    'success': False,
                    'message': 'Données de référence introuvables'
                })
            
            # Get current exchange rate
            current_rate = TauxChange.objects.filter(is_active=True).first()
            if not current_rate:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun taux de change défini'
                })
            
            # Check stock availability
            try:
                stock = Stock.objects.get(
                    branche=request.user.branche,
                    type_carburant=type_carburant
                )
                
                quantite = Decimal(str(data['quantite']))
                if stock.quantite_actuelle < quantite:
                    return JsonResponse({
                        'success': False,
                        'message': f'Stock insuffisant. Disponible: {stock.quantite_actuelle}L'
                    })
            except Stock.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Stock non configuré pour ce carburant'
                })
            
            # Create sale record
            vente = Vente.objects.create(
                branche=request.user.branche,
                pompiste=pompiste,
                manager=request.user,
                type_carburant=type_carburant,
                quantite=quantite,
                moyen_paiement=moyen_paiement,
                montant_usd=Decimal(str(data['montant_usd'])),
                montant_fc=Decimal(str(data['montant_fc'])),
                taux_change=current_rate.taux_usd_fc,
                observations=data.get('observations', ''),
                statut='en_attente'  # Will be validated by caissier
            )
            
            # Update stock
            stock.quantite_actuelle -= quantite
            stock.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Vente enregistrée avec succès',
                'sale': {
                    'id': vente.id,
                    'pompiste': vente.pompiste.get_full_name(),
                    'carburant': vente.type_carburant.nom,
                    'quantite': str(vente.quantite),
                    'montant_usd': str(vente.montant_usd),
                    'montant_fc': str(vente.montant_fc),
                    'status': vente.get_statut_display()
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
                'message': f'Erreur lors de l\'enregistrement: {str(e)}'
            })


class ManagerSalesListView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get date filters
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        pompiste_id = request.GET.get('pompiste_id')
        statut = request.GET.get('statut')
        
        # Base queryset
        sales = Vente.objects.filter(branche=branche).select_related(
            'pompiste', 'type_carburant', 'moyen_paiement', 'caissier'
        )
        
        # Apply filters
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
        
        if pompiste_id:
            sales = sales.filter(pompiste_id=pompiste_id)
        
        if statut:
            sales = sales.filter(statut=statut)
        
        # Order by most recent
        sales = sales.order_by('-created_at')[:100]  # Limit to last 100 sales
        
        sales_data = []
        for sale in sales:
            sales_data.append({
                'id': sale.id,
                'time': sale.created_at.strftime('%H:%M'),
                'date': sale.created_at.strftime('%d/%m/%Y'),
                'pompiste': sale.pompiste.get_full_name(),
                'carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'moyen_paiement': sale.moyen_paiement.nom,
                'statut': sale.statut,
                'statut_display': sale.get_statut_display(),
                'caissier': sale.caissier.get_full_name() if sale.caissier else None,
                'validated_at': sale.validated_at.strftime('%d/%m/%Y %H:%M') if sale.validated_at else None,
                'manquant_usd': str(sale.manquant_usd) if sale.manquant_usd else '0.00',
                'manquant_fc': str(sale.manquant_fc) if sale.manquant_fc else '0.00',
                'observations': sale.observations
            })
        
        return JsonResponse({'sales': sales_data})


class BrancheStockView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        stock_items = Stock.objects.filter(branche=branche).select_related(
            'type_carburant'
        )
        
        stock_data = []
        for stock in stock_items:
            # Calculate percentage and alert level
            pourcentage_rempli = stock.pourcentage_rempli
            niveau_alerte = stock.niveau_alerte
            
            stock_data.append({
                'id': stock.id,
                'carburant': stock.type_carburant.nom,
                'carburant_code': stock.type_carburant.code,
                'carburant_couleur': stock.type_carburant.couleur_hex,
                'quantite_actuelle': str(stock.quantite_actuelle),
                'capacite_max': str(stock.capacite_max),
                'seuil_alerte': str(stock.seuil_alerte),
                'pourcentage_rempli': round(pourcentage_rempli, 1),
                'niveau_alerte': niveau_alerte,
                'prix_achat': str(stock.prix_achat) if stock.prix_achat else None,
                'updated_at': stock.updated_at.strftime('%d/%m/%Y %H:%M')
            })
        
        return JsonResponse({'stock_items': stock_data})


class ConfirmDeliveryView(ManagerRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['type_carburant_id', 'quantite', 'fournisseur']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Get type carburant
            try:
                type_carburant = TypeCarburant.objects.get(
                    id=data['type_carburant_id'],
                    is_active=True
                )
            except TypeCarburant.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Type de carburant introuvable'
                })
            
            # Parse quantity and validate
            try:
                quantite = Decimal(str(data['quantite']))
                if quantite <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'La quantité doit être supérieure à 0'
                    })
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Quantité invalide'
                })
            
            # Get or create stock record
            stock, created = Stock.objects.get_or_create(
                branche=request.user.branche,
                type_carburant=type_carburant,
                defaults={
                    'quantite_actuelle': 0,
                    'capacite_max': 10000,  # Default capacity
                    'seuil_alerte': 1000,   # Default alert threshold
                }
            )
            
            # Check capacity
            nouvelle_quantite = stock.quantite_actuelle + quantite
            if nouvelle_quantite > stock.capacite_max:
                return JsonResponse({
                    'success': False,
                    'message': f'Capacité dépassée. Maximum: {stock.capacite_max}L, '
                              f'Actuel: {stock.quantite_actuelle}L, '
                              f'Tentative: {nouvelle_quantite}L'
                })
            
            # Create delivery record
            livraison = Livraison.objects.create(
                branche=request.user.branche,
                type_carburant=type_carburant,
                manager=request.user,
                quantite=quantite,
                fournisseur=data['fournisseur'],
                reference_document=data.get('reference_document', ''),
                date_livraison=timezone.now(),
                date_confirmation=timezone.now(),
                statut='confirmee'
            )
            
            # Update stock
            stock.quantite_actuelle = nouvelle_quantite
            
            # Update purchase price if provided
            if data.get('prix_achat'):
                try:
                    prix_achat = Decimal(str(data['prix_achat']))
                    stock.prix_achat = prix_achat
                except (ValueError, TypeError):
                    pass  # Keep old price if invalid
            
            stock.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Livraison confirmée: {quantite}L de {type_carburant.nom}',
                'livraison': {
                    'id': livraison.id,
                    'carburant': type_carburant.nom,
                    'quantite': str(quantite),
                    'fournisseur': data['fournisseur'],
                    'nouveau_stock': str(stock.quantite_actuelle)
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
                'message': f'Erreur lors de la confirmation: {str(e)}'
            })
        

class SaleDetailsView(ManagerRequiredMixin, View):
    def get(self, request, sale_id):
        try:
            sale = Vente.objects.select_related(
                'pompiste', 'manager', 'caissier', 'type_carburant', 'moyen_paiement', 'abonne'
            ).get(id=sale_id, branche=request.user.branche)
        except Vente.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Vente introuvable'})
        
        sale_details = {
            'id': sale.id,
            'pompiste': {
                'id': sale.pompiste.id,
                'nom': sale.pompiste.get_full_name(),
                'quart': sale.pompiste.get_quart_display()
            },
            'manager': {
                'id': sale.manager.id,
                'nom': sale.manager.get_full_name()
            },
            'caissier': {
                'id': sale.caissier.id,
                'nom': sale.caissier.get_full_name()
            } if sale.caissier else None,
            'abonne': {
                'id': sale.abonne.id,
                'nom_entreprise': sale.abonne.nom_entreprise,
                'code_client': sale.abonne.code_client
            } if sale.abonne else None,
            'type_carburant': {
                'id': sale.type_carburant.id,
                'nom': sale.type_carburant.nom,
                'couleur': sale.type_carburant.couleur_hex
            },
            'quantite': str(sale.quantite),
            'moyen_paiement': {
                'id': sale.moyen_paiement.id,
                'nom': sale.moyen_paiement.nom
            },
            'montant_usd': str(sale.montant_usd),
            'montant_fc': str(sale.montant_fc),
            'taux_change': str(sale.taux_change),
            'statut': sale.statut,
            'statut_display': sale.get_statut_display(),
            'manquant_usd': str(sale.manquant_usd) if sale.manquant_usd else None,
            'manquant_fc': str(sale.manquant_fc) if sale.manquant_fc else None,
            'raison_manquant': sale.raison_manquant,
            'observations': sale.observations,
            'created_at': sale.created_at.strftime('%d/%m/%Y %H:%M'),
            'validated_at': sale.validated_at.strftime('%d/%m/%Y %H:%M') if sale.validated_at else None
        }
        
        return JsonResponse({'sale': sale_details})


class StockHistoryView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get date range
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        type_carburant_id = request.GET.get('type_carburant_id')
        
        if not date_start or not date_end:
            today = timezone.now().date()
            date_start = today - timedelta(days=30)
            date_end = today
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Get deliveries (stock increases)
        deliveries = Livraison.objects.filter(
            branche=branche,
            date_livraison__date__gte=date_start,
            date_livraison__date__lte=date_end
        ).select_related('type_carburant')
        
        if type_carburant_id:
            deliveries = deliveries.filter(type_carburant_id=type_carburant_id)
        
        # Get sales (stock decreases)
        sales = Vente.objects.filter(
            branche=branche,
            created_at__date__gte=date_start,
            created_at__date__lte=date_end,
            statut__in=['validee', 'en_attente']  # Include pending sales as they reduce stock
        ).select_related('type_carburant', 'pompiste')
        
        if type_carburant_id:
            sales = sales.filter(type_carburant_id=type_carburant_id)
        
        # Combine and sort history
        history = []
        
        # Add deliveries
        for delivery in deliveries:
            history.append({
                'date': delivery.date_livraison.strftime('%d/%m/%Y %H:%M'),
                'type': 'delivery',
                'type_carburant': delivery.type_carburant.nom,
                'quantite': str(delivery.quantite),
                'operation': 'Livraison',
                'details': f"Fournisseur: {delivery.fournisseur}",
                'reference': delivery.reference_document,
                'impact': '+' + str(delivery.quantite) + 'L'
            })
        
        # Add sales
        for sale in sales:
            history.append({
                'date': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                'type': 'sale',
                'type_carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'operation': 'Vente',
                'details': f"Pompiste: {sale.pompiste.get_full_name()}",
                'reference': f"Vente #{sale.id}",
                'impact': '-' + str(sale.quantite) + 'L',
                'statut': sale.get_statut_display()
            })
        
        # Sort by date (most recent first)
        history.sort(key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y %H:%M'), reverse=True)
        
        return JsonResponse({
            'period': {
                'start': date_start.strftime('%Y-%m-%d'),
                'end': date_end.strftime('%Y-%m-%d')
            },
            'history': history[:100]  # Limit to 100 most recent entries
        })


class PompistesPlanningView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get date range (default: current week)
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        
        if not date_start or not date_end:
            today = timezone.now().date()
            # Get current week (Monday to Sunday)
            start_of_week = today - timedelta(days=today.weekday())
            date_start = start_of_week
            date_end = start_of_week + timedelta(days=6)
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Get all pompistes for this branch
        pompistes = Pompiste.objects.filter(branche=branche, is_active=True)
        
        # Get planning for the period
        planning = PlanningShift.objects.filter(
            branche=branche,
            date_shift__gte=date_start,
            date_shift__lte=date_end
        ).select_related('pompiste')
        
        # Organize planning by pompiste and date
        planning_data = {}
        
        for pompiste in pompistes:
            pompiste_planning = []
            current_date = date_start
            
            while current_date <= date_end:
                # Get shifts for this pompiste on this date
                day_shifts = planning.filter(
                    pompiste=pompiste,
                    date_shift=current_date
                )
                
                day_data = {
                    'date': current_date.strftime('%Y-%m-%d'),
                    'day_name': current_date.strftime('%A'),
                    'shifts': []
                }
                
                for shift in day_shifts:
                    day_data['shifts'].append({
                        'id': shift.id,
                        'type_shift': shift.type_shift,
                        'type_shift_display': shift.get_type_shift_display(),
                        'heure_debut': shift.heure_debut.strftime('%H:%M'),
                        'heure_fin': shift.heure_fin.strftime('%H:%M'),
                        'statut': shift.statut,
                        'statut_display': shift.get_statut_display(),
                        'notes': shift.notes
                    })
                
                pompiste_planning.append(day_data)
                current_date += timedelta(days=1)
            
            planning_data[pompiste.id] = {
                'pompiste': {
                    'id': pompiste.id,
                    'nom': pompiste.get_full_name(),
                    'quart_preference': pompiste.get_quart_display()
                },
                'planning': pompiste_planning
            }
        
        return JsonResponse({
            'period': {
                'start': date_start.strftime('%Y-%m-%d'),
                'end': date_end.strftime('%Y-%m-%d')
            },
            'planning': planning_data
        })


class BranchePompistesView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        pompistes = Pompiste.objects.filter(branche=branche).order_by('prenom', 'nom')
        
        pompistes_data = []
        for pompiste in pompistes:
            # Get recent performance data
            recent_sales = Vente.objects.filter(
                pompiste=pompiste,
                created_at__gte=timezone.now() - timedelta(days=30)
            )
            
            total_sales = recent_sales.count()
            missing_sales = recent_sales.filter(statut='manquant').count()
            
            pompistes_data.append({
                'id': pompiste.id,
                'prenom': pompiste.prenom,
                'nom': pompiste.nom,
                'full_name': pompiste.get_full_name(),
                'telephone': pompiste.telephone,
                'quart': pompiste.quart,
                'quart_display': pompiste.get_quart_display(),
                'salaire': str(pompiste.salaire),
                'devise_salaire': pompiste.devise_salaire,
                'is_active': pompiste.is_active,
                'performance': {
                    'total_sales_30d': total_sales,
                    'missing_sales_30d': missing_sales,
                    'success_rate': round((total_sales - missing_sales) / total_sales * 100, 1) if total_sales > 0 else 100
                },
                'created_at': pompiste.created_at.strftime('%d/%m/%Y')
            })
        
        return JsonResponse({'pompistes': pompistes_data})


class CreatePompisteView(ManagerRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['prenom', 'nom', 'telephone', 'quart', 'salaire', 'devise_salaire']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Check if pompiste already exists (same name in same branch)
            if Pompiste.objects.filter(
                branche=request.user.branche,
                prenom=data['prenom'],
                nom=data['nom']
            ).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Un pompiste avec ce nom existe déjà dans cette branche'
                })
            
            # Create pompiste
            pompiste = Pompiste.objects.create(
                prenom=data['prenom'],
                nom=data['nom'],
                telephone=data['telephone'],
                adresse=data.get('adresse', ''),
                branche=request.user.branche,
                quart=data['quart'],
                salaire=Decimal(str(data['salaire'])),
                devise_salaire=data['devise_salaire']
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Pompiste créé avec succès',
                'pompiste': {
                    'id': pompiste.id,
                    'nom': pompiste.get_full_name(),
                    'quart': pompiste.get_quart_display(),
                    'salaire': str(pompiste.salaire) + ' ' + pompiste.devise_salaire
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


class BrancheAbonnesView(ManagerRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get all active abonnés
        abonnes = Abonne.objects.filter(is_active=True).order_by('nom_entreprise')
        
        # Apply search filter
        search = request.GET.get('search')
        if search:
            abonnes = abonnes.filter(
                Q(nom_entreprise__icontains=search) |
                Q(code_client__icontains=search) |
                Q(contact_nom__icontains=search)
            )
        
        abonnes_data = []
        for abonne in abonnes:
            # Get consumption for this branch in current month
            current_month_start = timezone.now().replace(day=1).date()
            
            branch_consumption = ConsommationAbonne.objects.filter(
                abonne=abonne,
                branche=branche,
                created_at__date__gte=current_month_start
            )
            
            total_consumption_usd = branch_consumption.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
            total_consumption_fc = branch_consumption.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
            
            # Get last consumption date for this branch
            last_consumption = branch_consumption.order_by('-created_at').first()
            
            abonnes_data.append({
                'id': abonne.id,
                'nom_entreprise': abonne.nom_entreprise,
                'code_client': abonne.code_client,
                'contact_nom': abonne.contact_nom,
                'contact_telephone': abonne.contact_telephone,
                'type_abonnement': abonne.type_abonnement,
                'type_abonnement_display': abonne.get_type_abonnement_display(),
                'solde_usd': str(abonne.solde_usd),
                'solde_fc': str(abonne.solde_fc),
                'limite_credit': str(abonne.limite_credit),
                'branch_consumption': {
                    'current_month_usd': str(total_consumption_usd),
                    'current_month_fc': str(total_consumption_fc),
                    'last_consumption': last_consumption.created_at.strftime('%d/%m/%Y') if last_consumption else None,
                    'transactions_count': branch_consumption.count()
                },
                'can_consume': abonne.peut_consommer(Decimal('100'), 'USD'),  # Test with 100 USD
                'status': 'active' if abonne.solde_usd >= 0 and abonne.solde_fc >= 0 else 'debt'
            })
        
        return JsonResponse({
            'abonnes': abonnes_data,
            'branch_info': {
                'nom': branche.nom,
                'code': branche.code
            }
        })


class RegisterAbonneConsumptionView(ManagerRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['abonne_id', 'type_carburant_id', 'quantite', 'montant', 'devise']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Get abonne
            try:
                abonne = Abonne.objects.get(id=data['abonne_id'], is_active=True)
            except Abonne.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Abonné introuvable'
                })
            
            # Get type carburant
            try:
                type_carburant = TypeCarburant.objects.get(
                    id=data['type_carburant_id'],
                    is_active=True
                )
            except TypeCarburant.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Type de carburant introuvable'
                })
            
            # Convert to decimals
            try:
                quantite = Decimal(str(data['quantite']))
                montant = Decimal(str(data['montant']))
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Quantité et montant invalides'
                })
            
            # Check if abonné can consume this amount
            if not abonne.peut_consommer(montant, data['devise']):
                return JsonResponse({
                    'success': False,
                    'message': 'Solde insuffisant ou limite de crédit dépassée'
                })
            
            # Check stock availability
            try:
                stock = Stock.objects.get(
                    branche=request.user.branche,
                    type_carburant=type_carburant
                )
                
                if stock.quantite_actuelle < quantite:
                    return JsonResponse({
                        'success': False,
                        'message': f'Stock insuffisant. Disponible: {stock.quantite_actuelle}L'
                    })
            except Stock.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Stock non configuré pour ce carburant'
                })
            
            # Create consumption record
            consumption = ConsommationAbonne.objects.create(
                abonne=abonne,
                branche=request.user.branche,
                type_carburant=type_carburant,
                quantite=quantite,
                montant=montant,
                devise=data['devise']
            )
            
            # Update abonné balance
            abonne.update_solde_with_consumption(montant, data['devise'], 'consommation')
            
            # Update stock
            stock.quantite_actuelle -= quantite
            stock.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Consommation enregistrée pour {abonne.nom_entreprise}',
                'consumption': {
                    'id': consumption.id,
                    'quantite': str(quantite),
                    'montant': str(montant),
                    'devise': data['devise'],
                    'nouveau_solde_usd': str(abonne.solde_usd),
                    'nouveau_solde_fc': str(abonne.solde_fc),
                    'nouveau_stock': str(stock.quantite_actuelle)
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
                'message': f'Erreur lors de l\'enregistrement: {str(e)}'
            })