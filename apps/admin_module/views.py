from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, Count, F, Avg, Max, Min  # FIXED: Import F directly
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import datetime, timedelta
from decimal import Decimal
import json
import csv
import io

# PDF Generation imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from apps.core.models import (
    User, Branche, TauxChange, TypeCarburant, CategorieDepense,
    Vente, Depense, Stock, Pompiste, Abonne, ConsommationAbonne,
    Document, DocumentCategory, Notification, Livraison, MoyenPaiement,
    PaiementSalaire
)


class AdminRequiredMixin(UserPassesTestMixin):
    """Mixin to restrict access to admin users only"""
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == 'admin'
    
    def handle_no_permission(self):
        messages.error(self.request, "Accès réservé aux administrateurs.")
        return redirect('authentication:login')
    
class AdminContextMixin:
    """Mixin to add common context data for admin templates"""
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # All branches for selector
        context['all_branches'] = Branche.objects.filter(is_active=True).order_by('nom')
        
        # Selected branch from query param
        branche_id = self.request.GET.get('branche_id', 'all')
        context['selected_branch_id'] = branche_id
        if branche_id and branche_id != 'all':
            try:
                context['selected_branch'] = Branche.objects.get(id=branche_id)
            except Branche.DoesNotExist:
                context['selected_branch'] = None
        else:
            context['selected_branch'] = None
        
        # Unread notifications count
        context['unread_notifications'] = Notification.objects.filter(
            destinataire=self.request.user,
            lu=False
        ).count()
        
        # Current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        context['current_rate'] = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        return context

class AdminDashboardView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Main Admin Dashboard - displays KPIs, charts, recent transactions"""
    template_name = 'admin/dashboard.html'


class BranchesListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """List all branches with performance metrics"""
    template_name = 'admin/branches.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all branches with related data
        branches = Branche.objects.all().prefetch_related('pompiste_set', 'stock_set')
        
        # Add stock alert status to each branch
        for branch in branches:
            branch.has_stock_alert = branch.stock_set.filter(
                quantite_actuelle__lte=F('seuil_alerte')
            ).exists()
        
        context['branches'] = branches
        
        # Get unique provinces for filter
        context['provinces'] = Branche.objects.values_list('province', flat=True).distinct()
        
        return context
    
class BranchDetailView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Detailed view of a single branch"""
    template_name = 'admin/branch_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        branch_id = self.kwargs.get('branch_id')
        
        branch = get_object_or_404(Branche, id=branch_id)
        context['branch'] = branch
        
        # Branch statistics
        today = timezone.now().date()
        month_start = today.replace(day=1)
        
        # Sales this month
        sales = Vente.objects.filter(
            branche=branch,
            created_at__date__gte=month_start,
            statut='validee'
        )
        context['total_sales_usd'] = sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        context['total_sales_fc'] = sales.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        context['sales_count'] = sales.count()
        
        # Expenses this month
        expenses = Depense.objects.filter(
            branche=branch,
            created_at__date__gte=month_start,
            statut='approuvee'
        )
        context['total_expenses_usd'] = expenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        context['total_expenses_fc'] = expenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        # Stock status
        context['stocks'] = Stock.objects.filter(branche=branch).select_related('type_carburant')
        
        # Employees
        context['pompistes'] = Pompiste.objects.filter(branche=branch, is_active=True)
        context['users'] = User.objects.filter(branche=branch, is_active=True)
        
        # Recent sales
        context['recent_sales'] = Vente.objects.filter(
            branche=branch
        ).select_related('pompiste', 'type_carburant').order_by('-created_at')[:10]
        
        return context
    
class VentesListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """List all sales with filters"""
    template_name = 'admin/ventes.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter parameters
        branche_id = self.request.GET.get('branche_id', 'all')
        period = self.request.GET.get('period', 'month')
        status = self.request.GET.get('status', 'all')
        carburant_id = self.request.GET.get('carburant_id', 'all')
        
        # Base queryset
        ventes = Vente.objects.select_related(
            'branche', 'pompiste', 'manager', 'caissier', 
            'type_carburant', 'moyen_paiement', 'abonne'
        )
        
        # Apply filters
        if branche_id and branche_id != 'all':
            ventes = ventes.filter(branche_id=branche_id)
        
        today = timezone.now().date()
        if period == 'today':
            ventes = ventes.filter(created_at__date=today)
        elif period == 'week':
            ventes = ventes.filter(created_at__date__gte=today - timedelta(days=7))
        elif period == 'month':
            ventes = ventes.filter(created_at__date__gte=today - timedelta(days=30))
        
        if status and status != 'all':
            ventes = ventes.filter(statut=status)
        
        if carburant_id and carburant_id != 'all':
            ventes = ventes.filter(type_carburant_id=carburant_id)
        
        context['ventes'] = ventes.order_by('-created_at')[:100]
        context['ventes_count'] = ventes.count()
        
        # Summary statistics
        context['total_usd'] = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        context['total_fc'] = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        context['manquants_count'] = ventes.filter(statut='manquant').count()
        context['total_manquant_usd'] = ventes.filter(statut='manquant').aggregate(
            Sum('manquant_usd'))['manquant_usd__sum'] or 0
        
        # Filter options
        context['types_carburant'] = TypeCarburant.objects.filter(is_active=True)
        context['statuts'] = [
            ('all', 'Tous les statuts'),
            ('en_attente', 'En attente'),
            ('validee', 'Validées'),
            ('manquant', 'Manquants'),
            ('rejetee', 'Rejetées'),
        ]
        
        # Current filters
        context['current_filters'] = {
            'branche_id': branche_id,
            'period': period,
            'status': status,
            'carburant_id': carburant_id,
        }
        
        return context
    
class DepensesListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """List all expenses with filters and categories"""
    template_name = 'admin/depenses.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter parameters
        branche_id = self.request.GET.get('branche_id', 'all')
        categorie_id = self.request.GET.get('categorie_id', 'all')
        devise = self.request.GET.get('devise', 'all')
        period = self.request.GET.get('period', 'month')
        
        # Base queryset
        depenses = Depense.objects.select_related('branche', 'categorie', 'created_by')
        
        # Apply filters
        if branche_id and branche_id != 'all':
            depenses = depenses.filter(branche_id=branche_id)
        
        if categorie_id and categorie_id != 'all':
            depenses = depenses.filter(categorie_id=categorie_id)
        
        if devise and devise != 'all':
            depenses = depenses.filter(devise=devise)
        
        today = timezone.now().date()
        if period == 'today':
            depenses = depenses.filter(created_at__date=today)
        elif period == 'week':
            depenses = depenses.filter(created_at__date__gte=today - timedelta(days=7))
        elif period == 'month':
            depenses = depenses.filter(created_at__date__gte=today - timedelta(days=30))
        
        context['depenses'] = depenses.order_by('-created_at')[:100]
        context['depenses_count'] = depenses.count()
        
        # Summary by currency
        context['total_usd'] = depenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        context['total_fc'] = depenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        # Summary by category
        context['by_category'] = depenses.values('categorie__nom').annotate(
            total=Sum('montant'),
            count=Count('id')
        ).order_by('-total')
        
        # Filter options
        context['categories'] = CategorieDepense.objects.filter(is_active=True)
        
        # Pending category requests
        context['pending_categories'] = CategorieDepense.objects.filter(is_active=False)
        
        return context

class CarburantsListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Global stock view and fuel types management"""
    template_name = 'admin/carburants.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        branche_id = self.request.GET.get('branche_id', 'all')
        
        # Stock items
        stocks = Stock.objects.select_related('branche', 'type_carburant')
        
        if branche_id and branche_id != 'all':
            stocks = stocks.filter(branche_id=branche_id)
        
        context['stocks'] = stocks.order_by('branche__nom', 'type_carburant__nom')
        
        # Stock summary
        context['total_stock'] = stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0
        context['total_capacity'] = stocks.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0
        context['alerts_count'] = stocks.filter(quantite_actuelle__lte=F('seuil_alerte')).count()
        
        # Fuel types
        context['types_carburant'] = TypeCarburant.objects.all()
        
        # Recent deliveries
        context['recent_livraisons'] = Livraison.objects.select_related(
            'branche', 'type_carburant', 'manager'
        ).order_by('-created_at')[:20]
        
        # Stock by fuel type (aggregated)
        context['stock_by_fuel'] = stocks.values('type_carburant__nom', 'type_carburant__couleur_hex').annotate(
            total_quantity=Sum('quantite_actuelle'),
            total_capacity=Sum('capacite_max'),
            branches_count=Count('branche', distinct=True)
        )
        
        return context


class AdminDashboardView(AdminRequiredMixin, TemplateView):
    """Vue principale du dashboard administrateur"""
    template_name = 'admin/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['all_branches'] = Branche.objects.filter(is_active=True)
        context['types_carburant'] = TypeCarburant.objects.filter(is_active=True)
        context['categories_depense'] = CategorieDepense.objects.filter(is_active=True)
        return context


class DashboardStatsAPIView(AdminRequiredMixin, View):
    """API pour les statistiques du dashboard admin"""
    
    def get(self, request):
        # Get date filters
        period = request.GET.get('period', 'today')
        branche_id = request.GET.get('branche_id')
        devise = request.GET.get('devise', 'USD')
        
        today = timezone.now().date()
        
        # Calculate date range based on period
        if period == 'today':
            start_date = today
            end_date = today
        elif period == 'week':
            start_date = today - timedelta(days=7)
            end_date = today
        elif period == 'month':
            start_date = today - timedelta(days=30)
            end_date = today
        elif period == 'year':
            start_date = today - timedelta(days=365)
            end_date = today
        else:
            # Custom period
            try:
                start_date = datetime.strptime(request.GET.get('start_date', str(today)), '%Y-%m-%d').date()
                end_date = datetime.strptime(request.GET.get('end_date', str(today)), '%Y-%m-%d').date()
            except ValueError:
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
        
        # Filter by branch if specified
        if branche_id and branche_id != 'all':
            vente_filters['branche_id'] = branche_id
            depense_filters['branche_id'] = branche_id
        
        # Calculate sales totals
        ventes = Vente.objects.filter(**vente_filters)
        total_sales_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or Decimal('0')
        total_sales_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or Decimal('0')
        
        # Calculate expenses totals
        depenses_usd = Depense.objects.filter(**depense_filters, devise='USD')
        depenses_fc = Depense.objects.filter(**depense_filters, devise='FC')
        
        total_expenses_usd = depenses_usd.aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        total_expenses_fc = depenses_fc.aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        
        # Get current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        current_rate_value = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        # Calculate Forex Impact
        forex_data = self._calculate_forex_impact(ventes, current_rate_value)
        
        # Calculate stock totals - FIXED: Using F() correctly now
        stock_filters = {}
        if branche_id and branche_id != 'all':
            stock_filters['branche_id'] = branche_id
            
        total_stock = Stock.objects.filter(**stock_filters).aggregate(
            Sum('quantite_actuelle')
        )['quantite_actuelle__sum'] or 0
        
        # Determine stock status - FIXED: Using F() from django.db.models
        low_stock_items = Stock.objects.filter(
            **stock_filters,
            quantite_actuelle__lte=F('seuil_alerte')
        ).count()
        
        if low_stock_items > 0:
            stock_status = f"Alerte ({low_stock_items} items)"
            stock_status_class = 'danger'
        else:
            stock_status = "Normal"
            stock_status_class = 'success'
        
        # Count active branches
        active_branches = Branche.objects.filter(is_active=True).count()
        
        # Calculate trends (comparison with previous period)
        period_days = (end_date - start_date).days + 1
        prev_start = start_date - timedelta(days=period_days)
        prev_end = start_date - timedelta(days=1)
        
        prev_vente_filters = {
            'created_at__date__gte': prev_start,
            'created_at__date__lte': prev_end,
            'statut': 'validee'
        }
        if branche_id and branche_id != 'all':
            prev_vente_filters['branche_id'] = branche_id
        
        prev_ventes = Vente.objects.filter(**prev_vente_filters)
        prev_total_usd = prev_ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or Decimal('0')
        prev_total_fc = prev_ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or Decimal('0')
        
        # Calculate trend percentages
        sales_trend_usd = self._calculate_trend(total_sales_usd, prev_total_usd)
        sales_trend_fc = self._calculate_trend(total_sales_fc, prev_total_fc)
        
        # Count manquants (shortages)
        manquants_count = Vente.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            statut='manquant'
        )
        if branche_id and branche_id != 'all':
            manquants_count = manquants_count.filter(branche_id=branche_id)
        manquants_count = manquants_count.count()
        
        total_manquant_usd = Vente.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            statut='manquant'
        ).aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or Decimal('0')
        
        total_manquant_fc = Vente.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            statut='manquant'
        ).aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or Decimal('0')
        
        # Sales by fuel type
        sales_by_fuel = ventes.values('type_carburant__nom', 'type_carburant__couleur_hex').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            total_quantity=Sum('quantite'),
            count=Count('id')
        ).order_by('-total_usd')
        
        # Recent transactions
        recent_transactions = ventes.select_related(
            'branche', 'pompiste', 'type_carburant'
        ).order_by('-created_at')[:10]
        
        recent_data = []
        for vente in recent_transactions:
            recent_data.append({
                'id': vente.id,
                'branche': vente.branche.nom if vente.branche else 'N/A',
                'pompiste': vente.pompiste.get_full_name() if vente.pompiste else 'N/A',
                'carburant': vente.type_carburant.nom if vente.type_carburant else 'N/A',
                'quantite': str(vente.quantite),
                'montant_usd': str(vente.montant_usd),
                'montant_fc': str(vente.montant_fc),
                'date': vente.created_at.strftime('%d/%m/%Y %H:%M')
            })
        
        return JsonResponse({
            'period': {
                'start': start_date.strftime('%d/%m/%Y'),
                'end': end_date.strftime('%d/%m/%Y'),
                'type': period
            },
            'sales': {
                'total_usd': str(total_sales_usd),
                'total_fc': str(total_sales_fc),
                'trend_usd': sales_trend_usd,
                'trend_fc': sales_trend_fc,
                'count': ventes.count(),
                'by_fuel': list(sales_by_fuel)
            },
            'expenses': {
                'total_usd': str(total_expenses_usd),
                'total_fc': str(total_expenses_fc)
            },
            'profit': {
                'usd': str(total_sales_usd - total_expenses_usd),
                'fc': str(total_sales_fc - total_expenses_fc)
            },
            'forex': forex_data,
            'stock': {
                'total': float(total_stock),
                'status': stock_status,
                'status_class': stock_status_class,
                'alerts': low_stock_items
            },
            'manquants': {
                'count': manquants_count,
                'total_usd': str(total_manquant_usd),
                'total_fc': str(total_manquant_fc)
            },
            'branches': {
                'active': active_branches
            },
            'exchange_rate': {
                'current': str(current_rate_value),
                'date': current_rate.date_effective.strftime('%d/%m/%Y') if current_rate else None
            },
            'recent_transactions': recent_data
        })
    
    def _calculate_trend(self, current, previous):
        """Calculate percentage change between current and previous period"""
        if previous == 0:
            if current > 0:
                return {'value': 100, 'direction': 'up'}
            return {'value': 0, 'direction': 'stable'}
        
        change = ((current - previous) / previous) * 100
        direction = 'up' if change > 0 else 'down' if change < 0 else 'stable'
        return {'value': round(abs(float(change)), 1), 'direction': direction}
    
    def _calculate_forex_impact(self, ventes, current_rate):
        """Calculate detailed forex impact for sales"""
        forex_impact = {
            'total_gain_loss_usd': Decimal('0'),
            'by_carburant': [],
            'details': []
        }
        
        # Group by fuel type and calculate forex impact
        for vente in ventes:
            if vente.taux_change and vente.taux_change != current_rate:
                # Calculate what FC should be at current rate vs what was recorded
                expected_fc = vente.montant_usd * current_rate
                actual_fc = vente.montant_fc
                
                # Forex impact in FC
                fc_difference = actual_fc - expected_fc
                
                # Convert to USD for reporting
                usd_impact = fc_difference / current_rate if current_rate > 0 else Decimal('0')
                
                forex_impact['total_gain_loss_usd'] += usd_impact
                
                forex_impact['details'].append({
                    'vente_id': vente.id,
                    'date': vente.created_at.strftime('%d/%m/%Y'),
                    'taux_applique': str(vente.taux_change),
                    'taux_actuel': str(current_rate),
                    'montant_usd': str(vente.montant_usd),
                    'montant_fc': str(vente.montant_fc),
                    'impact_usd': str(round(usd_impact, 2))
                })
        
        # Aggregate by fuel type
        fuel_forex = ventes.values('type_carburant__nom').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            avg_rate=Avg('taux_change')
        )
        
        for fuel in fuel_forex:
            expected_fc = fuel['total_usd'] * current_rate
            actual_fc = fuel['total_fc'] or Decimal('0')
            impact = (actual_fc - expected_fc) / current_rate if current_rate > 0 else Decimal('0')
            
            forex_impact['by_carburant'].append({
                'carburant': fuel['type_carburant__nom'],
                'total_usd': str(fuel['total_usd'] or 0),
                'total_fc': str(fuel['total_fc'] or 0),
                'taux_moyen': str(round(fuel['avg_rate'] or current_rate, 2)),
                'impact_usd': str(round(impact, 2)),
                'impact_type': 'gain' if impact > 0 else 'loss' if impact < 0 else 'neutral'
            })
        
        forex_impact['total_gain_loss_usd'] = str(round(forex_impact['total_gain_loss_usd'], 2))
        forex_impact['impact_type'] = 'gain' if float(forex_impact['total_gain_loss_usd']) > 0 else 'loss' if float(forex_impact['total_gain_loss_usd']) < 0 else 'neutral'
        
        return forex_impact


class ForexAnalysisView(AdminRequiredMixin, View):
    """Vue détaillée de l'analyse Forex"""
    
    def get(self, request):
        period = request.GET.get('period', 'month')
        branche_id = request.GET.get('branche_id')
        
        today = timezone.now().date()
        
        if period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        elif period == 'year':
            start_date = today - timedelta(days=365)
        else:
            start_date = today - timedelta(days=30)
        
        # Get current rate
        current_rate = TauxChange.get_current_rate()
        
        # Get historical rates
        historical_rates = TauxChange.objects.filter(
            date_effective__date__gte=start_date
        ).order_by('date_effective')
        
        rates_data = [{
            'date': rate.date_effective.strftime('%d/%m/%Y'),
            'taux': str(rate.taux_usd_fc),
            'created_by': rate.created_by.get_full_name() if rate.created_by else 'System'
        } for rate in historical_rates]
        
        # Get sales with forex impact
        vente_filters = {
            'created_at__date__gte': start_date,
            'statut': 'validee'
        }
        if branche_id and branche_id != 'all':
            vente_filters['branche_id'] = branche_id
        
        ventes = Vente.objects.filter(**vente_filters).select_related(
            'branche', 'type_carburant'
        )
        
        # Calculate forex impact by branch
        branch_forex = {}
        for vente in ventes:
            branch_name = vente.branche.nom if vente.branche else 'N/A'
            if branch_name not in branch_forex:
                branch_forex[branch_name] = {
                    'total_usd': Decimal('0'),
                    'total_fc': Decimal('0'),
                    'expected_fc': Decimal('0'),
                    'impact': Decimal('0')
                }
            
            branch_forex[branch_name]['total_usd'] += vente.montant_usd
            branch_forex[branch_name]['total_fc'] += vente.montant_fc
            branch_forex[branch_name]['expected_fc'] += vente.montant_usd * current_rate
        
        # Calculate impact for each branch
        branch_summary = []
        total_impact = Decimal('0')
        
        for branch_name, data in branch_forex.items():
            impact = data['total_fc'] - data['expected_fc']
            impact_usd = impact / current_rate if current_rate > 0 else Decimal('0')
            total_impact += impact_usd
            
            branch_summary.append({
                'branche': branch_name,
                'total_usd': str(data['total_usd']),
                'total_fc': str(data['total_fc']),
                'expected_fc': str(data['expected_fc']),
                'impact_fc': str(impact),
                'impact_usd': str(round(impact_usd, 2)),
                'impact_type': 'gain' if impact_usd > 0 else 'loss' if impact_usd < 0 else 'neutral'
            })
        
        # Forex impact by fuel type
        fuel_forex = ventes.values('type_carburant__nom', 'type_carburant__couleur_hex').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            avg_rate=Avg('taux_change'),
            transaction_count=Count('id')
        )
        
        fuel_summary = []
        for fuel in fuel_forex:
            expected_fc = (fuel['total_usd'] or Decimal('0')) * current_rate
            actual_fc = fuel['total_fc'] or Decimal('0')
            impact = actual_fc - expected_fc
            impact_usd = impact / current_rate if current_rate > 0 else Decimal('0')
            
            fuel_summary.append({
                'carburant': fuel['type_carburant__nom'],
                'couleur': fuel['type_carburant__couleur_hex'],
                'transactions': fuel['transaction_count'],
                'total_usd': str(fuel['total_usd'] or 0),
                'total_fc': str(fuel['total_fc'] or 0),
                'taux_moyen': str(round(fuel['avg_rate'] or current_rate, 2)),
                'expected_fc': str(expected_fc),
                'impact_fc': str(impact),
                'impact_usd': str(round(impact_usd, 2)),
                'impact_type': 'gain' if impact_usd > 0 else 'loss' if impact_usd < 0 else 'neutral'
            })
        
        return JsonResponse({
            'current_rate': str(current_rate),
            'period': {
                'start': start_date.strftime('%d/%m/%Y'),
                'end': today.strftime('%d/%m/%Y')
            },
            'historical_rates': rates_data,
            'summary': {
                'total_impact_usd': str(round(total_impact, 2)),
                'impact_type': 'gain' if total_impact > 0 else 'loss' if total_impact < 0 else 'neutral',
                'transactions_analyzed': ventes.count()
            },
            'by_branch': branch_summary,
            'by_fuel': fuel_summary
        })


class UpdateExchangeRateView(AdminRequiredMixin, View):
    """Mise à jour du taux de change (Admin uniquement)"""
    
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
                    raise ValueError("Rate must be positive")
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Taux de change invalide'
                })
            
            # Deactivate previous rate
            TauxChange.objects.filter(is_active=True).update(is_active=False)
            
            # Create new rate
            new_taux = TauxChange.objects.create(
                taux_usd_fc=new_rate,
                date_effective=timezone.now(),
                created_by=request.user,
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Taux de change mis à jour: 1 USD = {new_rate} FC',
                'rate': {
                    'id': new_taux.id,
                    'taux': str(new_taux.taux_usd_fc),
                    'date': new_taux.date_effective.strftime('%d/%m/%Y %H:%M'),
                    'created_by': request.user.get_full_name()
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
                'message': f'Erreur: {str(e)}'
            })


class ExchangeRateHistoryView(AdminRequiredMixin, View):
    """Historique des taux de change"""
    
    def get(self, request):
        limit = int(request.GET.get('limit', 50))
        
        rates = TauxChange.objects.select_related('created_by').order_by('-date_effective')[:limit]
        
        rates_data = [{
            'id': rate.id,
            'taux': str(rate.taux_usd_fc),
            'date_effective': rate.date_effective.strftime('%d/%m/%Y %H:%M'),
            'created_by': rate.created_by.get_full_name() if rate.created_by else 'System',
            'is_active': rate.is_active
        } for rate in rates]
        
        return JsonResponse({
            'rates': rates_data,
            'count': len(rates_data)
        })


class MissingsSalesView(AdminRequiredMixin, View):
    """Vue des ventes avec manquants"""
    
    def get(self, request):
        branche_id = request.GET.get('branche_id')
        period = request.GET.get('period', 'month')
        
        today = timezone.now().date()
        
        if period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        else:
            start_date = today - timedelta(days=30)
        
        filters = {
            'created_at__date__gte': start_date,
            'statut': 'manquant'
        }
        
        if branche_id and branche_id != 'all':
            filters['branche_id'] = branche_id
        
        missing_sales = Vente.objects.filter(**filters).select_related(
            'branche', 'pompiste', 'manager', 'caissier', 'type_carburant'
        )
        
        # Summary statistics
        total_manquant_usd = missing_sales.aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or Decimal('0')
        total_manquant_fc = missing_sales.aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or Decimal('0')
        
        # Group by branch
        branches_summary = {}
        for sale in missing_sales:
            branch_code = sale.branche.code if sale.branche else 'N/A'
            if branch_code not in branches_summary:
                branches_summary[branch_code] = {
                    'nom': sale.branche.nom if sale.branche else 'N/A',
                    'count': 0,
                    'total_usd': 0,
                    'total_fc': 0
                }
            branches_summary[branch_code]['count'] += 1
            branches_summary[branch_code]['total_usd'] += float(sale.manquant_usd)
            branches_summary[branch_code]['total_fc'] += float(sale.manquant_fc)
        
        # Group by pompiste
        pompistes_summary = {}
        for sale in missing_sales:
            if sale.pompiste:
                pompiste_name = sale.pompiste.get_full_name()
                if pompiste_name not in pompistes_summary:
                    pompistes_summary[pompiste_name] = {
                        'branche': sale.branche.nom if sale.branche else 'N/A',
                        'count': 0,
                        'total_usd': 0,
                        'total_fc': 0
                    }
                pompistes_summary[pompiste_name]['count'] += 1
                pompistes_summary[pompiste_name]['total_usd'] += float(sale.manquant_usd)
                pompistes_summary[pompiste_name]['total_fc'] += float(sale.manquant_fc)
        
        # Detailed list
        missing_data = []
        for sale in missing_sales.order_by('-created_at')[:100]:
            missing_data.append({
                'id': sale.id,
                'branche': sale.branche.nom if sale.branche else 'N/A',
                'pompiste': sale.pompiste.get_full_name() if sale.pompiste else 'N/A',
                'manager': sale.manager.get_full_name() if sale.manager else 'N/A',
                'caissier': sale.caissier.get_full_name() if sale.caissier else 'N/A',
                'type_carburant': sale.type_carburant.nom if sale.type_carburant else 'N/A',
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
                'branches_summary': branches_summary,
                'pompistes_summary': pompistes_summary
            },
            'missing_sales': missing_data
        })


class GlobalStockView(AdminRequiredMixin, View):
    """Vue globale des stocks"""
    
    def get(self, request):
        branche_id = request.GET.get('branche_id')
        
        filters = {}
        if branche_id and branche_id != 'all':
            filters['branche_id'] = branche_id
        
        # Get all stock items
        stock_items = Stock.objects.filter(**filters).select_related(
            'branche', 'type_carburant'
        ).order_by('branche__nom', 'type_carburant__nom')
        
        # Group by fuel type for summary
        fuel_summary = {}
        branch_summary = {}
        
        total_stock = 0
        total_capacity = 0
        alert_count = 0
        
        stock_data = []
        
        for stock in stock_items:
            # Individual stock item - FIXED: Using proper comparison
            is_alert = stock.quantite_actuelle <= stock.seuil_alerte
            if is_alert:
                alert_count += 1
            
            total_stock += float(stock.quantite_actuelle)
            total_capacity += float(stock.capacite_max)
            
            stock_data.append({
                'id': stock.id,
                'branche': stock.branche.nom if stock.branche else 'N/A',
                'branche_code': stock.branche.code if stock.branche else 'N/A',
                'type_carburant': stock.type_carburant.nom if stock.type_carburant else 'N/A',
                'carburant_couleur': stock.type_carburant.couleur_hex if stock.type_carburant else '#000000',
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
            if stock.type_carburant:
                fuel_name = stock.type_carburant.nom
                if fuel_name not in fuel_summary:
                    fuel_summary[fuel_name] = {
                        'couleur': stock.type_carburant.couleur_hex,
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
            if stock.branche:
                branch_name = stock.branche.nom
                if branch_name not in branch_summary:
                    branch_summary[branch_name] = {
                        'code': stock.branche.code,
                        'total_quantity': 0,
                        'total_capacity': 0,
                        'fuel_types': 0,
                        'alerts': 0
                    }
                
                branch_summary[branch_name]['total_quantity'] += float(stock.quantite_actuelle)
                branch_summary[branch_name]['total_capacity'] += float(stock.capacite_max)
                branch_summary[branch_name]['fuel_types'] += 1
                if is_alert:
                    branch_summary[branch_name]['alerts'] += 1
        
        return JsonResponse({
            'summary': {
                'total_stock': round(total_stock, 2),
                'total_capacity': round(total_capacity, 2),
                'fill_percentage': round((total_stock / total_capacity * 100), 1) if total_capacity > 0 else 0,
                'total_branches': len(branch_summary),
                'total_fuel_types': len(fuel_summary),
                'alert_count': alert_count
            },
            'fuel_summary': fuel_summary,
            'branch_summary': branch_summary,
            'stock_items': stock_data
        })


class StockAlertsView(AdminRequiredMixin, View):
    """Vue des alertes de stock"""
    
    def get(self, request):
        # Get stock items with alerts - FIXED: Using F() correctly
        alert_stocks = Stock.objects.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).select_related('branche', 'type_carburant').order_by('quantite_actuelle')
        
        alerts_data = []
        for stock in alert_stocks:
            severity = 'critical' if stock.quantite_actuelle <= (stock.seuil_alerte * Decimal('0.5')) else 'warning'
            
            alerts_data.append({
                'id': stock.id,
                'branche': stock.branche.nom if stock.branche else 'N/A',
                'branche_code': stock.branche.code if stock.branche else 'N/A',
                'type_carburant': stock.type_carburant.nom if stock.type_carburant else 'N/A',
                'carburant_couleur': stock.type_carburant.couleur_hex if stock.type_carburant else '#000000',
                'quantite_actuelle': str(stock.quantite_actuelle),
                'seuil_alerte': str(stock.seuil_alerte),
                'capacite_max': str(stock.capacite_max),
                'pourcentage_rempli': round(stock.pourcentage_rempli, 1),
                'severity': severity,
                'updated_at': stock.updated_at.strftime('%d/%m/%Y %H:%M')
            })
        
        return JsonResponse({
            'alerts_count': len(alerts_data),
            'critical_count': len([a for a in alerts_data if a['severity'] == 'critical']),
            'warning_count': len([a for a in alerts_data if a['severity'] == 'warning']),
            'alerts': alerts_data
        })


# ============================================
# PDF EXPORT FUNCTIONALITY
# ============================================

class ExportPDFReportView(AdminRequiredMixin, View):
    """Export des rapports en PDF"""
    
    def get(self, request, report_type):
        try:
            if report_type == 'financial':
                return self._generate_financial_report(request)
            elif report_type == 'sales':
                return self._generate_sales_report(request)
            elif report_type == 'stock':
                return self._generate_stock_report(request)
            elif report_type == 'forex':
                return self._generate_forex_report(request)
            elif report_type == 'performance':
                return self._generate_performance_report(request)
            else:
                return JsonResponse({'success': False, 'message': 'Type de rapport invalide'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Erreur: {str(e)}'})
    
    def _get_date_range(self, request):
        """Get date range from request parameters"""
        period = request.GET.get('period', 'month')
        today = timezone.now().date()
        
        if period == 'today':
            return today, today
        elif period == 'week':
            return today - timedelta(days=7), today
        elif period == 'month':
            return today - timedelta(days=30), today
        elif period == 'year':
            return today - timedelta(days=365), today
        else:
            try:
                start = datetime.strptime(request.GET.get('start_date', ''), '%Y-%m-%d').date()
                end = datetime.strptime(request.GET.get('end_date', ''), '%Y-%m-%d').date()
                return start, end
            except ValueError:
                return today - timedelta(days=30), today
    
    def _generate_financial_report(self, request):
        """Generate financial report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            alignment=TA_CENTER,
            spaceAfter=20
        )
        
        elements = []
        start_date, end_date = self._get_date_range(request)
        branche_id = request.GET.get('branche_id')
        
        # Title
        elements.append(Paragraph("RAPPORT FINANCIER PETROX", title_style))
        elements.append(Paragraph(
            f"Période: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
            styles['Normal']
        ))
        elements.append(Spacer(1, 20))
        
        # Get data
        filters = {'created_at__date__gte': start_date, 'created_at__date__lte': end_date, 'statut': 'validee'}
        if branche_id and branche_id != 'all':
            filters['branche_id'] = branche_id
        
        ventes = Vente.objects.filter(**filters)
        total_sales_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or Decimal('0')
        total_sales_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or Decimal('0')
        
        depense_filters = {'created_at__date__gte': start_date, 'created_at__date__lte': end_date, 'statut': 'approuvee'}
        if branche_id and branche_id != 'all':
            depense_filters['branche_id'] = branche_id
        
        depenses_usd = Depense.objects.filter(**depense_filters, devise='USD').aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        depenses_fc = Depense.objects.filter(**depense_filters, devise='FC').aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        
        # Summary Table
        elements.append(Paragraph("RÉSUMÉ FINANCIER", styles['Heading2']))
        
        summary_data = [
            ['Catégorie', 'USD', 'FC'],
            ['Total Ventes', f"${total_sales_usd:,.2f}", f"{total_sales_fc:,.2f} FC"],
            ['Total Dépenses', f"${depenses_usd:,.2f}", f"{depenses_fc:,.2f} FC"],
            ['Profit/Perte', f"${total_sales_usd - depenses_usd:,.2f}", f"{total_sales_fc - depenses_fc:,.2f} FC"],
        ]
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 2*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))
        
        # Sales by branch
        elements.append(Paragraph("VENTES PAR BRANCHE", styles['Heading2']))
        
        branch_sales = ventes.values('branche__nom').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            count=Count('id')
        ).order_by('-total_usd')
        
        branch_data = [['Branche', 'Nombre', 'USD', 'FC']]
        for item in branch_sales:
            branch_data.append([
                item['branche__nom'] or 'N/A',
                str(item['count']),
                f"${item['total_usd']:,.2f}",
                f"{item['total_fc']:,.2f} FC"
            ])
        
        if len(branch_data) > 1:
            branch_table = Table(branch_data, colWidths=[2*inch, 1*inch, 1.5*inch, 2*inch])
            branch_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d3748')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(branch_table)
        
        # Footer
        elements.append(Spacer(1, 30))
        elements.append(Paragraph(
            f"Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')} par {request.user.get_full_name()}",
            ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, alignment=TA_CENTER)
        ))
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rapport_financier_{start_date}_{end_date}.pdf"'
        return response
    
    def _generate_sales_report(self, request):
        """Generate sales report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        
        styles = getSampleStyleSheet()
        elements = []
        start_date, end_date = self._get_date_range(request)
        
        elements.append(Paragraph("RAPPORT DES VENTES PETROX", styles['Title']))
        elements.append(Paragraph(f"Du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Get sales data
        ventes = Vente.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            statut='validee'
        ).select_related('branche', 'type_carburant', 'pompiste')
        
        # Summary by fuel type
        elements.append(Paragraph("Ventes par Type de Carburant", styles['Heading2']))
        
        fuel_sales = ventes.values('type_carburant__nom').annotate(
            quantity=Sum('quantite'),
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc')
        )
        
        fuel_data = [['Carburant', 'Quantité (L)', 'USD', 'FC']]
        for item in fuel_sales:
            fuel_data.append([
                item['type_carburant__nom'] or 'N/A',
                f"{item['quantity']:,.2f}",
                f"${item['total_usd']:,.2f}",
                f"{item['total_fc']:,.2f}"
            ])
        
        if len(fuel_data) > 1:
            fuel_table = Table(fuel_data)
            fuel_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            elements.append(fuel_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rapport_ventes_{start_date}_{end_date}.pdf"'
        return response
    
    def _generate_stock_report(self, request):
        """Generate stock report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        
        styles = getSampleStyleSheet()
        elements = []
        
        elements.append(Paragraph("RAPPORT DE STOCK PETROX", styles['Title']))
        elements.append(Paragraph(f"Date: {timezone.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Get stock data
        stocks = Stock.objects.select_related('branche', 'type_carburant').order_by('branche__nom')
        
        stock_data = [['Branche', 'Carburant', 'Quantité', 'Capacité', 'Seuil', 'Statut']]
        for stock in stocks:
            status = 'ALERTE' if stock.quantite_actuelle <= stock.seuil_alerte else 'OK'
            stock_data.append([
                stock.branche.nom if stock.branche else 'N/A',
                stock.type_carburant.nom if stock.type_carburant else 'N/A',
                f"{stock.quantite_actuelle:,.0f}L",
                f"{stock.capacite_max:,.0f}L",
                f"{stock.seuil_alerte:,.0f}L",
                status
            ])
        
        if len(stock_data) > 1:
            stock_table = Table(stock_data, colWidths=[1.2*inch, 1*inch, 0.9*inch, 0.9*inch, 0.8*inch, 0.7*inch])
            stock_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            elements.append(stock_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rapport_stock_{timezone.now().strftime("%Y%m%d")}.pdf"'
        return response
    
    def _generate_forex_report(self, request):
        """Generate forex analysis report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        
        styles = getSampleStyleSheet()
        elements = []
        start_date, end_date = self._get_date_range(request)
        
        elements.append(Paragraph("RAPPORT FOREX PETROX", styles['Title']))
        elements.append(Paragraph(f"Du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        current_rate = TauxChange.get_current_rate()
        elements.append(Paragraph(f"Taux actuel: 1 USD = {current_rate} FC", styles['Heading2']))
        elements.append(Spacer(1, 10))
        
        # Historical rates
        rates = TauxChange.objects.filter(
            date_effective__date__gte=start_date,
            date_effective__date__lte=end_date
        ).order_by('-date_effective')[:20]
        
        rate_data = [['Date', 'Taux (FC/USD)', 'Créé par']]
        for rate in rates:
            rate_data.append([
                rate.date_effective.strftime('%d/%m/%Y'),
                str(rate.taux_usd_fc),
                rate.created_by.get_full_name() if rate.created_by else 'System'
            ])
        
        if len(rate_data) > 1:
            rate_table = Table(rate_data)
            rate_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            elements.append(rate_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rapport_forex_{start_date}_{end_date}.pdf"'
        return response
    
    def _generate_performance_report(self, request):
        """Generate performance report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        
        styles = getSampleStyleSheet()
        elements = []
        start_date, end_date = self._get_date_range(request)
        
        elements.append(Paragraph("RAPPORT DE PERFORMANCE PETROX", styles['Title']))
        elements.append(Paragraph(f"Du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Branch performance
        elements.append(Paragraph("Performance par Branche", styles['Heading2']))
        
        branches = Branche.objects.filter(is_active=True)
        branch_data = [['Branche', 'Ventes USD', 'Ventes FC', 'Dépenses USD', 'Profit USD']]
        
        for branche in branches:
            ventes = Vente.objects.filter(
                branche=branche,
                created_at__date__gte=start_date,
                created_at__date__lte=end_date,
                statut='validee'
            )
            sales_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or Decimal('0')
            sales_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or Decimal('0')
            
            depenses = Depense.objects.filter(
                branche=branche,
                created_at__date__gte=start_date,
                created_at__date__lte=end_date,
                statut='approuvee',
                devise='USD'
            ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
            
            branch_data.append([
                branche.nom,
                f"${sales_usd:,.2f}",
                f"{sales_fc:,.2f}",
                f"${depenses:,.2f}",
                f"${sales_usd - depenses:,.2f}"
            ])
        
        if len(branch_data) > 1:
            branch_table = Table(branch_data)
            branch_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            elements.append(branch_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rapport_performance_{start_date}_{end_date}.pdf"'
        return response


class ExportExcelReportView(AdminRequiredMixin, View):
    """Export des rapports en Excel/CSV"""
    
    def get(self, request, report_type):
        try:
            if report_type == 'sales':
                return self._export_sales_csv(request)
            elif report_type == 'expenses':
                return self._export_expenses_csv(request)
            elif report_type == 'stock':
                return self._export_stock_csv(request)
            elif report_type == 'forex':
                return self._export_forex_csv(request)
            else:
                return JsonResponse({'success': False, 'message': 'Type invalide'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    def _export_sales_csv(self, request):
        """Export sales to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="ventes_{timezone.now().strftime("%Y%m%d")}.csv"'
        response.write('\ufeff')  # BOM for Excel UTF-8
        
        writer = csv.writer(response)
        writer.writerow(['ID', 'Date', 'Branche', 'Pompiste', 'Carburant', 'Quantité', 'USD', 'FC', 'Taux', 'Statut'])
        
        period = request.GET.get('period', 'month')
        today = timezone.now().date()
        start_date = today - timedelta(days=30) if period == 'month' else today - timedelta(days=7)
        
        ventes = Vente.objects.filter(
            created_at__date__gte=start_date
        ).select_related('branche', 'pompiste', 'type_carburant')
        
        for vente in ventes:
            writer.writerow([
                vente.id,
                vente.created_at.strftime('%d/%m/%Y %H:%M'),
                vente.branche.nom if vente.branche else '',
                vente.pompiste.get_full_name() if vente.pompiste else '',
                vente.type_carburant.nom if vente.type_carburant else '',
                vente.quantite,
                vente.montant_usd,
                vente.montant_fc,
                vente.taux_change,
                vente.get_statut_display()
            ])
        
        return response
    
    def _export_expenses_csv(self, request):
        """Export expenses to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="depenses_{timezone.now().strftime("%Y%m%d")}.csv"'
        response.write('\ufeff')
        
        writer = csv.writer(response)
        writer.writerow(['ID', 'Date', 'Branche', 'Catégorie', 'Description', 'Montant', 'Devise', 'Statut'])
        
        today = timezone.now().date()
        start_date = today - timedelta(days=30)
        
        depenses = Depense.objects.filter(
            created_at__date__gte=start_date
        ).select_related('branche', 'categorie')
        
        for depense in depenses:
            writer.writerow([
                depense.id,
                depense.created_at.strftime('%d/%m/%Y %H:%M'),
                depense.branche.nom if depense.branche else '',
                depense.categorie.nom if depense.categorie else '',
                depense.description,
                depense.montant,
                depense.devise,
                depense.get_statut_display()
            ])
        
        return response
    
    def _export_stock_csv(self, request):
        """Export stock to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="stock_{timezone.now().strftime("%Y%m%d")}.csv"'
        response.write('\ufeff')
        
        writer = csv.writer(response)
        writer.writerow(['Branche', 'Carburant', 'Quantité Actuelle', 'Capacité Max', 'Seuil Alerte', 'Prix Achat', 'Statut'])
        
        stocks = Stock.objects.select_related('branche', 'type_carburant')
        
        for stock in stocks:
            status = 'ALERTE' if stock.quantite_actuelle <= stock.seuil_alerte else 'OK'
            writer.writerow([
                stock.branche.nom if stock.branche else '',
                stock.type_carburant.nom if stock.type_carburant else '',
                stock.quantite_actuelle,
                stock.capacite_max,
                stock.seuil_alerte,
                stock.prix_achat or '',
                status
            ])
        
        return response
    
    def _export_forex_csv(self, request):
        """Export forex history to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="forex_{timezone.now().strftime("%Y%m%d")}.csv"'
        response.write('\ufeff')
        
        writer = csv.writer(response)
        writer.writerow(['Date', 'Taux USD/FC', 'Créé par', 'Actif'])
        
        rates = TauxChange.objects.select_related('created_by').order_by('-date_effective')[:100]
        
        for rate in rates:
            writer.writerow([
                rate.date_effective.strftime('%d/%m/%Y %H:%M'),
                rate.taux_usd_fc,
                rate.created_by.get_full_name() if rate.created_by else 'System',
                'Oui' if rate.is_active else 'Non'
            ])
        
        return response


# ============================================
# ABONNÉS MANAGEMENT
# ============================================

class AbonnesListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """List all subscribers with filters"""
    template_name = 'admin/abonnes.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        search = self.request.GET.get('search', '')
        type_filter = self.request.GET.get('type', 'all')
        
        abonnes = Abonne.objects.all()
        
        if search:
            abonnes = abonnes.filter(
                Q(nom_entreprise__icontains=search) |
                Q(code_client__icontains=search) |
                Q(contact_nom__icontains=search)
            )
        
        if type_filter and type_filter != 'all':
            abonnes = abonnes.filter(type_abonnement=type_filter)
        
        context['abonnes'] = abonnes.order_by('nom_entreprise')
        context['abonnes_count'] = abonnes.count()
        
        # Summary by type
        context['prepaye_count'] = Abonne.objects.filter(type_abonnement='prepaye').count()
        context['postpaye_count'] = Abonne.objects.filter(type_abonnement='postpaye').count()
        context['credit_count'] = Abonne.objects.filter(type_abonnement='credit').count()
        
        # Total balances
        context['total_solde_usd'] = Abonne.objects.aggregate(Sum('solde_usd'))['solde_usd__sum'] or 0
        context['total_solde_fc'] = Abonne.objects.aggregate(Sum('solde_fc'))['solde_fc__sum'] or 0
        
        return context

class AbonneDetailView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Detailed view of a subscriber with global history"""
    template_name = 'admin/abonne_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        abonne_id = self.kwargs.get('abonne_id')
        abonne = get_object_or_404(Abonne, id=abonne_id)
        
        context['abonne'] = abonne
        
        # Consumption history across ALL branches
        context['consumptions'] = ConsommationAbonne.objects.filter(
            abonne=abonne
        ).select_related('branche', 'type_carburant').order_by('-created_at')[:50]
        
        # Summary by branch
        context['by_branch'] = ConsommationAbonne.objects.filter(abonne=abonne).values(
            'branche__nom'
        ).annotate(
            total_quantity=Sum('quantite'),
            total_usd=Sum('montant', filter=Q(devise='USD')),
            total_fc=Sum('montant', filter=Q(devise='FC')),
            count=Count('id')
        )
        
        return context

class UtilisateursListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """List all users and pompistes"""
    template_name = 'admin/utilisateurs.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        role_filter = self.request.GET.get('role', 'all')
        branche_id = self.request.GET.get('branche_id', 'all')
        
        # System users
        users = User.objects.select_related('branche')
        
        if role_filter and role_filter != 'all':
            users = users.filter(role=role_filter)
        
        if branche_id and branche_id != 'all':
            users = users.filter(branche_id=branche_id)
        
        context['users'] = users.order_by('role', 'prenom')
        
        # Pompistes (non-system employees)
        pompistes = Pompiste.objects.select_related('branche')
        
        if branche_id and branche_id != 'all':
            pompistes = pompistes.filter(branche_id=branche_id)
        
        context['pompistes'] = pompistes.order_by('branche__nom', 'prenom')
        
        # Counts
        context['admin_count'] = User.objects.filter(role='admin').count()
        context['manager_count'] = User.objects.filter(role='manager').count()
        context['caissier_count'] = User.objects.filter(role='caissier').count()
        context['pompiste_count'] = Pompiste.objects.filter(is_active=True).count()
        
        return context
    
class DocumentsListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Documents management with categories and visibility"""
    template_name = 'admin/documents.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        categorie_id = self.request.GET.get('categorie_id', 'all')
        visibility = self.request.GET.get('visibility', 'all')
        
        documents = Document.objects.select_related('categorie', 'uploaded_by')
        
        if categorie_id and categorie_id != 'all':
            documents = documents.filter(categorie_id=categorie_id)
        
        if visibility and visibility != 'all':
            documents = documents.filter(visibilite=visibility)
        
        context['documents'] = documents.order_by('-created_at')
        context['categories'] = DocumentCategory.objects.filter(is_active=True)
        
        return context
    
class ForexView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Forex management and impact analysis"""
    template_name = 'admin/forex.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Current rate
        current = TauxChange.objects.filter(is_active=True).first()
        context['current_rate'] = current
        
        # Rate history
        context['rate_history'] = TauxChange.objects.select_related('created_by').order_by('-date_effective')[:30]
        
        # Forex impact calculation would come from API
        
        return context
    
class RapportsView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Reports generation and export"""
    template_name = 'admin/rapports.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Available report types
        context['report_types'] = [
            {'id': 'financial', 'name': 'Rapport Financier', 'description': 'Ventes, dépenses et profit'},
            {'id': 'sales', 'name': 'Rapport des Ventes', 'description': 'Détail des ventes par période'},
            {'id': 'stock', 'name': 'Rapport de Stock', 'description': 'État du stock par branche'},
            {'id': 'forex', 'name': 'Rapport Forex', 'description': 'Analyse de l\'impact des taux'},
            {'id': 'performance', 'name': 'Rapport de Performance', 'description': 'Performance par branche'},
        ]
        
        return context
    
class NotificationsView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Notifications center"""
    template_name = 'admin/notifications.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        context['notifications'] = Notification.objects.filter(
            destinataire=self.request.user
        ).order_by('-created_at')[:50]
        
        return context
    
class SalairesView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Payroll management and history"""
    template_name = 'admin/salaires.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        branche_id = self.request.GET.get('branche_id', 'all')
        period = self.request.GET.get('period', 'month')
        
        payments = PaiementSalaire.objects.select_related(
            'pompiste', 'branche', 'caissier'
        )
        
        if branche_id and branche_id != 'all':
            payments = payments.filter(branche_id=branche_id)
        
        today = timezone.now().date()
        if period == 'month':
            payments = payments.filter(date_paiement__date__gte=today - timedelta(days=30))
        
        context['payments'] = payments.order_by('-date_paiement')[:100]
        
        # Totals
        context['total_usd'] = payments.filter(devise='USD').aggregate(Sum('montant_paye'))['montant_paye__sum'] or 0
        context['total_fc'] = payments.filter(devise='FC').aggregate(Sum('montant_paye'))['montant_paye__sum'] or 0
        
        return context

class ParametresView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """System settings"""
    template_name = 'admin/parametres.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Payment methods
        context['moyens_paiement'] = MoyenPaiement.objects.all()
        
        # Expense categories
        context['categories_depense'] = CategorieDepense.objects.all()
        
        # Fuel types
        context['types_carburant'] = TypeCarburant.objects.all()
        
        return context


class CreateAbonneView(AdminRequiredMixin, View):
    """Création d'un abonné"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            required_fields = ['nom_entreprise', 'code_client', 'contact_nom', 'contact_telephone', 'type_abonnement']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            if Abonne.objects.filter(code_client=data['code_client']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce code client existe déjà'
                })
            
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
                    'code_client': abonne.code_client
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Données JSON invalides'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class UpdateAbonneView(AdminRequiredMixin, View):
    """Mise à jour d'un abonné"""
    
    def post(self, request, abonne_id):
        try:
            abonne = get_object_or_404(Abonne, id=abonne_id)
            data = json.loads(request.body)
            
            # Update fields
            if 'nom_entreprise' in data:
                abonne.nom_entreprise = data['nom_entreprise']
            if 'contact_nom' in data:
                abonne.contact_nom = data['contact_nom']
            if 'contact_telephone' in data:
                abonne.contact_telephone = data['contact_telephone']
            if 'contact_email' in data:
                abonne.contact_email = data['contact_email']
            if 'adresse' in data:
                abonne.adresse = data['adresse']
            if 'type_abonnement' in data:
                abonne.type_abonnement = data['type_abonnement']
            if 'limite_credit' in data:
                abonne.limite_credit = Decimal(str(data['limite_credit']))
            if 'is_active' in data:
                abonne.is_active = data['is_active']
            
            abonne.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Abonné mis à jour avec succès'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Données JSON invalides'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class AbonneGlobalHistoryView(AdminRequiredMixin, View):
    """Historique global des consommations d'un abonné (toutes branches)"""
    
    def get(self, request, abonne_id):
        abonne = get_object_or_404(Abonne, id=abonne_id)
        
        # Get all consumptions across all branches
        consumptions = ConsommationAbonne.objects.filter(
            abonne=abonne
        ).select_related('branche', 'type_carburant').order_by('-created_at')
        
        # Summary by branch
        branch_summary = consumptions.values('branche__nom').annotate(
            total_quantity=Sum('quantite'),
            total_usd=Sum('montant', filter=Q(devise='USD')),
            total_fc=Sum('montant', filter=Q(devise='FC')),
            count=Count('id')
        )
        
        consumption_data = []
        for c in consumptions[:100]:
            consumption_data.append({
                'id': c.id,
                'date': c.created_at.strftime('%d/%m/%Y %H:%M'),
                'branche': c.branche.nom if c.branche else 'N/A',
                'carburant': c.type_carburant.nom if c.type_carburant else 'N/A',
                'quantite': str(c.quantite),
                'montant': str(c.montant),
                'devise': c.devise
            })
        
        return JsonResponse({
            'abonne': {
                'id': abonne.id,
                'nom_entreprise': abonne.nom_entreprise,
                'code_client': abonne.code_client,
                'type_abonnement': abonne.get_type_abonnement_display(),
                'solde_usd': str(abonne.solde_usd),
                'solde_fc': str(abonne.solde_fc)
            },
            'branch_summary': list(branch_summary),
            'consumptions': consumption_data,
            'total_consumptions': consumptions.count()
        })


# ============================================
# DOCUMENT MANAGEMENT
# ============================================

class CreateDocumentCategoryView(AdminRequiredMixin, View):
    """Création de catégorie de document"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            if not data.get('nom'):
                return JsonResponse({'success': False, 'message': 'Le nom est requis'})
            
            category = DocumentCategory.objects.create(
                nom=data['nom'],
                description=data.get('description', '')
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Catégorie créée',
                'category': {'id': category.id, 'nom': category.nom}
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class UpdateDocumentVisibilityView(AdminRequiredMixin, View):
    """Mise à jour de la visibilité d'un document"""
    
    def post(self, request, document_id):
        try:
            document = get_object_or_404(Document, id=document_id)
            data = json.loads(request.body)
            
            if 'is_public' in data:
                document.is_public = data['is_public']
                document.save()
            
            return JsonResponse({
                'success': True,
                'message': f"Document {'public' if document.is_public else 'confidentiel'}"
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


# ============================================
# SYSTEM SETTINGS
# ============================================

class SystemSettingsView(AdminRequiredMixin, View):
    """Vue des paramètres système"""
    
    def get(self, request):
        current_rate = TauxChange.objects.filter(is_active=True).first()
        
        return JsonResponse({
            'exchange_rate': {
                'current': str(current_rate.taux_usd_fc) if current_rate else '2800.00',
                'last_updated': current_rate.date_effective.strftime('%d/%m/%Y %H:%M') if current_rate else None
            },
            'branches': {
                'total': Branche.objects.count(),
                'active': Branche.objects.filter(is_active=True).count()
            },
            'users': {
                'total': User.objects.count(),
                'admins': User.objects.filter(role='admin').count(),
                'managers': User.objects.filter(role='manager').count(),
                'caissiers': User.objects.filter(role='caissier').count()
            },
            'fuel_types': TypeCarburant.objects.filter(is_active=True).count(),
            'expense_categories': CategorieDepense.objects.filter(is_active=True).count(),
            'payment_methods': MoyenPaiement.objects.filter(is_active=True).count()
        })


class UpdateSystemSettingsView(AdminRequiredMixin, View):
    """Mise à jour des paramètres système"""
    
    def post(self, request):
        # This would handle various system settings updates
        # For now, just return success
        return JsonResponse({
            'success': True,
            'message': 'Paramètres mis à jour'
        })


# ============================================
# ADVANCED REPORTS
# ============================================

class FinancialReportView(AdminRequiredMixin, View):
    """Rapport financier détaillé"""
    
    def get(self, request):
        period = request.GET.get('period', 'month')
        branche_id = request.GET.get('branche_id')
        
        today = timezone.now().date()
        if period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        elif period == 'year':
            start_date = today - timedelta(days=365)
        else:
            start_date = today - timedelta(days=30)
        
        filters = {'created_at__date__gte': start_date, 'statut': 'validee'}
        if branche_id and branche_id != 'all':
            filters['branche_id'] = branche_id
        
        ventes = Vente.objects.filter(**filters)
        
        # Daily breakdown
        daily_sales = ventes.extra(
            select={'day': 'DATE(created_at)'}
        ).values('day').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            count=Count('id')
        ).order_by('day')
        
        return JsonResponse({
            'period': {'start': str(start_date), 'end': str(today)},
            'daily_breakdown': list(daily_sales),
            'totals': {
                'sales_usd': str(ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0),
                'sales_fc': str(ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0),
                'transaction_count': ventes.count()
            }
        })


class PerformanceReportView(AdminRequiredMixin, View):
    """Rapport de performance par branche et employé"""
    
    def get(self, request):
        period = request.GET.get('period', 'month')
        today = timezone.now().date()
        
        if period == 'week':
            start_date = today - timedelta(days=7)
        else:
            start_date = today - timedelta(days=30)
        
        # Branch performance
        branch_performance = []
        for branche in Branche.objects.filter(is_active=True):
            ventes = Vente.objects.filter(
                branche=branche,
                created_at__date__gte=start_date,
                statut='validee'
            )
            
            sales_usd = ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or Decimal('0')
            sales_fc = ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or Decimal('0')
            
            depenses = Depense.objects.filter(
                branche=branche,
                created_at__date__gte=start_date,
                statut='approuvee',
                devise='USD'
            ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
            
            manquants = Vente.objects.filter(
                branche=branche,
                created_at__date__gte=start_date,
                statut='manquant'
            ).count()
            
            branch_performance.append({
                'branche': branche.nom,
                'code': branche.code,
                'sales_usd': str(sales_usd),
                'sales_fc': str(sales_fc),
                'expenses_usd': str(depenses),
                'profit_usd': str(sales_usd - depenses),
                'transactions': ventes.count(),
                'manquants': manquants
            })
        
        # Pompiste performance
        pompiste_performance = Vente.objects.filter(
            created_at__date__gte=start_date,
            statut='validee'
        ).values('pompiste__prenom', 'pompiste__nom', 'branche__nom').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            total_quantity=Sum('quantite'),
            transactions=Count('id')
        ).order_by('-total_usd')[:20]
        
        return JsonResponse({
            'period': {'start': str(start_date), 'end': str(today)},
            'branch_performance': branch_performance,
            'pompiste_performance': list(pompiste_performance)
        })


class AuditReportView(AdminRequiredMixin, View):
    """Rapport d'audit - traçabilité des actions"""
    
    def get(self, request):
        today = timezone.now().date()
        start_date = today - timedelta(days=7)
        
        # Recent rate changes
        rate_changes = TauxChange.objects.filter(
            date_effective__date__gte=start_date
        ).select_related('created_by').order_by('-date_effective')
        
        rate_data = [{
            'date': r.date_effective.strftime('%d/%m/%Y %H:%M'),
            'taux': str(r.taux_usd_fc),
            'user': r.created_by.get_full_name() if r.created_by else 'System'
        } for r in rate_changes]
        
        # Recent validations
        validations = Vente.objects.filter(
            validated_at__date__gte=start_date,
            statut__in=['validee', 'manquant']
        ).select_related('caissier', 'branche').order_by('-validated_at')[:50]
        
        validation_data = [{
            'id': v.id,
            'date': v.validated_at.strftime('%d/%m/%Y %H:%M') if v.validated_at else None,
            'branche': v.branche.nom if v.branche else 'N/A',
            'caissier': v.caissier.get_full_name() if v.caissier else 'N/A',
            'statut': v.get_statut_display(),
            'montant_usd': str(v.montant_usd),
            'manquant_usd': str(v.manquant_usd) if v.statut == 'manquant' else None
        } for v in validations]
        
        return JsonResponse({
            'rate_changes': rate_data,
            'validations': validation_data
        })