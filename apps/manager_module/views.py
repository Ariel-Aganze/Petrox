import os
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, F, Count, Avg
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import datetime, timedelta
from apps.core.models import (
    Attendance, LivraisonCarburant, User, Branche, TauxChange, TypeCarburant, Vente, Stock, 
    Pompiste, Livraison, MoyenPaiement, Abonne, ConsommationAbonne,
    PlanningShift, Document, DocumentCategory, Notification
)
from decimal import Decimal
import json
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction



# ============================================
# AUTHENTICATION MIXIN
# ============================================

class ManagerRequiredMixin(UserPassesTestMixin):
    """
    Ensures user is authenticated, has manager role, and is assigned to a branch
    Redirects unauthorized users to login
    """
    login_url = '/auth/login/'
    
    def test_func(self):
        return (
            self.request.user.is_authenticated and 
            self.request.user.role == 'manager' and 
            self.request.user.branche is not None
        )
    
    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            messages.error(self.request, "Veuillez vous connecter.")
        elif self.request.user.role != 'manager':
            messages.error(self.request, "Accès réservé aux gestionnaires.")
        else:
            messages.error(self.request, "Vous devez être assigné à une branche.")
        return redirect('authentication:login')


# ============================================
# DASHBOARD VIEW
# ============================================

class ManagerDashboardView(ManagerRequiredMixin, TemplateView):
    """
    Manager Dashboard - Operational command center
    Shows real-time sales, stock levels, and performance metrics
    """
    template_name = 'manager/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        branche = user.branche
        
        # Today's date range
        today = timezone.now().date()
        start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))
        
        # Get current exchange rate
        try:
            current_rate = TauxChange.objects.filter(is_active=True).latest('date_effective')
            context['current_rate'] = current_rate
        except TauxChange.DoesNotExist:
            context['current_rate'] = None
        
        # Sales statistics (today only)
        ventes_today = Vente.objects.filter(
            branche=branche,
            created_at__range=[start_of_day, end_of_day]
        )
        
        context['stats'] = {
            'ventes_today_usd': ventes_today.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0,
            'ventes_today_fc': ventes_today.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0,
            'ventes_count': ventes_today.count(),
            'pending_validation': ventes_today.filter(statut='en_attente').count(),
        }
        
        # Stock levels with alerts
        stocks = Stock.objects.filter(branche=branche).select_related('type_carburant')
        context['stocks'] = stocks
        context['stock_alerts'] = stocks.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).count()
        
        # Fuel types
        context['types_carburant'] = TypeCarburant.objects.all()
        
        # Pompistes (for dropdown in sale modal)
        context['pompistes'] = Pompiste.objects.filter(
            branche=branche,
            is_active=True
        ).order_by('prenom', 'nom')
        
        # Payment methods
        context['moyens_paiement'] = MoyenPaiement.objects.all()
        
        # Branch info
        context['branche'] = branche
        context['user'] = user
        
        return context


# ============================================
# DASHBOARD API ENDPOINTS
# ============================================

class DashboardStatsAPIView(ManagerRequiredMixin, View):
    """
    Returns real-time dashboard statistics
    Used for AJAX updates without page reload
    """
    
    def get(self, request):
        try:
            branche = request.user.branche
            period = request.GET.get('period', 'today')  # today, week, month
            
            # Calculate date range based on period
            today = timezone.now().date()
            if period == 'today':
                start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            elif period == 'week':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
            elif period == 'month':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
            else:
                start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            
            end_date = timezone.now()
            
            # Sales statistics
            ventes = Vente.objects.filter(
                branche=branche,
                created_at__range=[start_date, end_date]
            )
            
            # Group by fuel type
            ventes_by_fuel = ventes.values('type_carburant__nom').annotate(
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                total_litres=Sum('quantite')
            )
            
            # Stock info
            stocks = Stock.objects.filter(branche=branche).select_related('type_carburant')
            stock_data = []
            for stock in stocks:
                stock_data.append({
                    'fuel': stock.type_carburant.nom,
                    'quantity': float(stock.quantite_actuelle),
                    'alert_threshold': float(stock.seuil_alerte),
                    'status': 'critical' if stock.quantite_actuelle <= stock.seuil_alerte else 'ok',
                    'percentage': (stock.quantite_actuelle / stock.capacite_max * 100) if stock.capacite_max > 0 else 0
                })
            
            return JsonResponse({
                'success': True,
                'data': {
                    'sales': {
                        'total_usd': float(ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0),
                        'total_fc': float(ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0),
                        'count': ventes.count(),
                        'pending': ventes.filter(statut='en_attente').count(),
                        'validated': ventes.filter(statut='validee').count(),
                        'by_fuel': list(ventes_by_fuel)
                    },
                    'stock': stock_data,
                    'period': period
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ChartDataAPIView(ManagerRequiredMixin, View):
    """
    Returns chart data for line charts
    Supports filtering by period and currency
    """
    
    def get(self, request):
        try:
            branche = request.user.branche
            period = request.GET.get('period', 'week')  # today, week, month, custom
            currency = request.GET.get('currency', 'USD')  # USD or FC
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'today':
                start_date = today
                days = 1
            elif period == 'week':
                start_date = today - timedelta(days=7)
                days = 7
            elif period == 'month':
                start_date = today - timedelta(days=30)
                days = 30
            else:
                # Custom period from request
                start_date = datetime.strptime(request.GET.get('start_date', str(today)), '%Y-%m-%d').date()
                end_date = datetime.strptime(request.GET.get('end_date', str(today)), '%Y-%m-%d').date()
                days = (end_date - start_date).days + 1
            
            # Generate date labels
            labels = []
            data_points = []
            
            for i in range(days):
                current_date = start_date + timedelta(days=i)
                labels.append(current_date.strftime('%d/%m'))
                
                # Get sales for this day
                day_start = timezone.make_aware(datetime.combine(current_date, datetime.min.time()))
                day_end = timezone.make_aware(datetime.combine(current_date, datetime.max.time()))
                
                daily_ventes = Vente.objects.filter(
                    branche=branche,
                    created_at__range=[day_start, day_end],
                    statut__in=['validee', 'en_attente']  # Include pending sales
                )
                
                # Sum based on selected currency
                if currency == 'USD':
                    daily_sales = daily_ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
                else:  # FC
                    daily_sales = daily_ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
                
                data_points.append(float(daily_sales))
            
            return JsonResponse({
                'success': True,
                'data': {
                    'labels': labels,
                    'datasets': [{
                        'label': f'Ventes ({currency})',
                        'data': data_points,
                        'borderColor': '#10b981' if currency == 'USD' else '#3b82f6',
                        'backgroundColor': f'rgba({"16, 185, 129" if currency == "USD" else "59, 130, 246"}, 0.1)',
                        'tension': 0.4
                    }]
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class RecentTransactionsAPIView(ManagerRequiredMixin, View):
    """
    Returns recent transactions for dashboard
    """
    
    def get(self, request):
        try:
            branche = request.user.branche
            limit = int(request.GET.get('limit', 10))
            
            ventes = Vente.objects.filter(
                branche=branche
            ).select_related(
                'pompiste', 'type_carburant', 'moyen_paiement'
            ).order_by('-created_at')[:limit]
            
            transactions = []
            for vente in ventes:
                # Determine primary amount/currency for display
                if vente.montant_usd > 0:
                    amount = float(vente.montant_usd)
                    currency = 'USD'
                else:
                    amount = float(vente.montant_fc)
                    currency = 'FC'
                
                transactions.append({
                    'id': vente.id,
                    'date': vente.created_at.strftime('%d/%m/%Y %H:%M'),
                    'pompiste': f"{vente.pompiste.prenom} {vente.pompiste.nom}" if vente.pompiste else 'N/A',
                    'fuel': vente.type_carburant.nom if vente.type_carburant else 'N/A',
                    'quantity': float(vente.quantite),
                    'amount': amount,
                    'currency': currency,
                    'status': vente.statut,
                    'payment_method': vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A'
                })
            
            return JsonResponse({
                'success': True,
                'data': transactions
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ForexImpactAPIView(ManagerRequiredMixin, View):
    """
    Calculate forex impact (gain/loss) per fuel type
    """
    
    def get(self, request):
        try:
            branche = request.user.branche
            
            # Get current rate
            try:
                current_rate = TauxChange.objects.filter(is_active=True).latest('date_effective')
            except TauxChange.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun taux de change configuré'
                }, status=404)
            
            # Get today's sales
            today = timezone.now().date()
            start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))
            
            ventes_today = Vente.objects.filter(
                branche=branche,
                created_at__range=[start_of_day, end_of_day]
            ).select_related('type_carburant')
            
            forex_impact = []
            for fuel_type in TypeCarburant.objects.all():
                fuel_sales = ventes_today.filter(type_carburant=fuel_type)
                
                # Calculate impact - all sales track both USD and FC
                total_usd = float(fuel_sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0)
                total_fc = float(fuel_sales.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0)
                
                # Convert FC to USD at current rate
                fc_in_usd = total_fc / float(current_rate.taux_usd_fc)
                total_in_usd = total_usd + fc_in_usd
                
                # Check if there's gain/loss based on rate applied vs current rate
                # This is simplified - in production, you'd track the rate for each sale
                impact = {
                    'fuel': fuel_type.nom,
                    'total_usd': total_usd,
                    'total_fc': total_fc,
                    'fc_in_usd': fc_in_usd,
                    'total_in_usd': total_in_usd,
                    'current_rate': float(current_rate.taux_usd_fc)
                }
                
                forex_impact.append(impact)
            
            return JsonResponse({
                'success': True,
                'data': forex_impact
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================
# SALES MANAGEMENT VIEWS
# ============================================

class VentesListView(ManagerRequiredMixin, TemplateView):
    """Display list of all sales for this branch"""
    template_name = 'manager/ventes.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['branche'] = self.request.user.branche
        context['pompistes'] = Pompiste.objects.filter(
            branche=self.request.user.branche,
            is_active=True
        )
        context['types_carburant'] = TypeCarburant.objects.all()
        context['moyens_paiement'] = MoyenPaiement.objects.all()
        return context


class VentesListAPIView(ManagerRequiredMixin, View):
    """
    Returns paginated list of sales with filtering
    """
    
    def get(self, request):
        try:
            branche = request.user.branche
            page = int(request.GET.get('page', 1))
            per_page = int(request.GET.get('per_page', 20))
            
            # Base queryset
            ventes = Vente.objects.filter(branche=branche)
            
            # Apply filters
            if request.GET.get('pompiste_id'):
                ventes = ventes.filter(pompiste_id=request.GET.get('pompiste_id'))
            
            if request.GET.get('fuel_type_id'):
                ventes = ventes.filter(type_carburant_id=request.GET.get('fuel_type_id'))
            
            if request.GET.get('status'):
                ventes = ventes.filter(statut=request.GET.get('status'))
            
            if request.GET.get('start_date'):
                start_date = datetime.strptime(request.GET.get('start_date'), '%Y-%m-%d')
                ventes = ventes.filter(created_at__gte=start_date)
            
            if request.GET.get('end_date'):
                end_date = datetime.strptime(request.GET.get('end_date'), '%Y-%m-%d')
                end_date = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
                ventes = ventes.filter(created_at__lte=end_date)
            
            # Order by date (newest first)
            ventes = ventes.select_related(
                'pompiste', 'type_carburant', 'moyen_paiement', 'abonne'
            ).order_by('-created_at')
            
            # Pagination
            paginator = Paginator(ventes, per_page)
            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)
            
            # Serialize data
            sales_data = []
            for vente in page_obj:
                sales_data.append({
                    'id': vente.id,
                    'date': vente.created_at.strftime('%d/%m/%Y %H:%M'),
                    'pompiste': f"{vente.pompiste.prenom} {vente.pompiste.nom}" if vente.pompiste else 'N/A',
                    'fuel': vente.type_carburant.nom if vente.type_carburant else 'N/A',
                    'quantity': float(vente.quantite),
                    'amount_usd': float(vente.montant_usd),
                    'amount_fc': float(vente.montant_fc),
                    'status': vente.statut,
                    'payment_method': vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A',
                    'subscriber': f"{vente.abonne.nom_entreprise}" if vente.abonne else None,
                })
            
            return JsonResponse({
                'success': True,
                'data': sales_data,
                'pagination': {
                    'current_page': page_obj.number,
                    'total_pages': paginator.num_pages,
                    'total_items': paginator.count,
                    'has_next': page_obj.has_next(),
                    'has_previous': page_obj.has_previous()
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class CreateVenteAPIView(ManagerRequiredMixin, View):
    """
    Create a new sale transaction
    Business Logic:
    - Status: "en_attente" (pending validation by Caissier)
    - Stock: Provisionally deducted
    - Exchange rate: Captured at transaction time
    """
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            branche = request.user.branche
            
            # Validate required fields
            required_fields = ['pompiste_id', 'fuel_type_id', 'quantity', 'payment_method_id']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({
                        'success': False,
                        'message': f'Champ requis manquant: {field}'
                    }, status=400)
            
            # Get related objects
            pompiste = get_object_or_404(Pompiste, id=data['pompiste_id'], branche=branche)
            type_carburant = get_object_or_404(TypeCarburant, id=data['fuel_type_id'])
            moyen_paiement = get_object_or_404(MoyenPaiement, id=data['payment_method_id'])
            
            # Get current exchange rate
            try:
                taux_change = TauxChange.objects.filter(is_active=True).latest('date_effective')
            except TauxChange.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun taux de change configuré'
                }, status=400)
            
            # Validate stock availability
            try:
                stock = Stock.objects.get(branche=branche, type_carburant=type_carburant)
                if stock.quantite_actuelle < Decimal(str(data['quantity'])):
                    return JsonResponse({
                        'success': False,
                        'message': f'Stock insuffisant. Disponible: {stock.quantite_actuelle} L'
                    }, status=400)
            except Stock.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Stock non configuré pour ce carburant'
                }, status=400)
            
            # Handle subscriber if provided
            abonne = None
            if data.get('abonne_id'):
                abonne = get_object_or_404(Abonne, id=data['abonne_id'])
            
            # Create vente
            vente = Vente.objects.create(
                branche=branche,
                pompiste=pompiste,
                manager=request.user,
                type_carburant=type_carburant,
                quantite=Decimal(str(data['quantity'])),
                montant_usd=Decimal(str(data.get('amount_usd', 0))),
                montant_fc=Decimal(str(data.get('amount_fc', 0))),
                moyen_paiement=moyen_paiement,
                abonne=abonne,
                taux_change=taux_change.taux_usd_fc,
                statut='en_attente'  # Pending validation
            )
            
            # Provisionally deduct stock
            stock.quantite_actuelle -= Decimal(str(data['quantity']))
            stock.save()
            
            # Handle subscriber balance/debt
            if abonne:
                ConsommationAbonne.objects.create(
                    abonne=abonne,
                    branche=branche,
                    vente=vente,
                    montant_usd=vente.montant_usd,
                    montant_fc=vente.montant_fc
                )
                
                # Update subscriber balance based on type
                if abonne.type_abonnementment == 'prepaye':
                    # Check USD balance
                    if abonne.solde_usd_usd < vente.montant_usd:
                        return JsonResponse({
                            'success': False,
                            'message': 'Solde USD insuffisant pour cet abonné'
                        }, status=400)
                    abonne.solde_usd_usd -= vente.montant_usd
                    abonne.solde_usd_fc -= vente.montant_fc
                elif abonne.type_abonnementment == 'postpaye':
                    # Debt is tracked as negative balance
                    abonne.solde_usd_usd -= vente.montant_usd
                    abonne.solde_usd_fc -= vente.montant_fc
                elif abonne.type_abonnementment == 'credit':
                    # Check credit limit
                    current_debt = abs(abonne.solde_usd_usd) if abonne.solde_usd_usd < 0 else 0
                    if abonne.limite_credit - current_debt < vente.montant_usd:
                        return JsonResponse({
                            'success': False,
                            'message': 'Limite de crédit dépassée'
                        }, status=400)
                    abonne.solde_usd_usd -= vente.montant_usd
                    abonne.solde_usd_fc -= vente.montant_fc
                
                abonne.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Vente enregistrée avec succès',
                'data': {
                    'id': vente.id,
                    'status': vente.statut
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class VenteDetailAPIView(ManagerRequiredMixin, View):
    """Get detailed information about a specific sale"""
    
    def get(self, request, vente_id):
        try:
            vente = get_object_or_404(
                Vente.objects.select_related(
                    'pompiste', 'type_carburant', 'moyen_paiement', 'abonne', 'manager'
                ),
                id=vente_id,
                branche=request.user.branche
            )
            
            data = {
                'id': vente.id,
                'date': vente.created_at.strftime('%d/%m/%Y %H:%M'),
                'pompiste': {
                    'id': vente.pompiste.id if vente.pompiste else None,
                    'name': f"{vente.pompiste.prenom} {vente.pompiste.nom}" if vente.pompiste else 'N/A'
                },
                'fuel': {
                    'id': vente.type_carburant.id if vente.type_carburant else None,
                    'name': vente.type_carburant.nom if vente.type_carburant else 'N/A'
                },
                'quantity': float(vente.quantite),
                'amount_usd': float(vente.montant_usd),
                'amount_fc': float(vente.montant_fc),
                'payment_method': vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A',
                'subscriber': {
                    'id': vente.abonne.id if vente.abonne else None,
                    'name': vente.abonne.nom_entreprise if vente.abonne else None
                },
                'exchange_rate': float(vente.taux_change) if vente.taux_change else None,
                'status': vente.statut,
                'recorded_by': vente.manager.get_full_name() if vente.manager else 'N/A',
                'missing_usd': float(vente.manquant_usd) if vente.manquant_usd else 0,
                'missing_fc': float(vente.manquant_fc) if vente.manquant_fc else 0
            }
            
            return JsonResponse({
                'success': True,
                'data': data
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================
# STOCK & DELIVERIES VIEWS
# ============================================

class CarburantsView(ManagerRequiredMixin, TemplateView):
    """Stock management and delivery confirmation page"""
    template_name = 'manager/carburants.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['branche'] = self.request.user.branche
        context['stocks'] = Stock.objects.filter(
            branche=self.request.user.branche
        ).select_related('type_carburant')
        context['types_carburant'] = TypeCarburant.objects.all()
        return context


class StockListAPIView(ManagerRequiredMixin, View):
    """Returns current stock levels"""
    
    def get(self, request):
        try:
            stocks = Stock.objects.filter(
                branche=request.user.branche
            ).select_related('type_carburant')
            
            stock_data = []
            for stock in stocks:
                percentage = (stock.quantite_actuelle / stock.capacite_max * 100) if stock.capacite_max > 0 else 0
                
                stock_data.append({
                    'id': stock.id,
                    'fuel': stock.type_carburant.nom if stock.type_carburant else 'N/A',
                    'quantite_actuelle': float(stock.quantite_actuelle),
                    'seuil_alerte': float(stock.seuil_alerte),
                    'capacite_max': float(stock.capacite_max) if stock.capacite_max else 0,
                    'percentage': float(percentage)
                })
            
            return JsonResponse({
                'success': True,
                'data': stock_data
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ConfirmDeliveryAPIView(ManagerRequiredMixin, View):
    """
    Confirm a fuel delivery
    This updates stock DEFINITIVELY (not provisional like sales)
    """
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            branche = request.user.branche
            
            # Validate required fields
            required_fields = ['fuel_type_id', 'quantity', 'source', 'document_reference']
            for field in required_fields:
                if field not in data:
                    return JsonResponse({
                        'success': False,
                        'message': f'Champ requis manquant: {field}'
                    }, status=400)
            
            type_carburant = get_object_or_404(TypeCarburant, id=data['fuel_type_id'])
            
            # Get or create stock record
            stock, created = Stock.objects.get_or_create(
                branche=branche,
                type_carburant=type_carburant,
                defaults={
                    'quantite_actuelle': 0,
                    'seuil_alerte': 1000,
                    'capacite_max': 50000
                }
            )
            
            # Create delivery record
            livraison = Livraison.objects.create(
                branche=branche,
                type_carburant=type_carburant,
                quantite=Decimal(str(data['quantity'])),
                source=data['source'],  # 'interne' or 'partenaire'
                reference_document=data['document_reference'],
                confirmee_par=request.user,
                notes=data.get('notes', '')
            )
            
            # Update stock DEFINITIVELY
            stock.quantite_actuelle += Decimal(str(data['quantity']))
            stock.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Livraison confirmée avec succès',
                'data': {
                    'new_stock_level': float(stock.quantite_actuelle)
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class StockMovementsAPIView(ManagerRequiredMixin, View):
    """Get stock movement history (deliveries and sales)"""
    
    def get(self, request):
        try:
            branche = request.user.branche
            page = int(request.GET.get('page', 1))
            per_page = int(request.GET.get('per_page', 15))
            
            movements = []
            
            # Get deliveries
            livraisons = Livraison.objects.filter(
                branche=branche
            ).select_related('type_carburant', 'manager').order_by('-date_livraison')
            
            for livraison in livraisons:
                movements.append({
                    'type': 'delivery',
                    'date': livraison.date_livraison.strftime('%d/%m/%Y %H:%M'),
                    'fuel': livraison.type_carburant.nom if livraison.type_carburant else 'N/A',
                    'quantity': float(livraison.quantite),
                    'reference': livraison.reference_document or f"LIV-{livraison.id}",
                    'actor': livraison.manager.get_full_name() if livraison.manager else 'N/A',
                    'date_obj': livraison.date_livraison  # For sorting
                })
            
            # Get sales (validated only)
            ventes = Vente.objects.filter(
                branche=branche,
                statut='validee'
            ).select_related('type_carburant', 'pompiste').order_by('-created_at')
            
            for vente in ventes:
                movements.append({
                    'type': 'sale',
                    'date': vente.created_at.strftime('%d/%m/%Y %H:%M'),
                    'fuel': vente.type_carburant.nom if vente.type_carburant else 'N/A',
                    'quantity': -float(vente.quantite),
                    'reference': f"Vente #{vente.id}",
                    'actor': f"{vente.pompiste.prenom} {vente.pompiste.nom}" if vente.pompiste else 'N/A',
                    'date_obj': vente.created_at  # For sorting
                })
            
            # Sort by date (most recent first)
            movements.sort(key=lambda x: x['date_obj'], reverse=True)
            
            # Remove date_obj before returning
            for movement in movements:
                del movement['date_obj']
            
            # Pagination
            paginator = Paginator(movements, per_page)
            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)
            
            return JsonResponse({
                'success': True,
                'data': list(page_obj),
                'pagination': {
                    'current_page': page_obj.number,
                    'total_pages': paginator.num_pages,
                    'total_items': paginator.count,
                    'has_previous': page_obj.has_previous(),
                    'has_next': page_obj.has_next()
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================
# SUBSCRIBERS (ABONNÉS) VIEWS
# ============================================

class AbonnesView(ManagerRequiredMixin, TemplateView):
    """Subscribers management page"""
    template_name = 'manager/abonnes.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['branche'] = self.request.user.branche
        context['pompistes'] = Pompiste.objects.filter(
            branche=self.request.user.branche,
            is_active=True
        ).order_by('prenom', 'nom')
        context['types_carburant'] = TypeCarburant.objects.filter(is_active=True).order_by('nom')
        context['moyens_paiement'] = MoyenPaiement.objects.filter(is_active=True).order_by('nom')
        return context


class AbonnesListAPIView(ManagerRequiredMixin, View):
    """
    Returns list of all subscribers (GLOBAL - not branch-specific)
    Subscribers can purchase at any branch
    """
    
    def get(self, request):
        try:
            branche = request.user.branche
            
            # Get ALL subscribers (they're global)
            abonnes = Abonne.objects.filter(is_active=True).order_by('nom_entreprise')
            
            # Search filter
            search = request.GET.get('search')
            if search:
                abonnes = abonnes.filter(
                    Q(nom_entreprise__icontains=search) |
                    Q(code_client__icontains=search) |
                    Q(contact_nom__icontains=search)
                )
            
            abonnes_data = []
            for abonne in abonnes:
                try:
                    # Get consumption for this branch in current month
                    current_month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    
                    # Get ventes for this subscriber at this branch
                    branch_sales = Vente.objects.filter(
                        abonne=abonne,
                        branche=branche,
                        created_at__gte=current_month_start
                    )
                    
                    total_consumption_usd = sum(float(v.montant_usd) for v in branch_sales)
                    total_consumption_fc = sum(float(v.montant_fc) for v in branch_sales)
                    
                    # Get last consumption date for this branch
                    last_sale = branch_sales.order_by('-created_at').first()
                    
                    abonnes_data.append({
                        'id': abonne.id,
                        'nom_entreprise': abonne.nom_entreprise,
                        'code_client': abonne.code_client,
                        'contact_nom': abonne.contact_nom or '',
                        'contact_telephone': abonne.contact_telephone or '',
                        'contact_email': abonne.contact_email or '',
                        'type_abonnement': abonne.type_abonnement,
                        'type_abonnement_display': abonne.get_type_abonnement_display(),
                        'solde_usd': str(abonne.solde_usd),
                        'solde_fc': str(abonne.solde_fc),
                        'limite_credit': str(abonne.limite_credit),
                        'branch_consumption': {
                            'current_month_usd': str(total_consumption_usd),
                            'current_month_fc': str(total_consumption_fc),
                            'last_consumption': last_sale.created_at.strftime('%d/%m/%Y') if last_sale else None,
                            'transactions_count': branch_sales.count()
                        },
                        'can_consume': True,
                        'status': 'active' if abonne.solde_usd >= 0 and abonne.solde_fc >= 0 else 'debt'
                    })
                except Exception as e:
                    # Log the error but continue with other subscribers
                    print(f"Error processing subscriber {abonne.id}: {str(e)}")
                    continue
            
            return JsonResponse({
                'abonnes': abonnes_data,
                'branch_info': {
                    'nom': branche.nom,
                    'code': branche.code
                }
            })
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Error in AbonnesListAPIView: {error_details}")
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_details': error_details
            }, status=500)


class AbonneDetailAPIView(ManagerRequiredMixin, View):
    """Get detailed subscriber information including consumption history"""
    
    def get(self, request, abonne_id):
        try:
            abonne = get_object_or_404(Abonne, id=abonne_id)
            branche = request.user.branche
            
            # Get consumption history at THIS branch
            # Note: ConsommationAbonne links to Vente for details
            consommations_branche = Vente.objects.filter(
                abonne=abonne,
                branche=branche
            ).select_related('type_carburant', 'pompiste').order_by('-created_at')[:10]
            
            # Get consumption history at ALL branches
            consommations_total = Vente.objects.filter(
                abonne=abonne
            ).select_related('type_carburant', 'pompiste', 'branche').order_by('-created_at')[:20]
            
            branch_consumption = []
            for vente in consommations_branche:
                branch_consumption.append({
                    'date': vente.created_at.strftime('%d/%m/%Y %H:%M'),
                    'amount_usd': float(vente.montant_usd),
                    'amount_fc': float(vente.montant_fc),
                    'fuel': vente.type_carburant.nom if vente.type_carburant else 'N/A'
                })
            
            total_consumption = []
            for vente in consommations_total:
                total_consumption.append({
                    'date': vente.created_at.strftime('%d/%m/%Y %H:%M'),
                    'branch': vente.branche.nom if vente.branche else 'N/A',
                    'amount_usd': float(vente.montant_usd),
                    'amount_fc': float(vente.montant_fc),
                    'fuel': vente.type_carburant.nom if vente.type_carburant else 'N/A'
                })
            
            data = {
                'id': abonne.id,
                'nom_entreprise': abonne.nom_entreprise,
                'code_client': abonne.code_client,
                'contact_nom': abonne.contact_nom,
                'contact_telephone': abonne.contact_telephone or '',
                'contact_email': abonne.contact_email or '',
                'type_abonnement': abonne.type_abonnement,
                'type_abonnement_display': abonne.get_type_abonnement_display(),
                'solde_usd': str(abonne.solde_usd),
                'solde_fc': str(abonne.solde_fc),
                'limite_credit': str(abonne.limite_credit),
                'consumption_this_branch': branch_consumption,
                'consumption_all_branches': total_consumption
            }
            
            return JsonResponse({
                'success': True,
                'data': data
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

class RecordConsumptionView(ManagerRequiredMixin, View):
    """Record subscriber consumption with automatic balance calculation"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            abonne_id = data.get('abonne_id')
            pompiste_id = data.get('pompiste_id')
            fuel_type_id = data.get('fuel_type_id')
            quantity = data.get('quantity')
            currency = data.get('currency')
            payment_method_id = data.get('payment_method_id')
            
            if not all([abonne_id, pompiste_id, fuel_type_id, quantity, currency, payment_method_id]):
                return JsonResponse({
                    'success': False,
                    'message': 'Tous les champs sont requis'
                }, status=400)
            
            # Get objects
            try:
                abonne = Abonne.objects.get(id=abonne_id)
                pompiste = Pompiste.objects.get(id=pompiste_id, branche=request.user.branche)
                fuel_type = TypeCarburant.objects.get(id=fuel_type_id)
                payment_method = MoyenPaiement.objects.get(id=payment_method_id)
            except (Abonne.DoesNotExist, Pompiste.DoesNotExist, TypeCarburant.DoesNotExist, MoyenPaiement.DoesNotExist) as e:
                return JsonResponse({
                    'success': False,
                    'message': f'Enregistrement introuvable: {str(e)}'
                }, status=404)
            
            # Calculate amounts
            quantity = Decimal(str(quantity))
            amount_usd = Decimal('0.00')
            amount_fc = Decimal('0.00')
            
            if currency == 'USD':
                amount_usd = Decimal(str(fuel_type.prix_vente_usd)) * quantity
            else:
                amount_fc = Decimal(str(fuel_type.prix_vente_fc)) * quantity
            
            # Get current taux de change
            try:
                taux = TauxChange.objects.filter(is_active=True).latest('created_at')
                taux_value = taux.taux_usd_fc
            except TauxChange.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun taux de change actif. Veuillez contacter l\'administrateur.'
                }, status=400)
            
            # CHECK AND DEDUCT STOCK
            try:
                stock = Stock.objects.get(
                    branche=request.user.branche,
                    type_carburant=fuel_type
                )
                
                if stock.quantite_actuelle < quantity:
                    return JsonResponse({
                        'success': False,
                        'message': f'❌ Stock insuffisant!\n\nDisponible: {stock.quantite_actuelle} L\nDemandé: {quantity} L'
                    }, status=400)
            except Stock.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': f'❌ Aucun stock configuré pour {fuel_type.nom} dans cette branche'
                }, status=400)
            
            # Create vente
            vente = Vente.objects.create(
                pompiste=pompiste,
                branche=request.user.branche,
                type_carburant=fuel_type,
                quantite=quantity,
                montant_usd=amount_usd,
                montant_fc=amount_fc,
                moyen_paiement=payment_method,
                taux_change=taux_value,
                statut='en_attente',
                abonne=abonne,
                manager=request.user
            )
            
            # DEDUCT FROM STOCK
            stock.quantite_actuelle -= quantity
            stock.save()
            
            # CREATE CONSUMPTION RECORD (without vente field)
            consumption = ConsommationAbonne.objects.create(
                abonne=abonne,
                branche=request.user.branche,
                type_carburant=fuel_type,
                quantite=quantity,
                montant=amount_usd if currency == 'USD' else amount_fc,
                devise=currency
            )
            
            print(f"✅ ConsommationAbonne created: ID={consumption.id}, Abonne={abonne.nom_entreprise}")
            print(f"✅ Stock updated: {fuel_type.nom} - Remaining: {stock.quantite_actuelle} L")
            
            # Update subscriber balance
            balance_message = ''
            
            if abonne.type_abonnement == 'prepaye':
                if currency == 'USD':
                    old_balance = abonne.solde_usd
                    abonne.solde_usd = Decimal(str(abonne.solde_usd)) - amount_usd
                    balance_message = f'Solde USD: ${old_balance:.2f} → ${abonne.solde_usd:.2f}'
                else:
                    old_balance = abonne.solde_fc
                    abonne.solde_fc = Decimal(str(abonne.solde_fc)) - amount_fc
                    balance_message = f'Solde FC: {old_balance:.0f} FC → {abonne.solde_fc:.0f} FC'
                abonne.save()
                
            elif abonne.type_abonnement == 'postpaye':
                if currency == 'USD':
                    old_debt = abs(Decimal(str(abonne.solde_usd)))
                    abonne.solde_usd = Decimal(str(abonne.solde_usd)) - amount_usd
                    new_debt = abs(Decimal(str(abonne.solde_usd)))
                    balance_message = f'Dette USD: ${old_debt:.2f} → ${new_debt:.2f}'
                else:
                    old_debt = abs(Decimal(str(abonne.solde_fc)))
                    abonne.solde_fc = Decimal(str(abonne.solde_fc)) - amount_fc
                    new_debt = abs(Decimal(str(abonne.solde_fc)))
                    balance_message = f'Dette FC: {old_debt:.0f} FC → {new_debt:.0f} FC'
                abonne.save()
                
            elif abonne.type_abonnement == 'credit':
                if currency == 'USD':
                    old_balance = abonne.solde_usd
                    available = Decimal(str(abonne.limite_credit)) + Decimal(str(old_balance))
                    abonne.solde_usd = Decimal(str(abonne.solde_usd)) - amount_usd
                    new_available = Decimal(str(abonne.limite_credit)) + Decimal(str(abonne.solde_usd))
                    balance_message = f'Crédit disponible: ${available:.2f} → ${new_available:.2f}'
                else:
                    old_balance = abonne.solde_fc
                    abonne.solde_fc = Decimal(str(abonne.solde_fc)) - amount_fc
                    balance_message = f'Solde FC: {old_balance:.0f} FC → {abonne.solde_fc:.0f} FC'
                abonne.save()
            
            return JsonResponse({
                'success': True,
                'message': f'''✅ Consommation enregistrée avec succès!

• Abonné: {abonne.nom_entreprise}
• Quantité: {quantity:.2f} L de {fuel_type.nom}
• Montant: {f"${amount_usd:.2f}" if currency == "USD" else f"{amount_fc:.0f} FC"}
• {balance_message}
• Stock restant: {stock.quantite_actuelle:.2f} L

La vente est en attente de validation par le caissier.''',
                'vente_id': vente.id,
                'consumption_id': consumption.id,
                'stock_remaining': float(stock.quantite_actuelle)
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Données JSON invalides'}, status=400)
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Error in RecordConsumptionView: {error_trace}")
            return JsonResponse({'success': False, 'message': f'Erreur: {str(e)}'}, status=500)


# ============================================
# PLANNING (SHIFTS) VIEWS  
# ============================================

class PlanningView(ManagerRequiredMixin, TemplateView):
    """Shift planning page with calendar view"""
    template_name = 'manager/planning.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['branche'] = self.request.user.branche
        
        # Get pompistes for this branch
        pompistes_qs = Pompiste.objects.filter(
            branche=self.request.user.branche,
            is_active=True
        ).order_by('prenom', 'nom')
        
        # Convert to JSON-safe format
        pompistes_list = []
        for p in pompistes_qs:
            pompistes_list.append({
                'id': p.id,
                'prenom': p.prenom,
                'nom': p.nom
            })
        
        context['pompistes'] = json.dumps(pompistes_list)
        return context


class PlanningAPIView(ManagerRequiredMixin, View):
    """Get shift schedule for a given period"""
    
    def get(self, request):
        try:
            branche = request.user.branche
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            
            if not start_date or not end_date:
                # Default to current week
                today = timezone.now().date()
                start_date = today - timedelta(days=today.weekday())
                end_date = start_date + timedelta(days=6)
            else:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            shifts = PlanningShift.objects.filter(
                branche=branche,
                date_shift__gte=start_date,
                date_shift__lte=end_date
            ).select_related('pompiste').order_by('date_shift', 'type_shift')
            
            shifts_data = []
            for shift in shifts:
                shifts_data.append({
                    'id': shift.id,
                    'pompiste_id': shift.pompiste.id if shift.pompiste else None,
                    'pompiste_nom': shift.pompiste.get_full_name() if shift.pompiste else 'N/A',
                    'date_shift': shift.date_shift.strftime('%Y-%m-%d') if shift.date_shift else None,
                    'type_shift': shift.type_shift,
                    'type_shift_display': shift.get_type_shift_display(),
                    'statut': shift.statut,
                    'statut_display': shift.get_statut_display(),
                    'heure_debut': shift.heure_debut.strftime('%H:%M') if shift.heure_debut else None,
                    'heure_fin': shift.heure_fin.strftime('%H:%M') if shift.heure_fin else None,
                    'notes': shift.notes or ''
                })
            
            return JsonResponse({
                'success': True,
                'shifts': shifts_data,
                'period': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                }
            })
            
        except Exception as e:
            import traceback
            print(f"Error in PlanningAPIView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
        
class CreateShiftView(ManagerRequiredMixin, View):
    """Create a new shift"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            branche = request.user.branche
            
            # Validate required fields
            required_fields = ['pompiste_id', 'date_shift', 'type_shift']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Get pompiste
            try:
                pompiste = Pompiste.objects.get(
                    id=data['pompiste_id'],
                    branche=branche,
                    is_active=True
                )
            except Pompiste.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Pompiste introuvable'
                }, status=404)
            
            # Parse date
            try:
                date_shift = datetime.strptime(data['date_shift'], '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': 'Format de date invalide (YYYY-MM-DD requis)'
                }, status=400)
            
            # Validate shift type
            if data['type_shift'] not in ['jour', 'nuit']:
                return JsonResponse({
                    'success': False,
                    'message': 'Type de shift invalide (jour ou nuit)'
                }, status=400)
            
            # Check if shift already exists for this pompiste on this date
            existing = PlanningShift.objects.filter(
                pompiste=pompiste,
                date_shift=date_shift,
                type_shift=data['type_shift']
            ).first()
            
            if existing:
                return JsonResponse({
                    'success': False,
                    'message': f'Ce pompiste a déjà un shift {data["type_shift"]} à cette date'
                }, status=400)
            
            # Set default hours based on shift type
            if data['type_shift'] == 'jour':
                heure_debut = datetime.strptime('06:00', '%H:%M').time()
                heure_fin = datetime.strptime('18:00', '%H:%M').time()
            else:  # nuit
                heure_debut = datetime.strptime('18:00', '%H:%M').time()
                heure_fin = datetime.strptime('06:00', '%H:%M').time()
            
            # Create shift
            shift = PlanningShift.objects.create(
                pompiste=pompiste,
                branche=branche,
                manager=request.user,
                date_shift=date_shift,
                type_shift=data['type_shift'],
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                notes=data.get('notes', ''),
                statut='planifie'
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Shift {shift.get_type_shift_display()} planifié pour {pompiste.get_full_name()}',
                'shift': {
                    'id': shift.id,
                    'pompiste': pompiste.get_full_name(),
                    'date': shift.date_shift.strftime('%d/%m/%Y'),
                    'type': shift.get_type_shift_display()
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            import traceback
            print(f"Error creating shift: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)
        
class UpdateShiftView(ManagerRequiredMixin, View):
    """Update an existing shift"""
    
    def put(self, request, shift_id):
        try:
            data = json.loads(request.body)
            branche = request.user.branche
            
            # Get shift
            try:
                shift = PlanningShift.objects.get(
                    id=shift_id,
                    branche=branche
                )
            except PlanningShift.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Shift introuvable'
                }, status=404)
            
            # Update fields
            if data.get('statut'):
                if data['statut'] in ['planifie', 'confirme', 'annule', 'complete']:
                    shift.statut = data['statut']
            
            if 'notes' in data:
                shift.notes = data['notes']
            
            if data.get('type_shift'):
                if data['type_shift'] in ['jour', 'nuit']:
                    shift.type_shift = data['type_shift']
                    # Update hours based on new type
                    if data['type_shift'] == 'jour':
                        shift.heure_debut = datetime.strptime('06:00', '%H:%M').time()
                        shift.heure_fin = datetime.strptime('18:00', '%H:%M').time()
                    else:
                        shift.heure_debut = datetime.strptime('18:00', '%H:%M').time()
                        shift.heure_fin = datetime.strptime('06:00', '%H:%M').time()
            
            shift.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Shift mis à jour avec succès',
                'shift': {
                    'id': shift.id,
                    'statut': shift.get_statut_display(),
                    'type_shift': shift.get_type_shift_display()
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            import traceback
            print(f"Error updating shift: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)

class DeleteShiftView(ManagerRequiredMixin, View):
    """Delete a shift"""
    
    def delete(self, request, shift_id):
        try:
            branche = request.user.branche
            
            # Get shift
            try:
                shift = PlanningShift.objects.get(
                    id=shift_id,
                    branche=branche
                )
            except PlanningShift.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Shift introuvable'
                }, status=404)
            
            pompiste_name = shift.pompiste.get_full_name() if shift.pompiste else 'N/A'
            date_shift = shift.date_shift.strftime('%d/%m/%Y') if shift.date_shift else 'N/A'
            type_shift = shift.get_type_shift_display()
            
            shift.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Shift {type_shift} du {date_shift} pour {pompiste_name} supprimé'
            })
            
        except Exception as e:
            import traceback
            print(f"Error deleting shift: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)

class AssignShiftAPIView(ManagerRequiredMixin, View):
    """Assign a pompiste to a shift"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            branche = request.user.branche
            
            pompiste = get_object_or_404(Pompiste, id=data['pompiste_id'], branche=branche)
            shift_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            shift_type = data['shift']  # 'jour' or 'nuit'
            
            # Check if shift already exists
            existing_shift = PlanningShift.objects.filter(
                branche=branche,
                date=shift_date,
                shift=shift_type,
                pompiste=pompiste
            ).first()
            
            if existing_shift:
                return JsonResponse({
                    'success': False,
                    'message': 'Ce pompiste est déjà assigné à ce shift'
                }, status=400)
            
            # Create shift
            shift = PlanningShift.objects.create(
                branche=branche,
                pompiste=pompiste,
                date=shift_date,
                shift=shift_type,
                statut='planifie'
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Shift assigné avec succès',
                'data': {
                    'id': shift.id
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class AttendanceAPIView(ManagerRequiredMixin, View):
    """Get attendance records for a date range"""
    
    def get(self, request):
        try:
            branche = request.user.branche
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            
            if not start_date or not end_date:
                today = timezone.now().date()
                start_date = today - timedelta(days=today.weekday())
                end_date = start_date + timedelta(days=6)
            else:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            # Get all shifts in date range for this branch
            shifts = PlanningShift.objects.filter(
                branche=branche,
                date_shift__gte=start_date,
                date_shift__lte=end_date
            )
            
            attendances_data = []
            for shift in shifts:
                # Check if attendance record exists
                attendance = Attendance.objects.filter(shift=shift).first()
                if attendance:
                    attendances_data.append({
                        'id': attendance.id,
                        'shift_id': shift.id,
                        'status': attendance.statut,
                        'reason': attendance.raison or ''
                    })
            
            return JsonResponse({
                'success': True,
                'attendances': attendances_data
            })
            
        except Exception as e:
            import traceback
            print(f"Error in AttendanceAPIView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class MarkAttendanceView(ManagerRequiredMixin, View):
    """Mark attendance for a shift"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            shift_id = data.get('shift_id')
            status = data.get('status')
            
            if not shift_id or not status:
                return JsonResponse({
                    'success': False,
                    'message': 'shift_id et status requis'
                }, status=400)
            
            # Validate status
            if status not in ['present', 'late', 'absent']:
                return JsonResponse({
                    'success': False,
                    'message': 'Statut invalide (present, late, absent)'
                }, status=400)
            
            # Get shift
            try:
                shift = PlanningShift.objects.get(
                    id=shift_id,
                    branche=request.user.branche
                )
            except PlanningShift.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Shift introuvable'
                }, status=404)
            
            # Check if reason is required
            reason = data.get('reason', '')
            if status in ['late', 'absent'] and not reason:
                return JsonResponse({
                    'success': False,
                    'message': 'Raison requise pour retard ou absence'
                }, status=400)
            
            # Create or update attendance record
            attendance, created = Attendance.objects.update_or_create(
                shift=shift,
                defaults={
                    'statut': status,
                    'raison': reason,
                    'marked_by': request.user
                }
            )
            
            action = 'enregistrée' if created else 'mise à jour'
            
            return JsonResponse({
                'success': True,
                'message': f'Présence {action} avec succès',
                'attendance': {
                    'id': attendance.id,
                    'status': attendance.statut
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            import traceback
            print(f"Error marking attendance: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class DownloadPlanningView(ManagerRequiredMixin, View):
    """Download planning as PDF"""
    
    def get(self, request):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from io import BytesIO
            
            # Get parameters
            period = request.GET.get('period', 'week')
            start_date_str = request.GET.get('start_date')
            end_date_str = request.GET.get('end_date')
            scope = request.GET.get('scope', 'all')
            pompiste_id = request.GET.get('pompiste_id')
            
            # Parse dates
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            # For month view, ensure we have the full month
            if period == 'month':
                start_date = datetime(start_date.year, start_date.month, 1).date()
                if start_date.month == 12:
                    end_date = datetime(start_date.year + 1, 1, 1).date() - timedelta(days=1)
                else:
                    end_date = datetime(start_date.year, start_date.month + 1, 1).date() - timedelta(days=1)
            
            branche = request.user.branche
            
            # Get shifts
            shifts = PlanningShift.objects.filter(
                branche=branche,
                date_shift__gte=start_date,
                date_shift__lte=end_date
            ).select_related('pompiste')
            
            # Filter by pompiste if single
            if scope == 'single' and pompiste_id:
                shifts = shifts.filter(pompiste_id=pompiste_id)
                pompiste = Pompiste.objects.get(id=pompiste_id)
                filename = f"planning_{pompiste.prenom}_{pompiste.nom}_{start_date}_{end_date}.pdf"
            else:
                filename = f"planning_tous_{start_date}_{end_date}.pdf"
            
            # Get attendances
            attendance_dict = {}
            for shift in shifts:
                att = Attendance.objects.filter(shift=shift).first()
                if att:
                    attendance_dict[shift.id] = att
            
            # Create PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer, 
                pagesize=landscape(A4), 
                rightMargin=30, 
                leftMargin=30, 
                topMargin=30, 
                bottomMargin=18
            )
            
            elements = []
            styles = getSampleStyleSheet()
            
            # Custom title style
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                textColor=colors.HexColor('#DC2626'),
                spaceAfter=20,
                alignment=1
            )
            
            # Title
            title = f"PLANNING {'HEBDOMADAIRE' if period == 'week' else 'MENSUEL'} - {branche.nom}"
            elements.append(Paragraph(title, title_style))
            elements.append(Paragraph(f"Période: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}", styles['Normal']))
            if scope == 'single':
                elements.append(Paragraph(f"Pompiste: {pompiste.prenom} {pompiste.nom}", styles['Normal']))
            elements.append(Spacer(1, 0.3*inch))
            
            # Build table
            # Get all dates in range
            dates = []
            current = start_date
            while current <= end_date:
                dates.append(current)
                current += timedelta(days=1)
            
            # Get pompistes
            if scope == 'single':
                pompistes = [pompiste]
            else:
                pompistes = Pompiste.objects.filter(
                    branche=branche, 
                    is_active=True
                ).order_by('prenom', 'nom')
            
            # Build table data
            table_data = []
            
            # Header row
            header = ['Pompiste']
            for date in dates:
                header.append(date.strftime('%d/%m'))
            table_data.append(header)
            
            # Pompiste rows
            for pomp in pompistes:
                row = [f"{pomp.prenom} {pomp.nom}"]
                
                for date in dates:
                    day_shifts = shifts.filter(pompiste=pomp, date_shift=date)
                    cell_content = ''
                    
                    for shift in day_shifts:
                        # Shift type
                        shift_text = 'JOUR' if shift.type_shift == 'jour' else 'NUIT'
                        
                        # Attendance
                        att = attendance_dict.get(shift.id)
                        if att:
                            if att.statut == 'present':
                                shift_text += ' [P]'
                            elif att.statut == 'late':
                                shift_text += ' [R]'
                            else:
                                shift_text += ' [A]'
                        
                        cell_content += shift_text + '\n'
                    
                    row.append(cell_content.strip() if cell_content else '')
                
                table_data.append(row)
            
            # Calculate column widths dynamically
            if len(dates) <= 7:
                # Week view
                col_widths = [2.0*inch] + [0.8*inch] * len(dates)
            else:
                # Month view
                col_widths = [1.5*inch] + [0.5*inch] * len(dates)
            
            # Create table
            table = Table(table_data, colWidths=col_widths)
            
            # Style table
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f9fafb')),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 7 if len(dates) > 7 else 9),
                ('ROWBACKGROUNDS', (1, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')])
            ]))
            
            elements.append(table)
            
            # Legend
            elements.append(Spacer(1, 0.3*inch))
            legend_data = [
                ['Type de Shift:', 'JOUR = Service de jour (6h-18h)', 'NUIT = Service de nuit (18h-6h)'],
                ['Présence:', '[P] = Présent', '[R] = Retard', '[A] = Absent']
            ]
            
            legend_table = Table(legend_data, colWidths=[1.5*inch, 2.5*inch, 2.5*inch])
            legend_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9fafb'))
            ]))
            
            elements.append(Paragraph('<b>Légende:</b>', styles['Normal']))
            elements.append(Spacer(1, 0.1*inch))
            elements.append(legend_table)
            
            # Footer
            elements.append(Spacer(1, 0.2*inch))
            footer_text = f"Document généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')} par {request.user.get_full_name()}"
            elements.append(Paragraph(footer_text, styles['Normal']))
            
            # Build PDF
            doc.build(elements)
            
            # Return response
            buffer.seek(0)
            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
        except Exception as e:
            import traceback
            print(f"Error downloading planning: {traceback.format_exc()}")
            return HttpResponse(f"Erreur: {str(e)}", status=500)


# ============================================
# NOTIFICATIONS VIEWS
# ============================================

class NotificationsView(ManagerRequiredMixin, TemplateView):
    """Notifications page"""
    template_name = 'manager/notifications.html'


# ============================================
# PROFILE VIEWS
# ============================================

class ProfilView(ManagerRequiredMixin, TemplateView):
    """Manager profile page"""
    template_name = 'manager/profil.html'


# ============================================
# POMPISTES API
# ============================================

class PompistesListAPIView(ManagerRequiredMixin, View):
    """Returns list of pompistes for this branch"""
    
    def get(self, request):
        try:
            pompistes = Pompiste.objects.filter(
                branche=request.user.branche,
                is_active=True
            ).order_by('prenom', 'nom')
            
            data = []
            for pompiste in pompistes:
                data.append({
                    'id': pompiste.id,
                    'name': f"{pompiste.prenom} {pompiste.nom}",
                    'phone': pompiste.telephone,
                    'shift': pompiste.quart
                })
            
            return JsonResponse({
                'success': True,
                'data': data
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

# ============================================
# DOCUMENTS VIEWS
# ============================================

class DocumentsView(ManagerRequiredMixin, TemplateView):
    """Documents page with filtering"""
    template_name = 'manager/documents.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['branche'] = self.request.user.branche
        
        # Get all active categories
        context['categories'] = DocumentCategory.objects.filter(is_active=True).order_by('nom')
        
        # Get documents (public only for managers) - NO is_active filter on Document
        documents = Document.objects.filter(
            visibilite='public'
        ).select_related('categorie', 'uploaded_by').order_by('-created_at')
        
        # Apply filters
        search = self.request.GET.get('search')
        if search:
            documents = documents.filter(
                Q(titre__icontains=search) | Q(description__icontains=search)
            )
        
        category_id = self.request.GET.get('category_id')
        if category_id:
            documents = documents.filter(categorie_id=category_id)
        
        date_range = self.request.GET.get('date_range')
        if date_range:
            today = timezone.now().date()
            if date_range == 'today':
                documents = documents.filter(created_at__date=today)
            elif date_range == 'week':
                week_start = today - timedelta(days=today.weekday())
                documents = documents.filter(created_at__date__gte=week_start)
            elif date_range == 'month':
                documents = documents.filter(
                    created_at__year=today.year,
                    created_at__month=today.month
                )
            elif date_range == 'year':
                documents = documents.filter(created_at__year=today.year)
        
        context['documents'] = documents[:50]  # Limit to 50
        return context


class DocumentsAPIView(ManagerRequiredMixin, View):
    """API endpoint to get documents"""
    
    def get(self, request):
        try:
            # Get public documents only - NO is_active filter
            documents = Document.objects.filter(
                visibilite='public'
            ).select_related('categorie', 'uploaded_by')
            
            # Apply filters
            search = request.GET.get('search')
            if search:
                documents = documents.filter(
                    Q(titre__icontains=search) | Q(description__icontains=search)
                )
            
            category_id = request.GET.get('category_id')
            if category_id:
                documents = documents.filter(categorie_id=category_id)
            
            # Order and limit
            documents = documents.order_by('-created_at')[:50]
            
            documents_data = []
            for doc in documents:
                documents_data.append({
                    'id': doc.id,
                    'titre': doc.titre,
                    'description': doc.description or '',
                    'categorie': doc.categorie.nom if doc.categorie else 'Sans catégorie',
                    'categorie_id': doc.categorie.id if doc.categorie else None,
                    'visibilite': doc.visibilite,
                    'visibilite_display': doc.get_visibilite_display(),
                    'type_fichier': doc.type_fichier,
                    'taille': doc.taille_fichier,
                    'taille_lisible': doc.get_taille_lisible(),
                    'uploaded_by': doc.uploaded_by.get_full_name() if doc.uploaded_by else 'Système',
                    'created_at': doc.created_at.strftime('%d/%m/%Y %H:%M')
                })
            
            return JsonResponse({
                'success': True,
                'documents': documents_data
            })
            
        except Exception as e:
            import traceback
            print(f"Error in DocumentsAPIView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UploadDocumentView(ManagerRequiredMixin, View):
    """Upload a new public document"""
    
    def post(self, request):
        try:
            titre = request.POST.get('titre')
            description = request.POST.get('description', '')
            categorie_id = request.POST.get('categorie_id')
            fichier = request.FILES.get('fichier')
            
            # Validate required fields
            if not all([titre, categorie_id, fichier]):
                return JsonResponse({
                    'success': False,
                    'message': 'Titre, catégorie et fichier requis'
                }, status=400)
            
            # Get category
            try:
                categorie = DocumentCategory.objects.get(id=categorie_id, is_active=True)
            except DocumentCategory.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Catégorie introuvable'
                }, status=404)
            
            # Validate file size (10MB max)
            if fichier.size > 10 * 1024 * 1024:
                return JsonResponse({
                    'success': False,
                    'message': 'Fichier trop volumineux (max 10MB)'
                }, status=400)
            
            # Validate file type
            allowed_types = [
                'application/pdf',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'image/jpeg',
                'image/png',
                'image/jpg'
            ]
            
            if fichier.content_type not in allowed_types:
                return JsonResponse({
                    'success': False,
                    'message': 'Type de fichier non autorisé. Utilisez PDF, DOC, XLS ou images.'
                }, status=400)
            
            # Create document - CORRECT field name: taille_fichier
            document = Document.objects.create(
                titre=titre,
                description=description,
                categorie=categorie,
                fichier=fichier,
                type_fichier=fichier.content_type,
                taille_fichier=fichier.size,  # CORRECT: taille_fichier not taille
                visibilite='public',
                uploaded_by=request.user
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Document téléversé avec succès',
                'document': {
                    'id': document.id,
                    'titre': document.titre,
                    'categorie': document.categorie.nom if document.categorie else 'Sans catégorie'
                }
            })
            
        except Exception as e:
            import traceback
            print(f"Error uploading document: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class ViewDocumentView(ManagerRequiredMixin, View):
    """View/preview document in browser"""
    
    def get(self, request, document_id):
        try:
            # NO is_active filter
            document = Document.objects.get(id=document_id, visibilite='public')
            
            # Get file path
            file_path = document.fichier.path
            
            # Determine content type
            content_type = document.type_fichier or 'application/octet-stream'
            
            # Open and return file
            with open(file_path, 'rb') as f:
                response = HttpResponse(f.read(), content_type=content_type)
                response['Content-Disposition'] = f'inline; filename="{document.titre}"'
                return response
                
        except Document.DoesNotExist:
            return HttpResponse('Document introuvable', status=404)
        except Exception as e:
            import traceback
            print(f"Error viewing document: {traceback.format_exc()}")
            return HttpResponse(f'Erreur: {str(e)}', status=500)


class DownloadDocumentView(ManagerRequiredMixin, View):
    """Download document"""
    
    def get(self, request, document_id):
        try:
            # NO is_active filter
            document = Document.objects.get(id=document_id, visibilite='public')
            
            # Get file path
            file_path = document.fichier.path
            
            # Determine content type
            content_type = document.type_fichier or 'application/octet-stream'
            
            # Get file extension
            file_extension = os.path.splitext(document.fichier.name)[1]
            
            # Create safe filename
            safe_filename = f"{document.titre}{file_extension}"
            
            # Open and return file
            with open(file_path, 'rb') as f:
                response = HttpResponse(f.read(), content_type=content_type)
                response['Content-Disposition'] = f'attachment; filename="{safe_filename}"'
                return response
                
        except Document.DoesNotExist:
            return HttpResponse('Document introuvable', status=404)
        except Exception as e:
            import traceback
            print(f"Error downloading document: {traceback.format_exc()}")
            return HttpResponse(f'Erreur: {str(e)}', status=500)

@method_decorator(csrf_exempt, name='dispatch')
class ConfirmDeliveryView(View):
    """
    Manager confirms delivery reception
    POST /manager/api/deliveries/<id>/confirm/
    """
    
    def post(self, request, delivery_id):
        try:
            # Only managers can confirm deliveries
            if not hasattr(request.user, 'role') or request.user.role != 'manager':
                return JsonResponse({
                    'success': False,
                    'message': 'Seuls les gestionnaires peuvent confirmer les livraisons'
                }, status=403)
            
            # Get the delivery
            try:
                delivery = LivraisonCarburant.objects.get(id=delivery_id)
            except LivraisonCarburant.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Livraison introuvable'
                }, status=404)
            
            # Check if delivery is for manager's branch
            if delivery.branche != request.user.branche:
                return JsonResponse({
                    'success': False,
                    'message': 'Cette livraison ne concerne pas votre branche'
                }, status=403)
            
            # Check if already confirmed
            if delivery.statut == 'confirmee':
                return JsonResponse({
                    'success': False,
                    'message': 'Cette livraison a déjà été confirmée'
                }, status=400)
            
            # Check if cancelled
            if delivery.statut == 'annulee':
                return JsonResponse({
                    'success': False,
                    'message': 'Cette livraison a été annulée'
                }, status=400)
            
            # Parse request data
            data = json.loads(request.body)
            quantite_recue = Decimal(str(data.get('quantite_recue')))
            observations = data.get('observations', '')
            
            if quantite_recue <= 0:
                return JsonResponse({
                    'success': False,
                    'message': 'La quantité reçue doit être supérieure à 0'
                }, status=400)
            
            # Update delivery with atomic transaction
            with transaction.atomic():
                # Update delivery
                delivery.quantite_recue = quantite_recue
                delivery.ecart_quantite = quantite_recue - delivery.quantite_prevue
                delivery.observations_manager = observations
                delivery.statut = 'confirmee'
                delivery.confirmee_par = request.user
                delivery.date_confirmation = timezone.now()
                delivery.save()
                
                # Update stock based on delivery type
                stock, created = Stock.objects.get_or_create(
                    branche=delivery.branche,
                    type_carburant=delivery.type_carburant,
                    defaults={
                        'quantite_actuelle': 0,
                        'capacite_max': 10000,  # Default capacity
                        'seuil_alerte': 1000     # Default alert threshold
                    }
                )
                
                if delivery.type_livraison in ['propre', 'partenaire_donne']:
                    # Increase stock (we receive fuel)
                    stock.quantite_actuelle += quantite_recue
                elif delivery.type_livraison == 'partenaire_prend':
                    # Decrease stock (partner takes fuel)
                    if stock.quantite_actuelle < quantite_recue:
                        return JsonResponse({
                            'success': False,
                            'message': f'Stock insuffisant. Disponible: {stock.quantite_actuelle}L'
                        }, status=400)
                    stock.quantite_actuelle -= quantite_recue
                
                stock.save()
                
                # Update partner balance if applicable
                if delivery.partenaire and delivery.prix_unitaire:
                    montant = quantite_recue * delivery.prix_unitaire
                    
                    if delivery.type_livraison == 'partenaire_donne':
                        # They give us fuel → we owe them (negative balance)
                        if delivery.devise == 'USD':
                            delivery.partenaire.solde_usd -= montant
                        else:
                            delivery.partenaire.solde_fc -= montant
                    elif delivery.type_livraison == 'partenaire_prend':
                        # They take our fuel → they owe us (positive balance)
                        if delivery.devise == 'USD':
                            delivery.partenaire.solde_usd += montant
                        else:
                            delivery.partenaire.solde_fc += montant
                    
                    delivery.partenaire.save()
                
                # TODO: Send notification to admin if there's a discrepancy
                # if delivery.has_ecart:
                #     send_notification_to_admin(delivery)
            
            return JsonResponse({
                'success': True,
                'message': 'Livraison confirmée avec succès',
                'delivery': {
                    'id': delivery.id,
                    'numero': delivery.numero,
                    'quantite_recue': float(delivery.quantite_recue),
                    'ecart': float(delivery.ecart_quantite) if delivery.ecart_quantite else 0,
                    'nouveau_stock': float(stock.quantite_actuelle)
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except ValueError as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur de validation: {str(e)}'
            }, status=400)
        except Exception as e:
            print(f"Error confirming delivery: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'message': f'Erreur serveur: {str(e)}'
            }, status=500)

# ============================================================
# STOCK API - GET CURRENT STOCK FOR MANAGER'S BRANCH
# ============================================================

class ManagerStockAPIView(View):
    """
    Get stock for manager's branch
    GET /manager/api/stock/
    """
    
    def get(self, request):
        try:
            if not hasattr(request.user, 'branche'):
                return JsonResponse({
                    'success': False,
                    'message': 'Utilisateur sans branche assignée'
                }, status=400)
            
            stocks = Stock.objects.filter(
                branche=request.user.branche
            ).select_related('type_carburant', 'branche')
            
            stocks_data = [{
                'id': stock.id,
                'type_carburant': {
                    'id': stock.type_carburant.id,
                    'nom': stock.type_carburant.nom,
                    'couleur_hex': stock.type_carburant.couleur_hex
                },
                'branche': {
                    'id': stock.branche.id,
                    'nom': stock.branche.nom
                },
                'quantite_actuelle': float(stock.quantite_actuelle),
                'capacite_max': float(stock.capacite_max),
                'seuil_alerte': float(stock.seuil_alerte),
                'prix_achat': float(stock.prix_achat) if stock.prix_achat else None
            } for stock in stocks]
            
            return JsonResponse({
                'success': True,
                'stocks': stocks_data
            })
            
        except Exception as e:
            print(f"Error loading stock: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================================
# STOCK MOVEMENTS API
# ============================================================

class ManagerStockMovementsView(View):
    """
    Get stock movements history for manager's branch
    GET /manager/api/stock/movements/
    """
    
    def get(self, request):
        try:
            if not hasattr(request.user, 'branche'):
                return JsonResponse({
                    'success': False,
                    'message': 'Utilisateur sans branche assignée'
                }, status=400)
            
            # Get deliveries (incoming stock)
            deliveries = LivraisonCarburant.objects.filter(
                branche=request.user.branche,
                statut='confirmee'
            ).select_related('type_carburant', 'confirmee_par').order_by('-date_confirmation')[:15]
            
            movements = []
            
            for delivery in deliveries:
                movements.append({
                    'date': delivery.date_confirmation.strftime('%d/%m/%Y %H:%M') if delivery.date_confirmation else '-',
                    'type': 'livraison',
                    'carburant': delivery.type_carburant.nom,
                    'quantite': float(delivery.quantite_recue),
                    'reference': delivery.numero,
                    'actor': delivery.confirmee_par.get_full_name() if delivery.confirmee_par else '-'
                })
            
            # TODO: Add sales movements here when ventes are linked to stock
            
            return JsonResponse({
                'success': True,
                'movements': movements,
                'pagination': {
                    'total_items': len(movements),
                    'current_page': 1,
                    'has_previous': False,
                    'has_next': False
                }
            })
            
        except Exception as e:
            print(f"Error loading movements: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================================
# PENDING DELIVERIES - WITH ALL FIELDS INCLUDING TRANSPORT
# ============================================================

class ManagerPendingDeliveriesView(View):
    """
    Get pending deliveries for manager's branch
    GET /manager/api/deliveries/pending/
    """
    
    def get(self, request):
        try:
            if not hasattr(request.user, 'branche'):
                return JsonResponse({
                    'success': False,
                    'message': 'Utilisateur sans branche assignée'
                }, status=400)
            
            # Get deliveries that are planned or in transit for this branch
            deliveries = LivraisonCarburant.objects.filter(
                branche=request.user.branche,
                statut__in=['planifiee', 'en_transit', 'livree']
            ).select_related(
                'type_carburant', 
                'branche', 
                'partenaire', 
                'planifiee_par'
            ).order_by('-date_prevue')
            
            deliveries_data = []
            for d in deliveries:
                deliveries_data.append({
                    'id': d.id,
                    'numero': d.numero,
                    'type_livraison': d.type_livraison,
                    'statut': d.statut,
                    'type_carburant': {
                        'id': d.type_carburant.id,
                        'nom': d.type_carburant.nom
                    },
                    'branche': {
                        'id': d.branche.id,
                        'nom': d.branche.nom
                    },
                    'partenaire': {
                        'id': d.partenaire.id,
                        'nom': d.partenaire.nom
                    } if d.partenaire else None,
                    'quantite_prevue': float(d.quantite_prevue),
                    'quantite_recue': float(d.quantite_recue) if d.quantite_recue else None,
                    'prix_unitaire': float(d.prix_unitaire) if d.prix_unitaire else None,
                    'devise': d.devise,
                    'montant_total': float(d.montant_total) if d.montant_total else 0,
                    'date_prevue': d.date_prevue.strftime('%d/%m/%Y') if d.date_prevue else None,
                    'date_livraison': d.date_livraison.strftime('%d/%m/%Y %H:%M') if d.date_livraison else None,
                    # TRANSPORT INFO - THIS WAS MISSING!
                    'bon_livraison': d.bon_livraison or None,
                    'transporteur': d.transporteur or None,
                    'immatriculation': d.immatriculation or None,
                    # OBSERVATIONS
                    'observations_admin': d.observations_admin or None,
                    'observations_manager': d.observations_manager or None,
                    # WHO
                    'planifiee_par': d.planifiee_par.get_full_name() if d.planifiee_par else None,
                    'can_confirm': True
                })
            
            return JsonResponse({
                'success': True,
                'deliveries': deliveries_data
            })
            
        except Exception as e:
            print(f"Error loading pending deliveries: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)