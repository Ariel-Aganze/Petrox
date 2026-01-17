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