from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, Count, F, Avg
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import datetime, timedelta, date
from apps.core.models import (
    User, Branche, TauxChange, CategorieDepense, Vente, Depense, 
    PaiementSalaire, Pompiste, Abonne, ConsommationAbonne, TypeCarburant,
    MoyenPaiement, Notification
)
from decimal import Decimal
import json


class CaissierRequiredMixin(UserPassesTestMixin):
    """Mixin to ensure user is authenticated and has caissier role"""
    
    def test_func(self):
        return (self.request.user.is_authenticated and 
                self.request.user.role == 'caissier' and 
                self.request.user.branche is not None)
    
    def handle_no_permission(self):
        messages.error(self.request, 'Accès non autorisé. Vous devez être caissier.')
        return redirect('authentication:login')


class CaissierContextMixin:
    """Mixin to add common context data for caissier templates"""
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # User's branch
        context['user_branche'] = self.request.user.branche
        
        # Expense categories
        context['categories_depense'] = CategorieDepense.objects.filter(is_active=True).order_by('nom')
        
        # Pompistes in this branch
        context['pompistes'] = Pompiste.objects.filter(
            branche=self.request.user.branche,
            is_active=True
        ).order_by('prenom', 'nom')
        
        # System users in this branch (for salary payments)
        context['branch_employees'] = User.objects.filter(
            branche=self.request.user.branche,
            is_active=True
        ).order_by('prenom', 'nom')
        
        # Current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        context['current_rate'] = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        # Fuel types
        context['types_carburant'] = TypeCarburant.objects.filter(is_active=True).order_by('nom')
        
        # Payment methods
        context['moyens_paiement'] = MoyenPaiement.objects.filter(is_active=True).order_by('nom')
        
        # Unread notifications count
        context['unread_notifications'] = Notification.objects.filter(
            destinataire=self.request.user,
            lu=False
        ).count()
        
        return context


# ============================================
# TEMPLATE VIEWS
# ============================================

class CaissierDashboardView(CaissierRequiredMixin, CaissierContextMixin, TemplateView):
    """
    Main Caissier Dashboard
    Displays financial overview, pending sales, and recent transactions
    """
    template_name = 'caissier/dashboard.html'


# ============================================
# API VIEWS - Dashboard
# ============================================

class CaissierDashboardStatsAPIView(CaissierRequiredMixin, View):
    """
    Returns dashboard statistics (KPIs)
    Used for AJAX updates
    """
    
    def get(self, request):
        branche = request.user.branche
        period = request.GET.get('period', 'today')
        devise = request.GET.get('devise', 'USD')
        
        # Calculate date range
        date_range = self._get_date_range(period)
        
        # Get validated sales
        validated_sales = Vente.objects.filter(
            branche=branche,
            created_at__gte=date_range['start'],
            created_at__lte=date_range['end'],
            statut='validee'
        )
        
        total_entries_usd = validated_sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        total_entries_fc = validated_sales.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        
        # Get approved expenses
        expenses = Depense.objects.filter(
            branche=branche,
            created_at__gte=date_range['start'],
            created_at__lte=date_range['end'],
            statut='approuvee'
        )
        
        total_expenses_usd = expenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        total_expenses_fc = expenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        # Calculate balance
        balance_usd = float(total_entries_usd) - float(total_expenses_usd)
        balance_fc = float(total_entries_fc) - float(total_expenses_fc)
        
        # Get current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        current_rate_value = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        # Count pending validations
        pending_validations = Vente.objects.filter(
            branche=branche,
            statut='en_attente'
        ).count()
        
        # Count missing reports
        missing_reports = Vente.objects.filter(
            branche=branche,
            created_at__gte=date_range['start'],
            created_at__lte=date_range['end'],
            statut='manquant'
        ).count()
        
        return JsonResponse({
            'branche_nom': branche.nom,
            'branche_code': branche.code,
            'total_entries_today': f"{total_entries_usd:.2f}",
            'total_entries_today_fc': f"{total_entries_fc:.0f}",
            'total_expenses_today': f"{total_expenses_usd:.2f}",
            'total_expenses_today_fc': f"{total_expenses_fc:.0f}",
            'balance_usd': f"{balance_usd:.2f}",
            'balance_fc': f"{balance_fc:.0f}",
            'balance_status': 'Positif' if balance_usd >= 0 else 'Négatif',
            'pending_validations': pending_validations,
            'missing_reports': missing_reports,
            'current_rate': f"{current_rate_value:.2f}"
        })
    
    def _get_date_range(self, period):
        """Calculate start and end dates for the given period"""
        today = timezone.now().date()
        now = timezone.now()
        
        if period == 'today':
            start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            end = now
        elif period == 'week':
            start = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
            end = now
        elif period == 'month':
            start = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
            end = now
        else:
            start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            end = now
        
        return {'start': start, 'end': end}


class ChartDataAPIView(CaissierRequiredMixin, View):
    """
    Returns chart data for dashboard visualizations
    """
    
    def get(self, request):
        branche = request.user.branche
        period = request.GET.get('period', 'today')
        devise = request.GET.get('devise', 'USD')
        
        # Get sales vs expenses data
        sales_vs_expenses = self._get_sales_vs_expenses_data(branche, period, devise)
        
        # Get forex impact data
        forex_impact = self._get_forex_impact_data(branche, period, devise)
        
        return JsonResponse({
            'sales_vs_expenses': sales_vs_expenses,
            'forex_impact': forex_impact
        })
    
    def _get_sales_vs_expenses_data(self, branche, period, devise):
        """Generate sales vs expenses chart data"""
        today = timezone.now().date()
        
        if period == 'today':
            # Hourly data for today
            data = []
            for hour in range(24):
                hour_start = timezone.make_aware(datetime.combine(today, datetime.min.time()) + timedelta(hours=hour))
                hour_end = hour_start + timedelta(hours=1)
                
                if devise == 'USD':
                    entries = Vente.objects.filter(
                        branche=branche,
                        created_at__gte=hour_start,
                        created_at__lt=hour_end,
                        statut='validee'
                    ).aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
                    
                    expenses = Depense.objects.filter(
                        branche=branche,
                        created_at__gte=hour_start,
                        created_at__lt=hour_end,
                        statut='approuvee',
                        devise='USD'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                else:
                    entries = Vente.objects.filter(
                        branche=branche,
                        created_at__gte=hour_start,
                        created_at__lt=hour_end,
                        statut='validee'
                    ).aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
                    
                    expenses = Depense.objects.filter(
                        branche=branche,
                        created_at__gte=hour_start,
                        created_at__lt=hour_end,
                        statut='approuvee',
                        devise='FC'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                
                data.append({
                    'date': f"{hour:02d}h",
                    'entries': float(entries),
                    'expenses': float(expenses)
                })
        
        elif period == 'week':
            # Daily data for last 7 days
            data = []
            for i in range(7):
                day = today - timedelta(days=6-i)
                day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
                day_end = day_start + timedelta(days=1)
                
                if devise == 'USD':
                    entries = Vente.objects.filter(
                        branche=branche,
                        created_at__gte=day_start,
                        created_at__lt=day_end,
                        statut='validee'
                    ).aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
                    
                    expenses = Depense.objects.filter(
                        branche=branche,
                        created_at__gte=day_start,
                        created_at__lt=day_end,
                        statut='approuvee',
                        devise='USD'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                else:
                    entries = Vente.objects.filter(
                        branche=branche,
                        created_at__gte=day_start,
                        created_at__lt=day_end,
                        statut='validee'
                    ).aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
                    
                    expenses = Depense.objects.filter(
                        branche=branche,
                        created_at__gte=day_start,
                        created_at__lt=day_end,
                        statut='approuvee',
                        devise='FC'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                
                data.append({
                    'date': day.strftime('%d/%m'),
                    'entries': float(entries),
                    'expenses': float(expenses)
                })
        
        else:  # month
            # Weekly data for last 4 weeks
            data = []
            for i in range(4):
                week_start = today - timedelta(days=today.weekday() + 7*(3-i))
                week_end = week_start + timedelta(days=7)
                week_start_aware = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
                week_end_aware = timezone.make_aware(datetime.combine(week_end, datetime.min.time()))
                
                if devise == 'USD':
                    entries = Vente.objects.filter(
                        branche=branche,
                        created_at__gte=week_start_aware,
                        created_at__lt=week_end_aware,
                        statut='validee'
                    ).aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
                    
                    expenses = Depense.objects.filter(
                        branche=branche,
                        created_at__gte=week_start_aware,
                        created_at__lt=week_end_aware,
                        statut='approuvee',
                        devise='USD'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                else:
                    entries = Vente.objects.filter(
                        branche=branche,
                        created_at__gte=week_start_aware,
                        created_at__lt=week_end_aware,
                        statut='validee'
                    ).aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
                    
                    expenses = Depense.objects.filter(
                        branche=branche,
                        created_at__gte=week_start_aware,
                        created_at__lt=week_end_aware,
                        statut='approuvee',
                        devise='FC'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                
                data.append({
                    'date': f"S{i+1}",
                    'entries': float(entries),
                    'expenses': float(expenses)
                })
        
        return data
    
    def _get_forex_impact_data(self, branche, period, devise):
        """Generate forex impact by fuel type chart data"""
        today = timezone.now().date()
        
        if period == 'today':
            start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        elif period == 'week':
            start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
        else:
            start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
        
        end_date = timezone.now()
        
        # Get current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        current_rate_value = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        # Get sales by fuel type
        sales_by_fuel = Vente.objects.filter(
            branche=branche,
            created_at__gte=start_date,
            created_at__lte=end_date,
            statut='validee'
        ).values('type_carburant__nom').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            avg_rate=Avg('taux_change')
        )
        
        data = []
        for item in sales_by_fuel:
            # Calculate forex impact (difference between rate used and current rate)
            avg_rate = float(item['avg_rate'] or current_rate_value)
            total_fc = float(item['total_fc'] or 0)
            
            # Impact = (current_rate - avg_rate) * (total_fc / avg_rate)
            impact = ((float(current_rate_value) - avg_rate) / avg_rate) * total_fc if avg_rate > 0 else 0
            
            if devise == 'USD':
                impact_value = impact / float(current_rate_value) if current_rate_value > 0 else 0
            else:
                impact_value = impact
            
            data.append({
                'fuel': item['type_carburant__nom'],
                'impact': round(impact_value, 2)
            })
        
        return data


class RecentTransactionsAPIView(CaissierRequiredMixin, View):
    """
    Returns recent transactions (sales and expenses)
    """
    
    def get(self, request):
        branche = request.user.branche
        limit = int(request.GET.get('limit', 10))
        
        transactions = []
        
        # Get recent validated sales
        recent_sales = Vente.objects.filter(
            branche=branche,
            statut='validee'
        ).select_related('pompiste', 'type_carburant').order_by('-validated_at')[:limit]
        
        for sale in recent_sales:
            transactions.append({
                'type': 'entry',
                'description': f"Vente {sale.type_carburant.nom} - {sale.pompiste.get_full_name()}",
                'amount': float(sale.montant_usd),
                'currency': 'USD',
                'date': sale.validated_at.strftime('%d/%m/%Y') if sale.validated_at else sale.created_at.strftime('%d/%m/%Y'),
                'time': sale.validated_at.strftime('%H:%M') if sale.validated_at else sale.created_at.strftime('%H:%M'),
                'timestamp': sale.validated_at.timestamp() if sale.validated_at else sale.created_at.timestamp()
            })
        
        # Get recent expenses
        recent_expenses = Depense.objects.filter(
            branche=branche,
            statut='approuvee'
        ).select_related('categorie').order_by('-created_at')[:limit]
        
        for expense in recent_expenses:
            transactions.append({
                'type': 'expense',
                'description': f"Dépense {expense.categorie.nom}",
                'amount': float(expense.montant),
                'currency': expense.devise,
                'date': expense.created_at.strftime('%d/%m/%Y'),
                'time': expense.created_at.strftime('%H:%M'),
                'timestamp': expense.created_at.timestamp()
            })
        
        # Sort by timestamp (most recent first)
        transactions.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return JsonResponse({
            'transactions': transactions[:limit]
        })


# ============================================
# API VIEWS - Sales Validation
# ============================================

class PendingSalesView(CaissierRequiredMixin, View):
    """
    Returns list of pending sales awaiting validation
    """
    
    def get(self, request):
        branche = request.user.branche
        
        pending_sales = Vente.objects.filter(
            branche=branche,
            statut='en_attente'
        ).select_related(
            'pompiste', 'manager', 'type_carburant', 'moyen_paiement'
        ).order_by('-created_at')
        
        sales_data = []
        for sale in pending_sales:
            sales_data.append({
                'id': sale.id,
                'created_at': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                'pompiste': sale.pompiste.get_full_name(),
                'manager': sale.manager.get_full_name() if sale.manager else 'N/A',
                'carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'moyen_paiement': sale.moyen_paiement.nom,
                'taux_change': str(sale.taux_change),
                'observations': sale.observations or '',
                'statut': sale.statut,
                'statut_display': sale.get_statut_display()
            })
        
        return JsonResponse({'pending_sales': sales_data})


class SaleDetailAPIView(CaissierRequiredMixin, View):
    """
    Returns detailed information for a specific sale
    """
    
    def get(self, request, sale_id):
        branche = request.user.branche
        
        try:
            sale = Vente.objects.select_related(
                'pompiste', 'manager', 'type_carburant', 'moyen_paiement', 'branche'
            ).get(id=sale_id, branche=branche)
            
            sale_data = {
                'id': sale.id,
                'created_at': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                'pompiste': sale.pompiste.get_full_name(),
                'manager': sale.manager.get_full_name() if sale.manager else 'N/A',
                'carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'moyen_paiement': sale.moyen_paiement.nom,
                'taux_change': str(sale.taux_change),
                'observations': sale.observations or '',
                'statut': sale.statut,
                'statut_display': sale.get_statut_display()
            }
            
            return JsonResponse({'sale': sale_data})
            
        except Vente.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Vente introuvable'}, status=404)


class ValidateSaleView(CaissierRequiredMixin, View):
    """
    Validates a sale or reports missing amount
    """
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            sale_id = data.get('sale_id')
            action = data.get('action')  # 'validate' or 'report_missing'
            
            if not sale_id or not action:
                return JsonResponse({
                    'success': False,
                    'message': 'ID de vente et action requis'
                })
            
            # Get the sale
            try:
                vente = Vente.objects.get(
                    id=sale_id,
                    branche=request.user.branche,
                    statut='en_attente'
                )
            except Vente.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Vente introuvable ou déjà traitée'
                })
            
            if action == 'validate':
                # Get missing amounts (if any)
                manquant_usd = Decimal(str(data.get('manquant_usd', 0)))
                manquant_fc = Decimal(str(data.get('manquant_fc', 0)))
                raison_manquant = data.get('raison_manquant', '')
                
                # If there's missing amount, update the sale
                if manquant_usd > 0 or manquant_fc > 0:
                    if not raison_manquant:
                        return JsonResponse({
                            'success': False,
                            'message': 'Raison du manquant requise'
                        })
                    
                    vente.manquant_usd = manquant_usd
                    vente.manquant_fc = manquant_fc
                    vente.raison_manquant = raison_manquant
                    vente.statut = 'manquant'
                else:
                    vente.statut = 'validee'
                
                vente.caissier = request.user
                vente.validated_at = timezone.now()
                vente.save()
                
                # Create notification for admin
                from apps.admin_module.utils import create_notification
                create_notification(
                    destinataire=vente.branche.admin if hasattr(vente.branche, 'admin') else None,
                    titre=f"Vente #{vente.id} validée",
                    message=f"La vente #{vente.id} a été validée par {request.user.get_full_name()}",
                    type_notification='vente_pending',
                    priorite='normale',
                    expediteur=request.user,
                    objet_id=vente.id
                )
                
                return JsonResponse({
                    'success': True,
                    'message': f'Vente #{vente.id} validée avec succès',
                    'sale_id': vente.id
                })
                
            elif action == 'report_missing':
                # Report missing amounts
                manquant_usd = Decimal(str(data.get('manquant_usd', 0)))
                manquant_fc = Decimal(str(data.get('manquant_fc', 0)))
                raison_manquant = data.get('raison_manquant', '')
                
                if manquant_usd <= 0 and manquant_fc <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Montant manquant requis'
                    })
                
                if not raison_manquant:
                    return JsonResponse({
                        'success': False,
                        'message': 'Raison du manquant requise'
                    })
                
                vente.manquant_usd = manquant_usd
                vente.manquant_fc = manquant_fc
                vente.raison_manquant = raison_manquant
                vente.statut = 'manquant'
                vente.caissier = request.user
                vente.validated_at = timezone.now()
                vente.save()
                
                # Create notification for admin
                from apps.admin_module.utils import create_notification
                admins = User.objects.filter(role='admin', is_active=True)
                for admin in admins:
                    create_notification(
                        destinataire=admin,
                        titre=f"Manquant signalé - Vente #{vente.id}",
                        message=f"Manquant de ${manquant_usd} USD / {manquant_fc} FC signalé par {request.user.get_full_name()}. Raison: {raison_manquant}",
                        type_notification='manquant',
                        priorite='haute',
                        expediteur=request.user,
                        objet_id=vente.id
                    )
                
                return JsonResponse({
                    'success': True,
                    'message': f'Manquant signalé pour vente #{vente.id}',
                    'sale_id': vente.id
                })
            
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Action invalide'
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


class ValidatedSalesHistoryView(CaissierRequiredMixin, View):
    """
    Returns history of validated sales
    """
    
    def get(self, request):
        branche = request.user.branche
        
        # Get filter parameters
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        pompiste_id = request.GET.get('pompiste_id')
        
        # Base queryset
        sales = Vente.objects.filter(
            branche=branche,
            statut__in=['validee', 'manquant']
        ).select_related('pompiste', 'type_carburant', 'caissier')
        
        # Apply filters
        if date_start:
            try:
                start_date = datetime.strptime(date_start, '%Y-%m-%d').date()
                sales = sales.filter(validated_at__date__gte=start_date)
            except ValueError:
                pass
        
        if date_end:
            try:
                end_date = datetime.strptime(date_end, '%Y-%m-%d').date()
                sales = sales.filter(validated_at__date__lte=end_date)
            except ValueError:
                pass
        
        if pompiste_id:
            sales = sales.filter(pompiste_id=pompiste_id)
        
        # Order by most recent
        sales = sales.order_by('-validated_at')[:100]
        
        sales_data = []
        for sale in sales:
            sales_data.append({
                'id': sale.id,
                'validated_at': sale.validated_at.strftime('%d/%m/%Y %H:%M') if sale.validated_at else 'N/A',
                'pompiste': sale.pompiste.get_full_name(),
                'carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'manquant_usd': str(sale.manquant_usd) if sale.manquant_usd else '0.00',
                'manquant_fc': str(sale.manquant_fc) if sale.manquant_fc else '0',
                'statut': sale.statut,
                'statut_display': sale.get_statut_display(),
                'caissier': sale.caissier.get_full_name() if sale.caissier else 'N/A'
            })
        
        return JsonResponse({'sales': sales_data})
    

class VentesPageView(CaissierRequiredMixin, CaissierContextMixin, TemplateView):
    """
    Ventes page template view
    """
    template_name = 'caissier/ventes.html'


class SalesListAPIView(CaissierRequiredMixin, View):
    """
    Returns list of sales with filters
    """
    
    def get(self, request):
        branche = request.user.branche
        
        # Get filter parameters
        period = request.GET.get('period', 'month')
        status = request.GET.get('status', 'all')
        fuel_id = request.GET.get('fuel', 'all')
        pompiste_id = request.GET.get('pompiste', 'all')
        
        # Calculate date range
        today = timezone.now().date()
        if period == 'today':
            start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        elif period == 'week':
            start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
        elif period == 'month':
            start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
        else:  # all
            start_date = timezone.make_aware(datetime.combine(date(2020, 1, 1), datetime.min.time()))
        
        end_date = timezone.now()
        
        # Base queryset
        sales = Vente.objects.filter(
            branche=branche,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).select_related('pompiste', 'manager', 'caissier', 'type_carburant', 'moyen_paiement')
        
        # Apply filters
        if status != 'all':
            sales = sales.filter(statut=status)
        
        if fuel_id != 'all':
            sales = sales.filter(type_carburant_id=fuel_id)
        
        if pompiste_id != 'all':
            sales = sales.filter(pompiste_id=pompiste_id)
        
        # Calculate statistics
        all_sales = sales
        statistics = {
            'total': all_sales.count(),
            'pending': all_sales.filter(statut='en_attente').count(),
            'validated': all_sales.filter(statut='validee').count(),
            'missing': all_sales.filter(statut='manquant').count()
        }
        
        # Order and limit
        sales = sales.order_by('-created_at')[:500]  # Limit to 500 for performance
        
        # Build response
        sales_data = []
        for sale in sales:
            sales_data.append({
                'id': sale.id,
                'created_at': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                'created_at_date': sale.created_at.strftime('%d/%m/%Y'),
                'created_at_time': sale.created_at.strftime('%H:%M'),
                'pompiste': sale.pompiste.get_full_name(),
                'manager': sale.manager.get_full_name() if sale.manager else 'N/A',
                'caissier': sale.caissier.get_full_name() if sale.caissier else '-',
                'carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'moyen_paiement': sale.moyen_paiement.nom,
                'taux_change': str(sale.taux_change),
                'observations': sale.observations or '',
                'statut': sale.statut,
                'statut_display': sale.get_statut_display(),
                'manquant_usd': str(sale.manquant_usd) if sale.manquant_usd else '0.00',
                'manquant_fc': str(sale.manquant_fc) if sale.manquant_fc else '0',
                'raison_manquant': sale.raison_manquant or ''
            })
        
        return JsonResponse({
            'sales': sales_data,
            'statistics': statistics
        })


class ExportSalesExcelView(CaissierRequiredMixin, View):
    """
    Export sales to Excel
    """
    
    def get(self, request):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment, PatternFill
            from django.http import HttpResponse
            
            branche = request.user.branche
            period = request.GET.get('period', 'month')
            status = request.GET.get('status', 'all')
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'today':
                start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            elif period == 'week':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
            elif period == 'month':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
            else:
                start_date = timezone.make_aware(datetime.combine(date(2020, 1, 1), datetime.min.time()))
            
            # Get sales
            sales = Vente.objects.filter(
                branche=branche,
                created_at__gte=start_date
            ).select_related('pompiste', 'type_carburant', 'moyen_paiement', 'caissier')
            
            if status != 'all':
                sales = sales.filter(statut=status)
            
            sales = sales.order_by('-created_at')
            
            # Create workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Ventes"
            
            # Header style
            header_fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            # Headers
            headers = ['Date', 'Pompiste', 'Carburant', 'Quantité (L)', 'USD', 'FC', 'Paiement', 'Statut', 'Caissier']
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center')
            
            # Data rows
            for row_idx, sale in enumerate(sales, 2):
                ws.cell(row=row_idx, column=1, value=sale.created_at.strftime('%d/%m/%Y %H:%M'))
                ws.cell(row=row_idx, column=2, value=sale.pompiste.get_full_name())
                ws.cell(row=row_idx, column=3, value=sale.type_carburant.nom)
                ws.cell(row=row_idx, column=4, value=float(sale.quantite))
                ws.cell(row=row_idx, column=5, value=float(sale.montant_usd))
                ws.cell(row=row_idx, column=6, value=float(sale.montant_fc))
                ws.cell(row=row_idx, column=7, value=sale.moyen_paiement.nom)
                ws.cell(row=row_idx, column=8, value=sale.get_statut_display())
                ws.cell(row=row_idx, column=9, value=sale.caissier.get_full_name() if sale.caissier else '-')
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Create response
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename=ventes_{branche.code}_{timezone.now().strftime("%Y%m%d")}.xlsx'
            wb.save(response)
            return response
            
        except Exception as e:
            import traceback
            print(f"Error exporting to Excel: {traceback.format_exc()}")
            return JsonResponse({'success': False, 'message': str(e)}, status=500)


class ExportSalesPDFView(CaissierRequiredMixin, View):
    """
    Export sales to PDF
    """
    
    def get(self, request):
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
            from io import BytesIO
            
            branche = request.user.branche
            period = request.GET.get('period', 'month')
            status = request.GET.get('status', 'all')
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'today':
                start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            elif period == 'week':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
            elif period == 'month':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
            else:
                start_date = timezone.make_aware(datetime.combine(date(2020, 1, 1), datetime.min.time()))
            
            # Get sales
            sales = Vente.objects.filter(
                branche=branche,
                created_at__gte=start_date
            ).select_related('pompiste', 'type_carburant', 'moyen_paiement', 'caissier')
            
            if status != 'all':
                sales = sales.filter(statut=status)
            
            sales = sales.order_by('-created_at')[:200]  # Limit for PDF
            
            # Create PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                textColor=colors.HexColor('#DC2626'),
                spaceAfter=30,
                alignment=TA_CENTER
            )
            
            # Title
            title = Paragraph(f"Liste des Ventes - {branche.nom}", title_style)
            elements.append(title)
            
            subtitle = Paragraph(
                f"Période: {start_date.strftime('%d/%m/%Y')} - {timezone.now().strftime('%d/%m/%Y')}<br/>Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')}",
                styles['Normal']
            )
            elements.append(subtitle)
            elements.append(Spacer(1, 0.3*inch))
            
            # Table data
            data = [['Date', 'Pompiste', 'Carburant', 'Qté (L)', 'USD', 'FC', 'Statut']]
            
            for sale in sales:
                data.append([
                    sale.created_at.strftime('%d/%m %H:%M'),
                    sale.pompiste.get_full_name()[:20],
                    sale.type_carburant.nom[:15],
                    f"{float(sale.quantite):.1f}",
                    f"${float(sale.montant_usd):.2f}",
                    f"{float(sale.montant_fc):.0f}",
                    sale.get_statut_display()
                ])
            
            # Create table
            table = Table(data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            
            elements.append(table)
            
            # Build PDF
            doc.build(elements)
            buffer.seek(0)
            
            # Create response
            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename=ventes_{branche.code}_{timezone.now().strftime("%Y%m%d")}.pdf'
            return response
            
        except Exception as e:
            import traceback
            print(f"Error exporting to PDF: {traceback.format_exc()}")
            return JsonResponse({'success': False, 'message': str(e)}, status=500)


class DepensesPageView(CaissierRequiredMixin, CaissierContextMixin, TemplateView):
    """
    Dépenses (Expenses) page template view
    """
    template_name = 'caissier/depenses.html'


class ExpensesListAPIView(CaissierRequiredMixin, View):
    """
    Returns list of expenses with filters
    """
    
    def get(self, request):
        branche = request.user.branche
        
        # Get filter parameters
        period = request.GET.get('period', 'month')
        category_id = request.GET.get('category', 'all')
        currency = request.GET.get('currency', 'all')
        status = request.GET.get('status', 'all')
        
        # Calculate date range
        today = timezone.now().date()
        if period == 'today':
            start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        elif period == 'week':
            start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
        elif period == 'month':
            start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
        else:  # all
            start_date = timezone.make_aware(datetime.combine(date(2020, 1, 1), datetime.min.time()))
        
        end_date = timezone.now()
        
        # Base queryset
        expenses = Depense.objects.filter(
            branche=branche,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).select_related('categorie', 'created_by')
        
        # Apply filters
        if category_id != 'all':
            expenses = expenses.filter(categorie_id=category_id)
        
        if currency != 'all':
            expenses = expenses.filter(devise=currency)
        
        if status != 'all':
            expenses = expenses.filter(statut=status)
        
        # Calculate statistics
        all_expenses = expenses
        total_usd = all_expenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        total_fc = all_expenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        statistics = {
            'total': all_expenses.count(),
            'pending': all_expenses.filter(statut='en_attente').count(),
            'total_usd': float(total_usd),
            'total_fc': float(total_fc)
        }
        
        # Order and limit
        expenses = expenses.order_by('-created_at')[:500]
        
        # Build response
        expenses_data = []
        for expense in expenses:
            expenses_data.append({
                'id': expense.id,
                'date': expense.created_at.strftime('%d/%m/%Y'),
                'time': expense.created_at.strftime('%H:%M'),
                'categorie': expense.categorie.nom,
                'description': expense.description,
                'montant': str(expense.montant),
                'devise': expense.devise,
                'methode_paiement': expense.get_methode_paiement_display(),
                'beneficiaire': expense.beneficiaire or '-',
                'created_by': expense.created_by.get_full_name(),
                'statut': expense.statut,
                'statut_display': expense.get_statut_display(),
                'justificatif_url': expense.justificatif.url if expense.justificatif else None
            })
        
        return JsonResponse({
            'expenses': expenses_data,
            'statistics': statistics
        })


class RegisterExpenseView(CaissierRequiredMixin, View):
    """
    Register a new expense
    """
    
    def post(self, request):
        try:
            # Get form data
            categorie_id = request.POST.get('categorie_id')
            montant = request.POST.get('montant')
            devise = request.POST.get('devise')
            methode_paiement = request.POST.get('methode_paiement')
            beneficiaire = request.POST.get('beneficiaire', '')
            description = request.POST.get('description')
            justificatif = request.FILES.get('justificatif')
            
            # Validate required fields
            if not all([categorie_id, montant, devise, methode_paiement, description]):
                return JsonResponse({
                    'success': False,
                    'message': 'Tous les champs obligatoires doivent être remplis'
                })
            
            # Get category
            try:
                categorie = CategorieDepense.objects.get(id=categorie_id, is_active=True)
            except CategorieDepense.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Catégorie invalide'
                })
            
            # Create expense
            depense = Depense.objects.create(
                branche=request.user.branche,
                categorie=categorie,
                montant=Decimal(montant),
                devise=devise,
                methode_paiement=methode_paiement,
                beneficiaire=beneficiaire,
                description=description,
                created_by=request.user,
                statut='approuvee'  # Caissier expenses are auto-approved
            )
            
            # Handle file upload
            if justificatif:
                depense.justificatif = justificatif
                depense.save()
            
            # Create notification for admin
            admins = User.objects.filter(role='admin', is_active=True)
            for admin in admins:
                Notification.objects.create(
                    destinataire=admin,
                    titre=f"Nouvelle dépense - {categorie.nom}",
                    message=f"Dépense de {montant} {devise} enregistrée par {request.user.get_full_name()} à {request.user.branche.nom}",
                    type_notification='depense',
                    priorite='normale',
                    expediteur=request.user,
                    objet_id=depense.id
                )
            
            return JsonResponse({
                'success': True,
                'message': 'Dépense enregistrée avec succès',
                'expense': {
                    'id': depense.id,
                    'montant': str(depense.montant),
                    'devise': depense.devise,
                    'categorie': categorie.nom,
                    'created_at': depense.created_at.strftime('%d/%m/%Y %H:%M')
                }
            })
            
        except Exception as e:
            import traceback
            print(f"Error registering expense: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'enregistrement: {str(e)}'
            })


class RequestExpenseCategoryView(CaissierRequiredMixin, View):
    """
    Request a new expense category
    """
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            nom = data.get('nom', '').strip()
            justification = data.get('justification', '').strip()
            
            if not nom or not justification:
                return JsonResponse({
                    'success': False,
                    'message': 'Nom et justification requis'
                })
            
            # Check if category already exists
            if CategorieDepense.objects.filter(nom__iexact=nom).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Cette catégorie existe déjà'
                })
            
            # Create pending category with justification stored in description
            categorie = CategorieDepense.objects.create(
                nom=nom,
                description=f"Demandée par: {request.user.get_full_name()} ({request.user.branche.nom})\nJustification: {justification}",
                is_active=False,  # Inactive until admin approves
                created_by=request.user
            )
            
            # Notify all admins
            admins = User.objects.filter(role='admin', is_active=True)
            for admin in admins:
                Notification.objects.create(
                    destinataire=admin,
                    titre=f"Demande de nouvelle catégorie: {nom}",
                    message=f"{request.user.get_full_name()} ({request.user.branche.nom}) demande la création de la catégorie '{nom}'. Justification: {justification}",
                    type_notification='demande_categorie',
                    priorite='normale',
                    expediteur=request.user,
                    objet_id=categorie.id
                )
            
            return JsonResponse({
                'success': True,
                'message': 'Demande envoyée à l\'Admin. Vous serez notifié de la décision.',
                'category': {
                    'id': categorie.id,
                    'nom': categorie.nom
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


class ExpenseDetailAPIView(CaissierRequiredMixin, View):
    """
    Returns detailed information for a specific expense
    """
    
    def get(self, request, expense_id):
        branche = request.user.branche
        
        try:
            expense = Depense.objects.select_related(
                'categorie', 'created_by', 'branche'
            ).get(id=expense_id, branche=branche)
            
            expense_data = {
                'id': expense.id,
                'date': expense.created_at.strftime('%d/%m/%Y'),
                'time': expense.created_at.strftime('%H:%M'),
                'categorie': expense.categorie.nom,
                'description': expense.description,
                'montant': str(expense.montant),
                'devise': expense.devise,
                'methode_paiement': expense.get_methode_paiement_display(),
                'beneficiaire': expense.beneficiaire or '-',
                'created_by': expense.created_by.get_full_name(),
                'statut': expense.statut,
                'statut_display': expense.get_statut_display(),
                'justificatif_url': expense.justificatif.url if expense.justificatif else None
            }
            
            return JsonResponse({'expense': expense_data})
            
        except Depense.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Dépense introuvable'}, status=404)


class ExportExpensesExcelView(CaissierRequiredMixin, View):
    """
    Export expenses to Excel
    """
    
    def get(self, request):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment, PatternFill
            from django.http import HttpResponse
            
            branche = request.user.branche
            period = request.GET.get('period', 'month')
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'today':
                start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            elif period == 'week':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
            elif period == 'month':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
            else:
                start_date = timezone.make_aware(datetime.combine(date(2020, 1, 1), datetime.min.time()))
            
            # Get expenses
            expenses = Depense.objects.filter(
                branche=branche,
                created_at__gte=start_date
            ).select_related('categorie', 'created_by').order_by('-created_at')
            
            # Create workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Dépenses"
            
            # Header style
            header_fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            # Headers
            headers = ['Date', 'Catégorie', 'Description', 'Montant', 'Devise', 'Paiement', 'Bénéficiaire', 'Statut', 'Enregistré par']
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center')
            
            # Data rows
            for row_idx, expense in enumerate(expenses, 2):
                ws.cell(row=row_idx, column=1, value=expense.created_at.strftime('%d/%m/%Y %H:%M'))
                ws.cell(row=row_idx, column=2, value=expense.categorie.nom)
                ws.cell(row=row_idx, column=3, value=expense.description)
                ws.cell(row=row_idx, column=4, value=float(expense.montant))
                ws.cell(row=row_idx, column=5, value=expense.devise)
                ws.cell(row=row_idx, column=6, value=expense.get_methode_paiement_display())
                ws.cell(row=row_idx, column=7, value=expense.beneficiaire or '-')
                ws.cell(row=row_idx, column=8, value=expense.get_statut_display())
                ws.cell(row=row_idx, column=9, value=expense.created_by.get_full_name())
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Create response
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename=depenses_{branche.code}_{timezone.now().strftime("%Y%m%d")}.xlsx'
            wb.save(response)
            return response
            
        except Exception as e:
            import traceback
            print(f"Error exporting to Excel: {traceback.format_exc()}")
            return JsonResponse({'success': False, 'message': str(e)}, status=500)


class ExportExpensesPDFView(CaissierRequiredMixin, View):
    """
    Export expenses to PDF
    """
    
    def get(self, request):
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER
            from io import BytesIO
            
            branche = request.user.branche
            period = request.GET.get('period', 'month')
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'today':
                start_date = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            elif period == 'week':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=7), datetime.min.time()))
            elif period == 'month':
                start_date = timezone.make_aware(datetime.combine(today - timedelta(days=30), datetime.min.time()))
            else:
                start_date = timezone.make_aware(datetime.combine(date(2020, 1, 1), datetime.min.time()))
            
            # Get expenses
            expenses = Depense.objects.filter(
                branche=branche,
                created_at__gte=start_date
            ).select_related('categorie', 'created_by').order_by('-created_at')[:200]
            
            # Create PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                textColor=colors.HexColor('#DC2626'),
                spaceAfter=30,
                alignment=TA_CENTER
            )
            
            # Title
            title = Paragraph(f"Liste des Dépenses - {branche.nom}", title_style)
            elements.append(title)
            
            subtitle = Paragraph(
                f"Période: {start_date.strftime('%d/%m/%Y')} - {timezone.now().strftime('%d/%m/%Y')}<br/>Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')}",
                styles['Normal']
            )
            elements.append(subtitle)
            elements.append(Spacer(1, 0.3*inch))
            
            # Table data
            data = [['Date', 'Catégorie', 'Description', 'Montant', 'Devise', 'Statut']]
            
            for expense in expenses:
                data.append([
                    expense.created_at.strftime('%d/%m %H:%M'),
                    expense.categorie.nom[:20],
                    expense.description[:30] + '...' if len(expense.description) > 30 else expense.description,
                    f"{float(expense.montant):.2f}",
                    expense.devise,
                    expense.get_statut_display()
                ])
            
            # Create table
            table = Table(data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            
            elements.append(table)
            
            # Build PDF
            doc.build(elements)
            buffer.seek(0)
            
            # Create response
            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename=depenses_{branche.code}_{timezone.now().strftime("%Y%m%d")}.pdf'
            return response
            
        except Exception as e:
            import traceback
            print(f"Error exporting to PDF: {traceback.format_exc()}")
            return JsonResponse({'success': False, 'message': str(e)}, status=500)


class SalairesPageView(CaissierRequiredMixin, CaissierContextMixin, TemplateView):
    """
    Salaires (Salary Payments) page template view
    """
    template_name = 'caissier/salaires.html'


class EmployeesListAPIView(CaissierRequiredMixin, View):
    """
    Returns list of employees (pompistes + system users) with payment status
    """
    
    def get(self, request):
        branche = request.user.branche
        
        # Get filter parameters
        employee_type = request.GET.get('type', 'all')
        status = request.GET.get('status', 'all')
        month_str = request.GET.get('month', '')
        
        # Parse month
        if month_str:
            try:
                year, month = map(int, month_str.split('-'))
                filter_month = date(year, month, 1)
            except:
                filter_month = date.today().replace(day=1)
        else:
            filter_month = date.today().replace(day=1)
        
        employees_data = []
        
        # Get Pompistes
        if employee_type in ['all', 'pompiste']:
            pompistes = Pompiste.objects.filter(
                branche=branche,
                is_active=True
            ).order_by('nom', 'prenom')
            
            for pompiste in pompistes:
                # Calculate payment status for this month
                payments_this_month = PaiementSalaire.objects.filter(
                    pompiste=pompiste,
                    mois_paiement=filter_month,
                    statut='paye'
                )
                
                total_paid_this_month = payments_this_month.aggregate(
                    Sum('montant_paye')
                )['montant_paye__sum'] or Decimal('0')
                
                # Get salary info
                salary = pompiste.salaire or Decimal('0')
                salary_currency = pompiste.devise_salaire or 'USD'
                
                # Check if fully paid
                paid_this_month = total_paid_this_month >= salary if salary > 0 else False
                
                # Get last payment
                last_payment = payments_this_month.order_by('-date_paiement').first()
                
                # Calculate remaining amount
                remaining = salary - total_paid_this_month if salary > 0 else Decimal('0')
                
                # Apply status filter
                if status == 'paid' and not paid_this_month:
                    continue
                if status == 'pending' and paid_this_month:
                    continue
                
                employees_data.append({
                    'id': pompiste.id,
                    'type': 'pompiste',
                    'name': pompiste.get_full_name(),
                    'initials': f"{pompiste.prenom[0]}{pompiste.nom[0]}" if pompiste.prenom and pompiste.nom else "??",
                    'email': None,
                    'phone': pompiste.telephone or None,
                    'salary': str(salary),
                    'salary_currency': salary_currency,
                    'paid_this_month': paid_this_month,
                    'total_paid': str(total_paid_this_month),
                    'remaining': str(remaining),
                    'last_payment': {
                        'date': last_payment.date_paiement.strftime('%d/%m/%Y'),
                        'amount': str(last_payment.montant_paye),
                        'currency': last_payment.devise_paiement,
                        'type': last_payment.type_paiement
                    } if last_payment else None
                })
        
        # Get System Users
        if employee_type in ['all', 'user']:
            users = User.objects.filter(
                branche=branche,
                is_active=True,
                role__in=['admin', 'manager', 'caissier']
            ).order_by('nom', 'prenom')
            
            for user in users:
                # Calculate payment status for this month
                payments_this_month = PaiementSalaire.objects.filter(
                    employe_user=user,
                    mois_paiement=filter_month,
                    statut='paye'
                )
                
                total_paid_this_month = payments_this_month.aggregate(
                    Sum('montant_paye')
                )['montant_paye__sum'] or Decimal('0')
                
                # Get salary info
                salary = user.salaire or Decimal('0')
                salary_currency = user.devise_salaire or 'USD'
                
                # Check if fully paid
                paid_this_month = total_paid_this_month >= salary if salary > 0 else False
                
                # Get last payment
                last_payment = payments_this_month.order_by('-date_paiement').first()
                
                # Calculate remaining amount
                remaining = salary - total_paid_this_month if salary > 0 else Decimal('0')
                
                # Apply status filter
                if status == 'paid' and not paid_this_month:
                    continue
                if status == 'pending' and paid_this_month:
                    continue
                
                employees_data.append({
                    'id': user.id,
                    'type': 'user',
                    'name': user.get_full_name(),
                    'initials': f"{user.prenom[0]}{user.nom[0]}" if user.prenom and user.nom else "??",
                    'email': user.email,
                    'phone': user.telephone or None,
                    'salary': str(salary),
                    'salary_currency': salary_currency,
                    'paid_this_month': paid_this_month,
                    'total_paid': str(total_paid_this_month),
                    'remaining': str(remaining),
                    'last_payment': {
                        'date': last_payment.date_paiement.strftime('%d/%m/%Y'),
                        'amount': str(last_payment.montant_paye),
                        'currency': last_payment.devise_paiement,
                        'type': last_payment.type_paiement
                    } if last_payment else None
                })
        
        # Calculate statistics
        total_employees = len(employees_data)
        paid_count = sum(1 for e in employees_data if e['paid_this_month'])
        pending_count = total_employees - paid_count
        
        # Calculate total paid this month
        total_paid_usd = PaiementSalaire.objects.filter(
            branche=branche,
            mois_paiement=filter_month,
            statut='paye',
            devise_paiement='USD'
        ).aggregate(Sum('montant_paye'))['montant_paye__sum'] or 0
        
        total_paid_fc = PaiementSalaire.objects.filter(
            branche=branche,
            mois_paiement=filter_month,
            statut='paye',
            devise_paiement='FC'
        ).aggregate(Sum('montant_paye'))['montant_paye__sum'] or 0
        
        # Convert FC to USD for display
        current_rate = TauxChange.objects.filter(is_active=True).first()
        rate = float(current_rate.taux_usd_fc) if current_rate else 2800.0
        total_paid_usd_equivalent = float(total_paid_usd) + (float(total_paid_fc) / rate)
        
        statistics = {
            'total': total_employees,
            'paid': paid_count,
            'pending': pending_count,
            'total_paid': total_paid_usd_equivalent
        }
        
        return JsonResponse({
            'employees': employees_data,
            'statistics': statistics
        })


class PaySalaryView(CaissierRequiredMixin, View):
    """
    Process salary payment (full or advance)
    Supports both pompistes and system users
    """
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            employee_id = data.get('employee_id')
            employee_type = data.get('employee_type')
            month_str = data.get('month')
            amount = data.get('amount')
            currency = data.get('currency')
            payment_type = data.get('payment_type', 'salaire_complet')  # salaire_complet or avance
            payment_method = data.get('payment_method', 'cash')
            notes = data.get('notes', '')
            
            # Validate required fields
            if not all([employee_id, employee_type, month_str, amount, currency]):
                return JsonResponse({
                    'success': False,
                    'message': 'Tous les champs obligatoires doivent être remplis'
                })
            
            # Parse month
            try:
                year, month = map(int, month_str.split('-'))
                period = date(year, month, 1)
            except:
                return JsonResponse({
                    'success': False,
                    'message': 'Format de mois invalide'
                })
            
            # Get employee and salary info
            if employee_type == 'pompiste':
                try:
                    employee = Pompiste.objects.get(
                        id=employee_id,
                        branche=request.user.branche,
                        is_active=True
                    )
                    employee_name = employee.get_full_name()
                    total_salary = employee.salaire or Decimal('0')
                    salary_currency = employee.devise_salaire or currency
                except Pompiste.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Pompiste introuvable'
                    })
            elif employee_type == 'user':
                try:
                    employee = User.objects.get(
                        id=employee_id,
                        branche=request.user.branche,
                        is_active=True
                    )
                    employee_name = employee.get_full_name()
                    total_salary = employee.salaire or Decimal('0')
                    salary_currency = employee.devise_salaire or currency
                except User.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Utilisateur introuvable'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Type d\'employé invalide'
                })
            
            # Validate amount
            payment_amount = Decimal(amount)
            if payment_amount <= 0:
                return JsonResponse({
                    'success': False,
                    'message': 'Le montant doit être supérieur à 0'
                })
            
            # Calculate previous advances this month
            if employee_type == 'pompiste':
                previous_payments = PaiementSalaire.objects.filter(
                    pompiste=employee,
                    mois_paiement=period,
                    statut='paye'
                )
            else:
                previous_payments = PaiementSalaire.objects.filter(
                    employe_user=employee,
                    mois_paiement=period,
                    statut='paye'
                )
            
            total_previous = previous_payments.aggregate(
                Sum('montant_paye')
            )['montant_paye__sum'] or Decimal('0')
            
            # Check if already fully paid
            if total_previous >= total_salary and total_salary > 0:
                return JsonResponse({
                    'success': False,
                    'message': f'Salaire déjà payé intégralement pour {period.strftime("%m/%Y")}'
                })
            
            # Calculate remaining after this payment
            remaining = total_salary - total_previous - payment_amount
            
            # Validate payment doesn't exceed remaining
            if remaining < 0 and payment_type == 'avance':
                return JsonResponse({
                    'success': False,
                    'message': f'Le montant dépasse le salaire restant ({total_salary - total_previous} {salary_currency})'
                })
            
            # Get current exchange rate
            current_rate = TauxChange.objects.filter(is_active=True).first()
            taux = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
            
            # Create payment record
            payment_data = {
                'branche': request.user.branche,
                'caissier': request.user,
                'mois_paiement': period,
                'type_paiement': payment_type,
                'montant_total_salaire': total_salary,
                'montant_avances_precedentes': total_previous,
                'montant_paye': payment_amount,
                'montant_restant': max(remaining, Decimal('0')),
                'devise_paiement': currency,
                'taux_change': taux,
                'methode_paiement': payment_method,
                'notes': notes,
                'statut': 'paye',
                'date_paiement': timezone.now()
            }
            
            if employee_type == 'pompiste':
                payment_data['pompiste'] = employee
            else:
                payment_data['employe_user'] = employee
            
            paiement = PaiementSalaire.objects.create(**payment_data)
            
            # Create expense record
            categorie, created = CategorieDepense.objects.get_or_create(
                nom='Salaires',
                defaults={
                    'description': 'Paiements de salaires aux employés',
                    'created_by': request.user
                }
            )
            
            payment_type_text = 'Avance' if payment_type == 'avance' else 'Salaire'
            
            Depense.objects.create(
                branche=request.user.branche,
                categorie=categorie,
                description=f'{payment_type_text} {employee_name} - {period.strftime("%m/%Y")}',
                montant=payment_amount,
                devise=currency,
                methode_paiement=payment_method,
                beneficiaire=employee_name,
                created_by=request.user,
                statut='approuvee'
            )
            
            # Notify admins
            admins = User.objects.filter(role='admin', is_active=True)
            for admin in admins:
                Notification.objects.create(
                    destinataire=admin,
                    titre=f"Paiement de {payment_type_text.lower()} - {employee_name}",
                    message=f"{payment_type_text} payé: {amount} {currency} à {employee_name} pour {period.strftime('%m/%Y')} par {request.user.get_full_name()} ({request.user.branche.nom}). Restant: {remaining} {salary_currency}",
                    type_notification='salaire',
                    priorite='normale',
                    expediteur=request.user,
                    objet_id=paiement.id
                )
            
            return JsonResponse({
                'success': True,
                'message': f'{payment_type_text} payé à {employee_name} pour {period.strftime("%m/%Y")}',
                'payment': {
                    'id': paiement.id,
                    'employee': employee_name,
                    'amount': str(paiement.montant_paye),
                    'currency': paiement.devise_paiement,
                    'period': period.strftime('%m/%Y'),
                    'date': paiement.date_paiement.strftime('%d/%m/%Y %H:%M'),
                    'type': payment_type,
                    'remaining': str(remaining)
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            import traceback
            print(f"Error paying salary: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors du paiement: {str(e)}'
            })


class SalaryHistoryAPIView(CaissierRequiredMixin, View):
    """
    Returns payment history for an employee
    """
    
    def get(self, request):
        employee_id = request.GET.get('employee_id')
        employee_type = request.GET.get('employee_type')
        
        if not employee_id or not employee_type:
            return JsonResponse({
                'success': False,
                'message': 'Paramètres manquants'
            })
        
        # Get payments
        if employee_type == 'pompiste':
            payments = PaiementSalaire.objects.filter(
                pompiste_id=employee_id,
                branche=request.user.branche,
                statut='paye'
            ).select_related('caissier').order_by('-date_paiement')
        else:
            payments = PaiementSalaire.objects.filter(
                employe_user_id=employee_id,
                branche=request.user.branche,
                statut='paye'
            ).select_related('caissier').order_by('-date_paiement')
        
        payments_data = []
        for payment in payments:
            payment_type_display = 'Salaire Complet' if payment.type_paiement == 'salaire_complet' else 'Avance'
            
            payments_data.append({
                'id': payment.id,
                'period': payment.mois_paiement.strftime('%B %Y'),
                'date': payment.date_paiement.strftime('%d/%m/%Y %H:%M'),
                'amount': str(payment.montant_paye),
                'currency': payment.devise_paiement,
                'payment_method': payment.get_methode_paiement_display(),
                'payment_type': payment_type_display,
                'total_salary': str(payment.montant_total_salaire) if payment.montant_total_salaire else '-',
                'previous_advances': str(payment.montant_avances_precedentes),
                'remaining': str(payment.montant_restant) if payment.montant_restant else '0',
                'caissier': payment.caissier.get_full_name() if payment.caissier else 'N/A',
                'notes': payment.notes or ''
            })
        
        return JsonResponse({'payments': payments_data})


class ExportSalariesExcelView(CaissierRequiredMixin, View):
    """
    Export salary payments to Excel
    """
    
    def get(self, request):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment, PatternFill
            from django.http import HttpResponse
            
            branche = request.user.branche
            month_str = request.GET.get('month', '')
            
            # Parse month
            if month_str:
                try:
                    year, month = map(int, month_str.split('-'))
                    filter_month = date(year, month, 1)
                except:
                    filter_month = date.today().replace(day=1)
            else:
                filter_month = date.today().replace(day=1)
            
            # Get payments
            payments = PaiementSalaire.objects.filter(
                branche=branche,
                mois_paiement=filter_month,
                statut='paye'
            ).select_related('pompiste', 'employe_user', 'caissier').order_by('-date_paiement')
            
            # Create workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Paiements Salaires"
            
            # Header style
            header_fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            # Headers
            headers = ['Date', 'Employé', 'Type', 'Période', 'Type Paiement', 'Montant', 'Devise', 'Méthode', 'Caissier', 'Notes']
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center')
            
            # Data rows
            for row_idx, payment in enumerate(payments, 2):
                employee_name = payment.get_employee_name()
                employee_type = 'Pompiste' if payment.pompiste else 'Utilisateur'
                payment_type = 'Salaire Complet' if payment.type_paiement == 'salaire_complet' else 'Avance'
                
                ws.cell(row=row_idx, column=1, value=payment.date_paiement.strftime('%d/%m/%Y %H:%M'))
                ws.cell(row=row_idx, column=2, value=employee_name)
                ws.cell(row=row_idx, column=3, value=employee_type)
                ws.cell(row=row_idx, column=4, value=payment.mois_paiement.strftime('%m/%Y'))
                ws.cell(row=row_idx, column=5, value=payment_type)
                ws.cell(row=row_idx, column=6, value=float(payment.montant_paye))
                ws.cell(row=row_idx, column=7, value=payment.devise_paiement)
                ws.cell(row=row_idx, column=8, value=payment.get_methode_paiement_display())
                ws.cell(row=row_idx, column=9, value=payment.caissier.get_full_name() if payment.caissier else 'N/A')
                ws.cell(row=row_idx, column=10, value=payment.notes or '')
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Create response
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename=salaires_{branche.code}_{filter_month.strftime("%Y%m")}.xlsx'
            wb.save(response)
            return response
            
        except Exception as e:
            import traceback
            print(f"Error exporting to Excel: {traceback.format_exc()}")
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
        

class AbonnesPageView(CaissierRequiredMixin, CaissierContextMixin, TemplateView):
    """
    Abonnés (Subscribers with Debt) page template view for Caissier
    Shows only subscribers who have consumed in this branch and have debt
    """
    template_name = 'caissier/abonnes.html'


class AbonnesListAPIView(CaissierRequiredMixin, View):
    """
    Returns list of subscribers with debt who have consumed in this branch
    """
    
    def get(self, request):
        branche = request.user.branche
        
        # Get filter parameters
        search = request.GET.get('search', '')
        type_filter = request.GET.get('type', 'all')
        status_filter = request.GET.get('status', 'all')
        
        # Get all active subscribers
        abonnes = Abonne.objects.filter(is_active=True)
        
        # Apply search filter
        if search:
            abonnes = abonnes.filter(
                Q(nom_entreprise__icontains=search) |
                Q(code_client__icontains=search) |
                Q(contact_nom__icontains=search) |
                Q(contact_telephone__icontains=search)
            )
        
        # Apply type filter
        if type_filter != 'all':
            abonnes = abonnes.filter(type_abonnement=type_filter)
        
        abonnes_data = []
        for abonne in abonnes:
            # Check if abonné has consumed in this branch
            has_consumed_here = ConsommationAbonne.objects.filter(
                abonne=abonne,
                branche=branche
            ).exists()
            
            # Only show subscribers who have consumed in this branch
            if not has_consumed_here:
                continue
            
            # Calculate debt
            debt_usd = abs(float(abonne.solde_usd)) if abonne.solde_usd < 0 else 0
            debt_fc = abs(float(abonne.solde_fc)) if abonne.solde_fc < 0 else 0
            has_debt = debt_usd > 0 or debt_fc > 0
            
            # Apply status filter
            if status_filter == 'debt' and not has_debt:
                continue
            if status_filter == 'no_debt' and has_debt:
                continue
            
            # Get consumption statistics for this branch
            consumptions = ConsommationAbonne.objects.filter(
                abonne=abonne,
                branche=branche
            )
            
            total_consumed_usd = consumptions.filter(
                devise='USD'
            ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
            
            total_consumed_fc = consumptions.filter(
                devise='FC'
            ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
            
            # Get last consumption
            last_consumption = consumptions.order_by('-created_at').first()
            
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
                'debt_usd': debt_usd,
                'debt_fc': debt_fc,
                'has_debt': has_debt,
                'limite_credit': str(abonne.limite_credit),
                'total_consumed_usd': str(total_consumed_usd),
                'total_consumed_fc': str(total_consumed_fc),
                'last_consumption': last_consumption.created_at.strftime('%d/%m/%Y') if last_consumption else None,
                'consumption_count': consumptions.count()
            })
        
        # Calculate statistics
        total_abonnes = len(abonnes_data)
        with_debt = sum(1 for a in abonnes_data if a['has_debt'])
        without_debt = total_abonnes - with_debt
        
        total_debt_usd = sum(a['debt_usd'] for a in abonnes_data)
        total_debt_fc = sum(a['debt_fc'] for a in abonnes_data)
        
        statistics = {
            'total': total_abonnes,
            'with_debt': with_debt,
            'without_debt': without_debt,
            'total_debt_usd': total_debt_usd,
            'total_debt_fc': total_debt_fc
        }
        
        return JsonResponse({
            'abonnes': abonnes_data,
            'statistics': statistics,
            'branch_info': {
                'nom': branche.nom,
                'code': branche.code
            }
        })


class RegisterPaymentView(CaissierRequiredMixin, View):
    """
    Register a payment from a subscriber
    """
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['abonne_id', 'montant', 'devise', 'methode_paiement']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Get abonné
            try:
                abonne = Abonne.objects.get(id=data['abonne_id'], is_active=True)
            except Abonne.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Abonné introuvable'
                })
            
            # Validate amount
            try:
                montant = Decimal(str(data['montant']))
                if montant <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le montant doit être supérieur à 0'
                    })
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Montant invalide'
                })
            
            # Validate currency
            if data['devise'] not in ['USD', 'FC']:
                return JsonResponse({
                    'success': False,
                    'message': 'Devise invalide'
                })
            
            # Validate payment method
            if data['methode_paiement'] not in ['cash', 'mobile_money', 'bank_transfer']:
                return JsonResponse({
                    'success': False,
                    'message': 'Méthode de paiement invalide'
                })
            
            # Get current exchange rate
            current_rate = TauxChange.objects.filter(is_active=True).first()
            taux = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
            
            # Update subscriber balance (payment increases balance, reduces debt)
            if data['devise'] == 'USD':
                old_balance = abonne.solde_usd
                abonne.solde_usd += montant
                new_balance = abonne.solde_usd
            else:  # FC
                old_balance = abonne.solde_fc
                abonne.solde_fc += montant
                new_balance = abonne.solde_fc
            
            abonne.save()
            
            # Create payment record in ConsommationAbonne (with negative amount for payment)
            ConsommationAbonne.objects.create(
                abonne=abonne,
                branche=request.user.branche,
                vente=None,  # No associated sale
                quantite=Decimal('0'),  # No fuel quantity
                type_carburant=None,
                montant=-montant,  # Negative for payment (increases balance)
                devise=data['devise'],
                taux_change=taux,
                notes=data.get('notes', f'Paiement reçu par {request.user.get_full_name()}')
            )
            
            # Create expense record (payment received is income, not expense)
            # We track it as negative expense (income)
            categorie, created = CategorieDepense.objects.get_or_create(
                nom='Paiements Abonnés',
                defaults={
                    'description': 'Paiements reçus des abonnés',
                    'created_by': request.user
                }
            )
            
            Depense.objects.create(
                branche=request.user.branche,
                categorie=categorie,
                description=f'Paiement de {abonne.nom_entreprise} ({abonne.code_client})',
                montant=-montant,  # Negative = income
                devise=data['devise'],
                methode_paiement=data['methode_paiement'],
                beneficiaire=abonne.nom_entreprise,
                created_by=request.user,
                notes=data.get('notes', ''),
                statut='approuvee'
            )
            
            # Notify admins
            admins = User.objects.filter(role='admin', is_active=True)
            for admin in admins:
                Notification.objects.create(
                    destinataire=admin,
                    titre=f"Paiement abonné - {abonne.nom_entreprise}",
                    message=f"Paiement reçu: {montant} {data['devise']} de {abonne.nom_entreprise} ({abonne.code_client}) par {request.user.get_full_name()} ({request.user.branche.nom}). Ancien solde: {old_balance}, Nouveau solde: {new_balance}",
                    type_notification='paiement',
                    priorite='normale',
                    expediteur=request.user
                )
            
            return JsonResponse({
                'success': True,
                'message': f'Paiement de {montant} {data["devise"]} enregistré avec succès',
                'payment': {
                    'abonne': abonne.nom_entreprise,
                    'montant': str(montant),
                    'devise': data['devise'],
                    'old_balance': str(old_balance),
                    'new_balance': str(new_balance),
                    'date': timezone.now().strftime('%d/%m/%Y %H:%M')
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            import traceback
            print(f"Error registering payment: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'enregistrement: {str(e)}'
            })


class PaymentHistoryAPIView(CaissierRequiredMixin, View):
    """
    Returns payment history for a subscriber in this branch
    """
    
    def get(self, request):
        abonne_id = request.GET.get('abonne_id')
        
        if not abonne_id:
            return JsonResponse({
                'success': False,
                'message': 'ID abonné manquant'
            })
        
        try:
            abonne = Abonne.objects.get(id=abonne_id, is_active=True)
        except Abonne.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Abonné introuvable'
            })
        
        # Get all consumption records for this subscriber in this branch
        # Payments have negative montant
        consumptions = ConsommationAbonne.objects.filter(
            abonne=abonne,
            branche=request.user.branche
        ).order_by('-created_at')
        
        history_data = []
        for consumption in consumptions:
            is_payment = consumption.montant < 0
            
            history_data.append({
                'id': consumption.id,
                'type': 'paiement' if is_payment else 'consommation',
                'date': consumption.created_at.strftime('%d/%m/%Y %H:%M'),
                'montant': str(abs(consumption.montant)),
                'devise': consumption.devise,
                'description': consumption.notes or ('Paiement reçu' if is_payment else 'Consommation carburant'),
                'quantite': str(consumption.quantite) if consumption.quantite else '0',
                'type_carburant': consumption.type_carburant.nom if consumption.type_carburant else None
            })
        
        # Calculate totals
        payments_usd = consumptions.filter(
            montant__lt=0,
            devise='USD'
        ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        
        payments_fc = consumptions.filter(
            montant__lt=0,
            devise='FC'
        ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        
        consumptions_usd = consumptions.filter(
            montant__gt=0,
            devise='USD'
        ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        
        consumptions_fc = consumptions.filter(
            montant__gt=0,
            devise='FC'
        ).aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
        
        return JsonResponse({
            'history': history_data,
            'summary': {
                'total_payments_usd': str(abs(payments_usd)),
                'total_payments_fc': str(abs(payments_fc)),
                'total_consumptions_usd': str(consumptions_usd),
                'total_consumptions_fc': str(consumptions_fc),
                'current_balance_usd': str(abonne.solde_usd),
                'current_balance_fc': str(abonne.solde_fc)
            },
            'abonne': {
                'id': abonne.id,
                'nom_entreprise': abonne.nom_entreprise,
                'code_client': abonne.code_client,
                'type_abonnement': abonne.get_type_abonnement_display()
            }
        })


class ExportAbonnesExcelView(CaissierRequiredMixin, View):
    """
    Export subscribers list to Excel
    """
    
    def get(self, request):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment, PatternFill
            from django.http import HttpResponse
            
            branche = request.user.branche
            
            # Get subscribers who have consumed in this branch
            abonnes = Abonne.objects.filter(is_active=True)
            
            # Filter to only those who consumed here
            abonnes_data = []
            for abonne in abonnes:
                has_consumed = ConsommationAbonne.objects.filter(
                    abonne=abonne,
                    branche=branche
                ).exists()
                
                if has_consumed:
                    abonnes_data.append(abonne)
            
            # Create workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Abonnés"
            
            # Header style
            header_fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            # Headers
            headers = ['Code Client', 'Entreprise', 'Type', 'Contact', 'Téléphone', 
                      'Solde USD', 'Solde FC', 'Dette USD', 'Dette FC', 'Total Consommé']
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center')
            
            # Data rows
            for row_idx, abonne in enumerate(abonnes_data, 2):
                debt_usd = abs(float(abonne.solde_usd)) if abonne.solde_usd < 0 else 0
                debt_fc = abs(float(abonne.solde_fc)) if abonne.solde_fc < 0 else 0
                
                # Calculate total consumed in this branch
                consumptions = ConsommationAbonne.objects.filter(
                    abonne=abonne,
                    branche=branche,
                    montant__gt=0  # Only consumptions, not payments
                )
                total_usd = consumptions.filter(devise='USD').aggregate(
                    Sum('montant'))['montant__sum'] or 0
                total_fc = consumptions.filter(devise='FC').aggregate(
                    Sum('montant'))['montant__sum'] or 0
                
                ws.cell(row=row_idx, column=1, value=abonne.code_client)
                ws.cell(row=row_idx, column=2, value=abonne.nom_entreprise)
                ws.cell(row=row_idx, column=3, value=abonne.get_type_abonnement_display())
                ws.cell(row=row_idx, column=4, value=abonne.contact_nom or '')
                ws.cell(row=row_idx, column=5, value=abonne.contact_telephone or '')
                ws.cell(row=row_idx, column=6, value=float(abonne.solde_usd))
                ws.cell(row=row_idx, column=7, value=float(abonne.solde_fc))
                ws.cell(row=row_idx, column=8, value=debt_usd)
                ws.cell(row=row_idx, column=9, value=debt_fc)
                ws.cell(row=row_idx, column=10, value=f"${float(total_usd):.2f} / {float(total_fc):.0f} FC")
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Create response
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename=abonnes_{branche.code}_{timezone.now().strftime("%Y%m%d")}.xlsx'
            wb.save(response)
            return response
            
        except Exception as e:
            import traceback
            print(f"Error exporting to Excel: {traceback.format_exc()}")
            return JsonResponse({'success': False, 'message': str(e)}, status=500)