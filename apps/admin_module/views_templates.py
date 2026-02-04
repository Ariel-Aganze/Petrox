from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import Http404
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from django.db.models import Sum, F, Count, Q, Avg
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from apps.core.models import (
    User, Branche, TauxChange, TypeCarburant, CategorieDepense,
    Vente, Depense, Stock, Pompiste, Abonne, ConsommationAbonne,
    Document, DocumentCategory, Notification, PaiementSalaire
)
from apps.core.models import MoyenPaiement, CategorieDepense, TypeCarburant, TauxChange, Branche, User
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from dateutil.relativedelta import relativedelta




class AdminRequiredMixin(UserPassesTestMixin):
    """Mixin to restrict access to admin users only"""
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == 'admin'


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
        
        # Fuel types for filters
        context['types_carburant'] = TypeCarburant.objects.filter(is_active=True)
        
        # Expense categories for filters
        context['categories_depense'] = CategorieDepense.objects.filter(is_active=True)
        
        return context


class AdminDashboardView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """
    Main Admin Dashboard
    Displays global overview with KPIs, charts, and recent activity
    
    This view provides initial server-side rendered data for faster page load,
    then the frontend can request updated data via AJAX from DashboardStatsAPIView
    """
    template_name = 'admin/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter parameters from URL
        branche_id = self.request.GET.get('branche_id', 'all')
        period = self.request.GET.get('period', 'month')
        devise = self.request.GET.get('devise', 'USD')
        
        # Store current filters in context for template
        context['current_period'] = period
        context['current_devise'] = devise
        
        # Calculate date range for the selected period
        date_range = self._get_date_range(period)
        
        # Base querysets for sales and expenses
        sales_qs = Vente.objects.filter(
            created_at__gte=date_range['start'],
            created_at__lte=date_range['end'],
            statut='validee'
        )
        
        expenses_qs = Depense.objects.filter(
            created_at__gte=date_range['start'],
            created_at__lte=date_range['end'],
            statut='approuvee'
        )
        
        # Apply branch filter if specific branch selected
        if branche_id and branche_id != 'all':
            try:
                branche = Branche.objects.get(id=branche_id)
                sales_qs = sales_qs.filter(branche=branche)
                expenses_qs = expenses_qs.filter(branche=branche)
            except Branche.DoesNotExist:
                pass
        
        # Calculate initial KPIs based on selected currency
        if devise == 'USD':
            context['initial_total_sales'] = sales_qs.aggregate(
                Sum('montant_usd')
            )['montant_usd__sum'] or 0
            
            context['initial_total_expenses'] = expenses_qs.filter(
                devise='USD'
            ).aggregate(Sum('montant'))['montant__sum'] or 0
            
            context['initial_total_manquants'] = Vente.objects.filter(
                created_at__gte=date_range['start'],
                created_at__lte=date_range['end'],
                statut='manquant'
            ).aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or 0
            
        else:  # FC
            context['initial_total_sales'] = sales_qs.aggregate(
                Sum('montant_fc')
            )['montant_fc__sum'] or 0
            
            context['initial_total_expenses'] = expenses_qs.filter(
                devise='FC'
            ).aggregate(Sum('montant'))['montant__sum'] or 0
            
            context['initial_total_manquants'] = Vente.objects.filter(
                created_at__gte=date_range['start'],
                created_at__lte=date_range['end'],
                statut='manquant'
            ).aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or 0
        
        # Calculate net profit
        context['initial_net_profit'] = context['initial_total_sales'] - context['initial_total_expenses']
        
        # Calculate profit margin percentage
        if context['initial_total_sales'] > 0:
            context['initial_profit_margin'] = round(
                (context['initial_net_profit'] / context['initial_total_sales']) * 100, 
                1
            )
        else:
            context['initial_profit_margin'] = 0
        
        # Count of missing sales
        context['initial_manquants_count'] = Vente.objects.filter(
            created_at__gte=date_range['start'],
            created_at__lte=date_range['end'],
            statut='manquant'
        ).count()
        
        # Get recent transactions (combined sales and expenses)
        context['recent_transactions'] = self._get_recent_transactions(
            branche_id, 
            devise, 
            limit=10
        )
        
        # Get stock alerts
        context['stock_alerts'] = self._get_stock_alerts(branche_id, limit=10)
        context['stock_alerts_count'] = len(context['stock_alerts'])
        
        # Get summary statistics for quick reference
        context['summary_stats'] = self._get_summary_stats(branche_id)
        
        # Active branches count
        context['active_branches_count'] = Branche.objects.filter(is_active=True).count()
        
        # Active users count
        context['active_users_count'] = User.objects.filter(is_active=True).count()
        
        # Active pompistes count
        context['active_pompistes_count'] = Pompiste.objects.filter(is_active=True).count()
        
        # Total subscribers count
        context['total_subscribers_count'] = Abonne.objects.count()
        
        # Currency symbol for template
        context['currency_symbol'] = '$' if devise == 'USD' else 'FC'
        
        return context
    
    def _get_date_range(self, period):
        """
        Calculate start and end dates based on selected period
        
        Args:
            period (str): One of 'today', 'week', 'month', 'year'
            
        Returns:
            dict: {'start': datetime, 'end': datetime}
        """
        now = timezone.now()
        
        if period == 'today':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == 'week':
            start = now - timedelta(days=7)
            end = now
        elif period == 'month':
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == 'year':
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
        else:
            # Default to month
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
        
        return {'start': start, 'end': end}
    
    def _get_recent_transactions(self, branche_id, devise, limit=10):
        """
        Get recent sales and expenses combined into single list
        
        Args:
            branche_id (str): Branch ID or 'all'
            devise (str): Currency 'USD' or 'FC'
            limit (int): Number of transactions to return
            
        Returns:
            list: Combined list of recent transactions
        """
        transactions = []
        
        # Get recent sales
        sales_qs = Vente.objects.select_related(
            'branche', 'pompiste', 'type_carburant'
        )
        
        if branche_id and branche_id != 'all':
            try:
                sales_qs = sales_qs.filter(branche_id=branche_id)
            except:
                pass
        
        recent_sales = sales_qs.order_by('-created_at')[:limit]
        
        for sale in recent_sales:
            amount = sale.montant_usd if devise == 'USD' else sale.montant_fc
            
            # Build description
            fuel_name = sale.type_carburant.nom if sale.type_carburant else "N/A"
            pompiste_name = sale.pompiste.get_full_name() if sale.pompiste else "N/A"
            
            transactions.append({
                'type': 'sale',
                'id': sale.id,
                'description': f'Vente {fuel_name} - {pompiste_name}',
                'branch': sale.branche.nom if sale.branche else 'N/A',
                'date': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                'timestamp': sale.created_at,
                'amount': float(amount),
                'status': sale.get_statut_display(),
                'icon': 'sale',  # For frontend icon selection
                'color': 'green'  # For frontend color coding
            })
        
        # Get recent expenses
        expenses_qs = Depense.objects.select_related(
            'branche', 'categorie'
        ).filter(devise=devise)
        
        if branche_id and branche_id != 'all':
            try:
                expenses_qs = expenses_qs.filter(branche_id=branche_id)
            except:
                pass
        
        recent_expenses = expenses_qs.order_by('-created_at')[:limit]
        
        for expense in recent_expenses:
            category_name = expense.categorie.nom if expense.categorie else "Dépense"
            description = expense.description[:50] + '...' if len(expense.description) > 50 else expense.description
            
            transactions.append({
                'type': 'expense',
                'id': expense.id,
                'description': f'{category_name} - {description}',
                'branch': expense.branche.nom if expense.branche else 'N/A',
                'date': expense.created_at.strftime('%d/%m/%Y %H:%M'),
                'timestamp': expense.created_at,
                'amount': -float(expense.montant),  # Negative for expenses
                'status': expense.get_statut_display(),
                'icon': 'expense',
                'color': 'red'
            })
        
        # Sort by timestamp (most recent first) and limit
        transactions.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Remove timestamp field before returning (not JSON serializable in template)
        for transaction in transactions[:limit]:
            del transaction['timestamp']
        
        return transactions[:limit]
    
    def _get_stock_alerts(self, branche_id, limit=10):
        """
        Get stock items below alert threshold
        
        Args:
            branche_id (str): Branch ID or 'all'
            limit (int): Maximum number of alerts to return
            
        Returns:
            list: Stock alerts with details
        """
        stocks_qs = Stock.objects.select_related(
            'branche', 'type_carburant'
        ).filter(
            quantite_actuelle__lte=F('seuil_alerte')
        )
        
        if branche_id and branche_id != 'all':
            try:
                stocks_qs = stocks_qs.filter(branche_id=branche_id)
            except:
                pass
        
        stocks_qs = stocks_qs.order_by('quantite_actuelle')[:limit]
        
        alerts = []
        for stock in stocks_qs:
            # Calculate percentage of stock remaining
            if stock.seuil_alerte > 0:
                percentage = (stock.quantite_actuelle / stock.seuil_alerte) * 100
            else:
                percentage = 0
            
            # Determine alert level
            if percentage < 25:
                level = 'critical'
                level_label = 'Critique'
            elif percentage < 50:
                level = 'warning'
                level_label = 'Attention'
            else:
                level = 'low'
                level_label = 'Bas'
            
            alerts.append({
                'id': stock.id,
                'fuel_type': stock.type_carburant.nom if stock.type_carburant else 'N/A',
                'fuel_code': stock.type_carburant.code if stock.type_carburant else '',
                'branch': stock.branche.nom if stock.branche else 'N/A',
                'branch_id': stock.branche.id if stock.branche else None,
                'current_stock': float(stock.quantite_actuelle),
                'threshold': float(stock.seuil_alerte),
                'percentage': round(percentage, 1),
                'level': level,
                'level_label': level_label,
                'color': 'red' if level == 'critical' else 'yellow'
            })
        
        return alerts
    
    def _get_summary_stats(self, branche_id):
        """
        Get additional summary statistics for dashboard
        
        Args:
            branche_id (str): Branch ID or 'all'
            
        Returns:
            dict: Summary statistics
        """
        # Base querysets
        sales_qs = Vente.objects.filter(statut='validee')
        expenses_qs = Depense.objects.filter(statut='approuvee')
        
        # Apply branch filter if needed
        if branche_id and branche_id != 'all':
            try:
                sales_qs = sales_qs.filter(branche_id=branche_id)
                expenses_qs = expenses_qs.filter(branche_id=branche_id)
            except:
                pass
        
        # Today's counts
        today = timezone.now().date()
        today_sales = sales_qs.filter(created_at__date=today).count()
        today_expenses = expenses_qs.filter(created_at__date=today).count()
        
        # This month's counts
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_sales = sales_qs.filter(created_at__gte=month_start).count()
        month_expenses = expenses_qs.filter(created_at__gte=month_start).count()
        
        # Pending validations
        pending_sales = Vente.objects.filter(statut='en_attente').count()
        pending_expenses = Depense.objects.filter(statut='en_attente').count()
        
        # Average sale amount (USD)
        avg_sale_usd = sales_qs.aggregate(Avg('montant_usd'))['montant_usd__avg'] or 0
        
        # Most sold fuel type
        top_fuel = sales_qs.values(
            'type_carburant__nom'
        ).annotate(
            total_quantity=Sum('quantite')
        ).order_by('-total_quantity').first()
        
        top_fuel_name = top_fuel['type_carburant__nom'] if top_fuel else 'N/A'
        
        # Most active branch (if viewing all branches)
        if branche_id == 'all':
            top_branch = Vente.objects.filter(
                statut='validee'
            ).values(
                'branche__nom'
            ).annotate(
                total=Sum('montant_usd')
            ).order_by('-total').first()
            
            top_branch_name = top_branch['branche__nom'] if top_branch else 'N/A'
        else:
            top_branch_name = None
        
        return {
            'today_sales_count': today_sales,
            'today_expenses_count': today_expenses,
            'month_sales_count': month_sales,
            'month_expenses_count': month_expenses,
            'pending_sales_count': pending_sales,
            'pending_expenses_count': pending_expenses,
            'average_sale_usd': round(float(avg_sale_usd), 2),
            'top_fuel_type': top_fuel_name,
            'top_branch': top_branch_name,
        }


# Additional helper method that can be used across multiple admin views
def format_currency(amount, devise='USD'):
    """
    Format currency amount with appropriate symbol
    
    Args:
        amount (Decimal/float): Amount to format
        devise (str): Currency code 'USD' or 'FC'
        
    Returns:
        str: Formatted currency string
    """
    symbol = '$' if devise == 'USD' else 'FC'
    formatted_amount = f"{float(amount):,.2f}"
    
    if devise == 'USD':
        return f"{symbol}{formatted_amount}"
    else:
        return f"{formatted_amount} {symbol}"


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
        
        # Pending category requests
        context['pending_categories'] = CategorieDepense.objects.filter(is_active=False)
        
        return context


class CarburantsListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Carburants management page"""
    template_name = 'admin/carburants.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all fuel types with stock data
        fuel_types = TypeCarburant.objects.all().order_by('nom')
        
        fuel_types_data = []
        for fuel in fuel_types:
            stocks = Stock.objects.filter(type_carburant=fuel)
            total_stock = float(stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0)
            branches_count = stocks.values('branche').distinct().count()
            
            fuel_types_data.append({
                'id': fuel.id,
                'nom': fuel.nom,
                'code': fuel.code if hasattr(fuel, 'code') else '',
                'couleur_hex': fuel.couleur_hex,
                'prix_vente_usd': fuel.prix_vente_usd,
                'prix_vente_fc': fuel.prix_vente_fc,
                'is_active': fuel.is_active,
                'total_stock': total_stock,
                'branches_count': branches_count
            })
        
        context['fuel_types'] = fuel_types_data
        context['fuel_types_count'] = len(fuel_types_data)
        
        # Get all stocks
        stocks = Stock.objects.select_related('branche', 'type_carburant').order_by('branche__nom', 'type_carburant__nom')
        context['stocks'] = stocks
        
        # Get all branches for filter
        context['all_branches'] = Branche.objects.filter(is_active=True).order_by('nom')
        context['branches_count'] = context['all_branches'].count()
        
        # Global statistics
        all_stocks = Stock.objects.all()
        totals = all_stocks.aggregate(
            total_stock=Sum('quantite_actuelle'),
            total_capacity=Sum('capacite_max')
        )
        
        total_stock = float(totals['total_stock'] or 0)
        total_capacity = float(totals['total_capacity'] or 0)
        
        context['total_stock'] = total_stock
        context['total_capacity'] = total_capacity
        context['fill_percentage'] = round((total_stock / total_capacity * 100), 1) if total_capacity > 0 else 0
        
        # Alerts count
        context['alerts_count'] = all_stocks.filter(quantite_actuelle__lte=F('seuil_alerte')).count()
        
        # Stock by fuel type summary
        stock_by_fuel = []
        for fuel in fuel_types:
            fuel_stocks = all_stocks.filter(type_carburant=fuel)
            fuel_total = float(fuel_stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0)
            fuel_capacity = float(fuel_stocks.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0)
            
            stock_by_fuel.append({
                'type_carburant__nom': fuel.nom,
                'type_carburant__couleur_hex': fuel.couleur_hex,
                'total_quantity': fuel_total,
                'total_capacity': fuel_capacity,
                'branches_count': fuel_stocks.values('branche').distinct().count()
            })
        
        context['stock_by_fuel'] = stock_by_fuel
        
        return context


class AbonnesListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """List all subscribers"""
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
    """Detailed view of a subscriber with consumption history"""
    template_name = 'admin/abonne_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        abonne_id = self.kwargs.get('abonne_id')
        
        # Get abonné
        try:
            abonne = Abonne.objects.get(id=abonne_id)
        except Abonne.DoesNotExist:
            raise Http404("Abonné non trouvé")
        
        context['abonne'] = abonne
        
        # Get consumptions - NO VENTE FIELD
        consumptions_list = ConsommationAbonne.objects.filter(
            abonne=abonne
        ).select_related(
            'branche', 
            'type_carburant'
        ).order_by('-created_at')
        
        # Pagination - 20 items per page
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
        paginator = Paginator(consumptions_list, 20)
        page = self.request.GET.get('page', 1)
        
        try:
            consumptions = paginator.page(page)
        except PageNotAnInteger:
            consumptions = paginator.page(1)
        except EmptyPage:
            consumptions = paginator.page(paginator.num_pages)
        
        context['consumptions'] = consumptions
        
        # Total consumptions count
        context['total_consumptions'] = consumptions_list.count()
        
        # Count unique branches
        context['branches_count'] = consumptions_list.values('branche').distinct().count()
        
        # Current month consumption
        from django.utils import timezone
        today = timezone.now().date()
        month_start = today.replace(day=1)
        
        month_consumptions = consumptions_list.filter(
            created_at__date__gte=month_start
        )
        
        # Calculate month totals
        context['month_consumption_usd'] = sum(
            c.montant for c in month_consumptions if c.devise == 'USD'
        )
        
        context['month_consumption_fc'] = sum(
            c.montant for c in month_consumptions if c.devise == 'FC'
        )
        
        # Last consumption date
        last_consumption = consumptions_list.first()
        context['last_consumption_date'] = last_consumption.created_at.strftime('%d/%m/%Y') if last_consumption else None
        
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
    """Documents management"""
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
    """Forex & Exchange Rate Management"""
    template_name = 'admin/forex.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # DEBUG: Print to console
        print("DEBUG: ForexView get_context_data called")
        
        # Get current rate
        current_rate_obj = TauxChange.objects.filter(is_active=True).first()
        
        if current_rate_obj:
            context['current_rate'] = float(current_rate_obj.taux_usd_fc)
            context['rate_updated_at'] = current_rate_obj.date_effective
            context['rate_updated_by'] = current_rate_obj.created_by.get_full_name() if current_rate_obj.created_by else 'System'
            print(f"DEBUG: Current rate = {context['current_rate']}")
        else:
            # Create default rate if none exists
            context['current_rate'] = 2800.00
            context['rate_updated_at'] = timezone.now()
            context['rate_updated_by'] = 'System'
            print("DEBUG: No rate found, using default 2800.00")
        
        # Get current month sales
        today = timezone.now().date()
        first_day = today.replace(day=1)
        
        ventes = Vente.objects.filter(
            created_at__date__gte=first_day,
            statut='validee'
        ).select_related('type_carburant', 'branche')
        
        context['transactions_count'] = ventes.count()
        print(f"DEBUG: Found {context['transactions_count']} transactions")
        
        # Calculate forex impact
        current_rate = Decimal(str(context['current_rate']))
        total_impact = Decimal('0')
        gains = Decimal('0')
        losses = Decimal('0')
        
        forex_by_fuel = {}
        
        for vente in ventes:
            if vente.taux_change and vente.taux_change != current_rate:
                # Expected FC at current rate
                expected_fc = vente.montant_usd * current_rate
                actual_fc = vente.montant_fc
                
                # Impact in FC
                fc_difference = actual_fc - expected_fc
                
                # Convert to USD
                usd_impact = fc_difference / current_rate if current_rate > 0 else Decimal('0')
                
                total_impact += usd_impact
                
                if usd_impact > 0:
                    gains += usd_impact
                else:
                    losses += abs(usd_impact)
                
                # Group by fuel
                if vente.type_carburant:
                    fuel_name = vente.type_carburant.nom
                    if fuel_name not in forex_by_fuel:
                        forex_by_fuel[fuel_name] = {
                            'nom': fuel_name,
                            'couleur': vente.type_carburant.couleur_hex,
                            'impact': Decimal('0'),
                            'transactions': 0
                        }
                    forex_by_fuel[fuel_name]['impact'] += usd_impact
                    forex_by_fuel[fuel_name]['transactions'] += 1
        
        context['total_impact'] = float(total_impact)
        context['gains'] = float(gains)
        context['losses'] = float(losses)
        context['forex_by_fuel'] = list(forex_by_fuel.values())
        
        print(f"DEBUG: Total impact = {context['total_impact']}")
        print(f"DEBUG: Gains = {context['gains']}")
        print(f"DEBUG: Losses = {context['losses']}")
        print(f"DEBUG: Fuel types with impact = {len(forex_by_fuel)}")
        
        # Rate history (last 20)
        rate_history = TauxChange.objects.select_related('created_by').order_by('-date_effective')[:20]
        context['rate_history'] = [{
            'taux': float(rate.taux_usd_fc),
            'date': rate.date_effective,
            'created_by': rate.created_by.get_full_name() if rate.created_by else 'System',
            'is_active': rate.is_active
        } for rate in rate_history]
        
        print(f"DEBUG: Rate history count = {len(context['rate_history'])}")
        
        # DEBUG: Print all context keys
        print(f"DEBUG: Context keys = {list(context.keys())}")
        
        return context


class RapportsView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Reports generation"""
    template_name = 'admin/rapports.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        context['report_types'] = [
            {'id': 'financial', 'name': 'Rapport Financier', 'description': 'Ventes, dépenses et profit'},
            {'id': 'sales', 'name': 'Rapport des Ventes', 'description': 'Détail des ventes par période'},
            {'id': 'stock', 'name': 'Rapport de Stock', 'description': 'État du stock par branche'},
            {'id': 'forex', 'name': 'Rapport Forex', 'description': "Analyse de l'impact des taux"},
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
    """Salaires & Payroll page"""
    template_name = 'admin/salaires.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filters
        branche_id = self.request.GET.get('branche_id', '')
        employee_type = self.request.GET.get('employee_type', 'all')
        period = self.request.GET.get('period', 'month')
        devise = self.request.GET.get('devise', '')
        
        # Calculate date range
        today = timezone.now().date()
        if period == 'month':
            start_date = today.replace(day=1)
        elif period == 'last_month':
            last_month = today - relativedelta(months=1)
            start_date = last_month.replace(day=1)
            today = start_date.replace(day=1) + relativedelta(months=1) - timedelta(days=1)
        elif period == 'year':
            start_date = today.replace(month=1, day=1)
        else:
            start_date = None
        
        # Base queryset
        payments = PaiementSalaire.objects.select_related(
            'pompiste', 'branche', 'caissier'
        ).order_by('-date_paiement')
        
        # Apply filters
        if start_date:
            payments = payments.filter(date_paiement__date__gte=start_date)
        
        if branche_id:
            payments = payments.filter(branche_id=branche_id)
        
        if devise:
            payments = payments.filter(devise_paiement=devise)
        
        # Format payments for template
        payments_list = []
        for payment in payments[:100]:  # Limit to 100 for performance
            payments_list.append({
                'id': payment.id,
                'employee_name': payment.pompiste.get_full_name() if payment.pompiste else 'N/A',
                'employee_type': 'Pompiste',
                'branche': payment.branche.nom if payment.branche else 'N/A',
                'periode': payment.mois_paiement.strftime('%m/%Y') if payment.mois_paiement else 'N/A',
                'montant': float(payment.montant_paye),
                'devise': payment.devise_paiement,
                'paid_by': payment.caissier.get_full_name() if payment.caissier else 'N/A',
                'date_paiement': payment.date_paiement
            })
        
        context['payments'] = payments_list
        
        # Statistics
        month_start = today.replace(day=1)
        month_payments = PaiementSalaire.objects.filter(
            date_paiement__date__gte=month_start
        )
        
        total_usd = float(month_payments.filter(devise_paiement='USD').aggregate(
            Sum('montant_paye'))['montant_paye__sum'] or 0)
        total_fc = float(month_payments.filter(devise_paiement='FC').aggregate(
            Sum('montant_paye'))['montant_paye__sum'] or 0)
        
        # Convert FC to USD for total (using current rate)
        current_rate_obj = TauxChange.objects.filter(is_active=True).first()
        current_rate = float(current_rate_obj.taux_usd_fc) if current_rate_obj else 2800.0
        total_usd += (total_fc / current_rate)
        
        context['total_paid_month'] = total_usd
        context['employees_paid_count'] = month_payments.values('pompiste').distinct().count()
        context['total_payments'] = month_payments.count()
        
        # Branches
        context['branches'] = Branche.objects.filter(is_active=True).order_by('nom')
        context['branches_count'] = context['branches'].count()
        
        return context


class ParametresView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """System settings"""
    template_name = 'admin/parametres.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Payment methods
        from apps.core.models import MoyenPaiement
        context['moyens_paiement'] = MoyenPaiement.objects.all()
        
        return context
    
class DocumentsView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Documents management page"""
    template_name = 'admin/documents.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filters
        search = self.request.GET.get('search', '')
        category_id = self.request.GET.get('category_id', '')
        visibility = self.request.GET.get('visibility', '')
        
        # Base queryset
        documents = Document.objects.select_related('categorie', 'uploaded_by').order_by('-created_at')
        
        # Apply filters
        if search:
            documents = documents.filter(
                Q(titre__icontains=search) | Q(description__icontains=search)
            )
        
        if category_id:
            documents = documents.filter(categorie_id=category_id)
        
        if visibility:
            documents = documents.filter(visibilite=visibility)
        
        # Add readable file size
        documents_list = []
        for doc in documents:
            doc_data = {
                'id': doc.id,
                'titre': doc.titre,
                'description': doc.description,
                'categorie': doc.categorie,
                'visibilite': doc.visibilite,
                'type_fichier': doc.type_fichier,
                'uploaded_by': doc.uploaded_by.get_full_name() if doc.uploaded_by else 'N/A',
                'created_at': doc.created_at,
                'taille_lisible': self._format_file_size(doc.taille_fichier)
            }
            documents_list.append(doc_data)
        
        context['documents'] = documents_list
        
        # Categories
        context['categories'] = DocumentCategory.objects.filter(is_active=True).order_by('nom')
        context['total_categories'] = context['categories'].count()
        
        # Statistics
        context['total_documents'] = Document.objects.count()
        context['public_documents'] = Document.objects.filter(visibilite='public').count()
        context['confidential_documents'] = Document.objects.filter(visibilite='confidentiel').count()
        
        return context
    
    def _format_file_size(self, size_bytes):
        """Format file size to human readable format"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
        

class ParametresView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """System settings page"""
    template_name = 'admin/parametres.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Fuel types
        context['types_carburant'] = TypeCarburant.objects.all().order_by('nom')
        context['fuel_types_count'] = context['types_carburant'].count()
        
        # Payment methods
        context['moyens_paiement'] = MoyenPaiement.objects.all().order_by('nom')
        context['payment_methods_count'] = context['moyens_paiement'].count()
        
        # Expense categories
        context['categories_depense'] = CategorieDepense.objects.all().order_by('nom')
        context['expense_categories_count'] = context['categories_depense'].count()
        
        # Current exchange rate
        current_rate_obj = TauxChange.objects.filter(is_active=True).first()
        if current_rate_obj:
            context['current_rate'] = float(current_rate_obj.taux_usd_fc)
            context['rate_updated_at'] = current_rate_obj.date_effective
        else:
            context['current_rate'] = 2800.00
            context['rate_updated_at'] = timezone.now()
        
        # Branches stats
        context['total_branches_count'] = Branche.objects.count()
        context['active_branches_count'] = Branche.objects.filter(is_active=True).count()
        
        # Users stats
        context['users_count'] = User.objects.count()
        context['admin_count'] = User.objects.filter(role='admin').count()
        context['manager_count'] = User.objects.filter(role='manager').count()
        context['caissier_count'] = User.objects.filter(role='caissier').count()
        
        return context
    
class ValidationManquantsView(AdminRequiredMixin, TemplateView):
    """
    Template view for Manquants Validation page
    Shows all manquants with filtering, charts, and export options
    """
    template_name = 'admin/validation_manquants.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all active branches for filter
        context['all_branches'] = Branche.objects.filter(is_active=True).order_by('nom')
        
        # Get all pompistes for filter
        context['all_pompistes'] = Pompiste.objects.filter(is_active=True).select_related('branche').order_by('prenom', 'nom')
        
        return context