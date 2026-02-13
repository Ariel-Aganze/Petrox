import os
import re
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
from decimal import Decimal, InvalidOperation
import json
import csv
import io

# PDF Generation imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from apps.core.models import (
    LivraisonCarburant, PaiementPartenaire, Partenaire, User, Branche, TauxChange, TypeCarburant, CategorieDepense,
    Vente, Depense, Stock, Pompiste, Abonne, ConsommationAbonne,
    Document, DocumentCategory, Notification, Livraison, MoyenPaiement,
    PaiementSalaire
)

from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Count, Q, Value, DecimalField, F
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from decimal import Decimal
import json
import random
import string

from apps.core.models import User, Pompiste, Branche
from django.core.files.storage import default_storage
from django.http import HttpResponse, Http404
from apps.core.models import Document, DocumentCategory

import io
from datetime import timedelta
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from django.db.models import Case, When, DecimalField

from apps.core.models import PaiementSalaire, Pompiste
from datetime import datetime
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from django.db.models.functions import TruncDate
from django.db import transaction



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

class CreateBranchView(AdminRequiredMixin, View):
    """Create a new branch"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Required fields
            required_fields = ['nom', 'code', 'adresse', 'ville', 'province']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Check if code already exists
            if Branche.objects.filter(code=data['code']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce code de branche existe déjà'
                }, status=400)
            
            # Create branch
            branch_data = {
                'nom': data['nom'],
                'code': data['code'].upper(),
                'adresse': data['adresse'],
                'ville': data['ville'],
                'province': data['province'],
                'is_active': True
            }
            
            # Optional responsable
            if data.get('responsable_id'):
                try:
                    responsable = User.objects.get(
                        id=data['responsable_id'],
                        role='manager',
                        is_active=True
                    )
                    branch_data['responsable'] = responsable
                except User.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Responsable invalide'
                    }, status=400)
            
            # Optional date
            if data.get('date_mise_en_service'):
                branch_data['date_mise_en_service'] = data['date_mise_en_service']
            
            # Create the branch
            branch = Branche.objects.create(**branch_data)
            
            # If responsable assigned, update their branch
            if branch.responsable:
                branch.responsable.branche = branch
                branch.responsable.save()
            
            # Initialize stock for all fuel types
            fuel_types = TypeCarburant.objects.filter(is_active=True)
            for fuel_type in fuel_types:
                Stock.objects.create(
                    branche=branch,
                    type_carburant=fuel_type,
                    quantite_actuelle=Decimal('0.00'),
                    seuil_alerte=Decimal('1000.00'),  # Default threshold
                    prix_achat=Decimal('0.00')
                )
            
            return JsonResponse({
                'success': True,
                'message': 'Branche créée avec succès',
                'branch': {
                    'id': branch.id,
                    'nom': branch.nom,
                    'code': branch.code
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
                'message': f'Erreur: {str(e)}'
            }, status=500)
        
class BranchDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about a branch"""
    
    def get(self, request, branch_id):
        try:
            branch = get_object_or_404(Branche, id=branch_id)
            
            return JsonResponse({
                'success': True,
                'branch': {
                    'id': branch.id,
                    'nom': branch.nom,
                    'code': branch.code,
                    'adresse': branch.adresse,
                    'ville': branch.ville,
                    'province': branch.province,
                    'responsable_id': branch.responsable.id if branch.responsable else None,
                    'responsable_nom': branch.responsable.get_full_name() if branch.responsable else None,
                    'date_mise_en_service': branch.date_mise_en_service.strftime('%Y-%m-%d') if hasattr(branch, 'date_mise_en_service') and branch.date_mise_en_service else None,
                    'is_active': branch.is_active,
                    'created_at': branch.created_at.strftime('%Y-%m-%d %H:%M'),
                    'pompistes_count': branch.pompiste_set.filter(is_active=True).count(),
                    'users_count': User.objects.filter(branche=branch, is_active=True).count()
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateBranchView(AdminRequiredMixin, View):
    """Update an existing branch"""
    
    def put(self, request, branch_id):
        try:
            data = json.loads(request.body)
            branch = get_object_or_404(Branche, id=branch_id)
            
            # Check code uniqueness if changed
            if data.get('code') and data['code'] != branch.code:
                if Branche.objects.filter(code=data['code']).exclude(id=branch_id).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Ce code de branche existe déjà'
                    }, status=400)
                branch.code = data['code'].upper()
            
            # Update fields
            if data.get('nom'):
                branch.nom = data['nom']
            if data.get('adresse'):
                branch.adresse = data['adresse']
            if data.get('ville'):
                branch.ville = data['ville']
            if data.get('province'):
                branch.province = data['province']
            
            # Update responsable
            if 'responsable_id' in data:
                if data['responsable_id']:
                    try:
                        # Remove branch from old responsable
                        if branch.responsable:
                            branch.responsable.branche = None
                            branch.responsable.save()
                        
                        # Assign new responsable
                        responsable = User.objects.get(
                            id=data['responsable_id'],
                            role='manager',
                            is_active=True
                        )
                        branch.responsable = responsable
                        responsable.branche = branch
                        responsable.save()
                    except User.DoesNotExist:
                        return JsonResponse({
                            'success': False,
                            'message': 'Responsable invalide'
                        }, status=400)
                else:
                    # Remove responsable
                    if branch.responsable:
                        branch.responsable.branche = None
                        branch.responsable.save()
                    branch.responsable = None
            
            # Update date if provided
            if data.get('date_mise_en_service'):
                branch.date_mise_en_service = data['date_mise_en_service']
            
            branch.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Branche modifiée avec succès'
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


class ToggleBranchActiveView(AdminRequiredMixin, View):
    """Toggle branch active status"""
    
    def patch(self, request, branch_id):
        try:
            branch = get_object_or_404(Branche, id=branch_id)
            
            # Toggle active status
            branch.is_active = not branch.is_active
            branch.save()
            
            status = 'activée' if branch.is_active else 'désactivée'
            
            return JsonResponse({
                'success': True,
                'message': f'Branche {status} avec succès',
                'is_active': branch.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class DeleteBranchView(AdminRequiredMixin, View):
    """Delete a branch (soft delete by deactivating)"""
    
    def delete(self, request, branch_id):
        try:
            branch = get_object_or_404(Branche, id=branch_id)
            
            # Check if branch has data
            has_sales = Vente.objects.filter(branche=branch).exists()
            has_expenses = Depense.objects.filter(branche=branch).exists()
            has_stock = Stock.objects.filter(branche=branch, quantite_actuelle__gt=0).exists()
            
            if has_sales or has_expenses or has_stock:
                # Soft delete - just deactivate
                branch.is_active = False
                branch.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Branche désactivée (données existantes préservées)'
                })
            else:
                # Hard delete if no data
                branch.delete()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Branche supprimée définitivement'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class BranchStatsView(AdminRequiredMixin, View):
    """Get comprehensive statistics for a branch"""
    
    def get(self, request, branch_id):
        try:
            branch = get_object_or_404(Branche, id=branch_id)
            
            # Date ranges
            today = timezone.now().date()
            month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            year_start = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Sales statistics
            sales_today = Vente.objects.filter(
                branche=branch,
                created_at__date=today,
                statut='validee'
            )
            sales_month = Vente.objects.filter(
                branche=branch,
                created_at__gte=month_start,
                statut='validee'
            )
            sales_year = Vente.objects.filter(
                branche=branch,
                created_at__gte=year_start,
                statut='validee'
            )
            
            # Expense statistics
            expenses_month = Depense.objects.filter(
                branche=branch,
                created_at__gte=month_start,
                statut='approuvee'
            )
            
            # Stock information
            stocks = Stock.objects.filter(branche=branch).select_related('type_carburant')
            total_stock = stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0
            stock_alerts = stocks.filter(quantite_actuelle__lte=F('seuil_alerte')).count()
            
            # Employee counts
            pompistes_count = Pompiste.objects.filter(branche=branch, is_active=True).count()
            users_count = User.objects.filter(branche=branch, is_active=True).count()
            
            # Missing amounts
            manquants = Vente.objects.filter(
                branche=branch,
                statut='manquant',
                created_at__gte=month_start
            )
            
            return JsonResponse({
                'success': True,
                'stats': {
                    'sales': {
                        'today_usd': float(sales_today.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0),
                        'today_fc': float(sales_today.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0),
                        'today_count': sales_today.count(),
                        'month_usd': float(sales_month.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0),
                        'month_fc': float(sales_month.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0),
                        'month_count': sales_month.count(),
                        'year_usd': float(sales_year.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0),
                        'year_fc': float(sales_year.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0),
                        'year_count': sales_year.count(),
                    },
                    'expenses': {
                        'month_usd': float(expenses_month.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0),
                        'month_fc': float(expenses_month.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0),
                        'month_count': expenses_month.count(),
                    },
                    'stock': {
                        'total': float(total_stock),
                        'alerts_count': stock_alerts,
                        'types_count': stocks.count()
                    },
                    'employees': {
                        'pompistes': pompistes_count,
                        'users': users_count,
                        'total': pompistes_count + users_count
                    },
                    'manquants': {
                        'count': manquants.count(),
                        'total_usd': float(manquants.aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or 0),
                        'total_fc': float(manquants.aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or 0)
                    }
                },
                'branch': {
                    'id': branch.id,
                    'nom': branch.nom,
                    'code': branch.code,
                    'is_active': branch.is_active
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

# ============================================
# NEW VIEW 1: Branch History (Modification History)
# ============================================

class BranchHistoryView(AdminRequiredMixin, View):
    """
    Get modification history for a branch
    Shows all changes made to the branch with user and timestamp
    """
    
    def get(self, request, branch_id):
        try:
            branch = get_object_or_404(Branche, id=branch_id)
            
            # Get history from Django's LogEntry if available
            from django.contrib.admin.models import LogEntry, ADDITION, CHANGE, DELETION
            from django.contrib.contenttypes.models import ContentType
            
            content_type = ContentType.objects.get_for_model(Branche)
            
            logs = LogEntry.objects.filter(
                content_type=content_type,
                object_id=str(branch_id)
            ).select_related('user').order_by('-action_time')
            
            history = []
            for log in logs:
                action_map = {
                    ADDITION: 'created',
                    CHANGE: 'updated',
                    DELETION: 'deleted'
                }
                
                history.append({
                    'date': log.action_time.strftime('%d/%m/%Y %H:%M'),
                    'user': f"{log.user.prenom} {log.user.nom}" if hasattr(log.user, 'prenom') else log.user.username,
                    'action': action_map.get(log.action_flag, 'unknown'),
                    'details': log.change_message or 'Aucun détail disponible'
                })
            
            # If no Django logs, create basic history from branch data
            if not history:
                history = [
                    {
                        'date': branch.created_at.strftime('%d/%m/%Y %H:%M') if hasattr(branch, 'created_at') else timezone.now().strftime('%d/%m/%Y %H:%M'),
                        'user': f"{branch.created_by.prenom} {branch.created_by.nom}" if hasattr(branch, 'created_by') and branch.created_by else 'Système',
                        'action': 'created',
                        'details': f'Branche créée: {branch.nom}'
                    }
                ]
            
            return JsonResponse({
                'success': True,
                'history': history
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================
# NEW VIEW 2: Branch Performance Comparison
# ============================================

class BranchComparisonView(AdminRequiredMixin, View):
    """
    Compare performance metrics across all branches
    Returns data for comparison charts
    """
    
    def get(self, request):
        try:
            # Get date range (current month by default)
            today = timezone.now().date()
            start_date = today.replace(day=1)
            end_date = today
            
            branches = Branche.objects.filter(is_active=True)
            comparison_data = []
            
            for branch in branches:
                # Sales for this month
                sales = Vente.objects.filter(
                    branche=branch,
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date,
                    statut='validee'
                )
                total_sales_usd = sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or Decimal('0')
                
                # Expenses for this month
                expenses = Depense.objects.filter(
                    branche=branch,
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date,
                    statut='approuvee',
                    devise='USD'
                )
                total_expenses_usd = expenses.aggregate(Sum('montant'))['montant__sum'] or Decimal('0')
                
                # Profit
                profit = total_sales_usd - total_expenses_usd
                
                # Employee count
                pompistes_count = Pompiste.objects.filter(branche=branch, is_active=True).count()
                users_count = User.objects.filter(branche=branch, is_active=True).count()
                total_employees = pompistes_count + users_count
                
                comparison_data.append({
                    'id': branch.id,
                    'name': branch.nom,
                    'sales': float(total_sales_usd),
                    'expenses': float(total_expenses_usd),
                    'profit': float(profit),
                    'employees': total_employees
                })
            
            # Sort by sales (descending)
            comparison_data.sort(key=lambda x: x['sales'], reverse=True)
            
            return JsonResponse({
                'success': True,
                'branches': comparison_data,
                'period': {
                    'start': start_date.strftime('%d/%m/%Y'),
                    'end': end_date.strftime('%d/%m/%Y')
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ==================== USERS API FOR BRANCH ASSIGNMENT ====================

class UsersListAPIView(AdminRequiredMixin, View):
    """Get list of users with filters"""
    
    def get(self, request):
        try:
            # Get filter parameters
            role = request.GET.get('role', '')
            assigned = request.GET.get('assigned', '')  # 'true' or 'false'
            
            # Base queryset
            users = User.objects.filter(is_active=True)
            
            # Filter by role
            if role:
                users = users.filter(role=role)
            
            # Filter by assignment status
            if assigned == 'false':
                users = users.filter(branche__isnull=True)
            elif assigned == 'true':
                users = users.filter(branche__isnull=False)
            
            # Build response
            users_data = []
            for user in users:
                users_data.append({
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'prenom': user.prenom,
                    'nom': user.nom,
                    'role': user.role,
                    'branche_id': user.branche.id if user.branche else None,
                    'branche_nom': user.branche.nom if user.branche else None
                })
            
            return JsonResponse({
                'success': True,
                'users': users_data,
                'count': len(users_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
        

class BranchesListView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """List all branches with performance metrics"""
    template_name = 'admin/branches.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all branches with related data
        branches = Branche.objects.all().prefetch_related('pompiste_set', 'stock_set')
        
        # Calculate counts
        active_count = 0
        stock_alerts_count = 0
        
        # Add stock alert status to each branch and count
        for branch in branches:
            branch.has_stock_alert = branch.stock_set.filter(
                quantite_actuelle__lte=F('seuil_alerte')
            ).exists()
            
            if branch.is_active:
                active_count += 1
            
            if branch.has_stock_alert:
                stock_alerts_count += 1
        
        context['branches'] = branches
        context['active_branches_count'] = active_count
        context['stock_alerts_count'] = stock_alerts_count
        
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


class DepensesAnalyticsAPIView(AdminRequiredMixin, View):
    """Get analytics data for expenses"""
    
    def get(self, request):
        try:
            # Get filters
            period = request.GET.get('period', 'month')
            branche_id = request.GET.get('branche_id')
            
            # Base queryset
            depenses = Depense.objects.filter(statut='approuvee')
            
            # Apply branch filter
            if branche_id and branche_id != 'all':
                depenses = depenses.filter(branche_id=branche_id)
            
            # Apply period filter
            from datetime import datetime, timedelta
            today = timezone.now()
            
            if period == 'today':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                depenses = depenses.filter(created_at__gte=start_date)
            elif period == 'week':
                start_date = today - timedelta(days=7)
                depenses = depenses.filter(created_at__gte=start_date)
            elif period == 'month':
                start_date = today - timedelta(days=30)
                depenses = depenses.filter(created_at__gte=start_date)
            
            # === FIX 1: BY CATEGORY - Group properly by category ===
            # WRONG WAY (returns only one group):
            # by_category = depenses.aggregate(total=Sum('montant'))
            
            # CORRECT WAY (returns separate row for each category):
            from django.db.models import Sum, Count
            from django.db.models.functions import TruncDate
            
            by_category = list(depenses.values('categorie__nom').annotate(
                total=Sum(
                    Case(
                        When(devise='USD', then=F('montant')),
                        default=Value(0),
                        output_field=DecimalField()
                    )
                )
            ).order_by('-total'))
            
            # === FIX 2: CURRENCY DISTRIBUTION - Calculate both USD and FC ===
            # Calculate totals for EACH currency separately
            total_usd = float(depenses.filter(devise='USD').aggregate(
                total=Sum('montant')
            )['total'] or 0)
            
            total_fc = float(depenses.filter(devise='FC').aggregate(
                total=Sum('montant')
            )['total'] or 0)
            
            # Trend data (30 days)
            if period in ['month', 'all']:
                trend_days = 30
            elif period == 'week':
                trend_days = 7
            else:
                trend_days = 1
            
            trend_start = today - timedelta(days=trend_days)
            trend = list(depenses.filter(created_at__gte=trend_start)
                .annotate(date=TruncDate('created_at'))
                .values('date')
                .annotate(
                    total=Sum(
                        Case(
                            When(devise='USD', then=F('montant')),
                            default=Value(0),
                            output_field=DecimalField()
                        )
                    )
                )
                .order_by('date'))
            
            # By branch
            by_branch = list(depenses.values('branche__nom').annotate(
                total_usd=Sum(
                    Case(
                        When(devise='USD', then=F('montant')),
                        default=Value(0),
                        output_field=DecimalField()
                    )
                ),
                total_fc=Sum(
                    Case(
                        When(devise='FC', then=F('montant')),
                        default=Value(0),
                        output_field=DecimalField()
                    )
                )
            ).order_by('-total_usd'))
            
            # Convert Decimals to float for JSON
            for item in by_category:
                item['total'] = float(item['total'] or 0)
            
            for item in trend:
                item['total'] = float(item['total'] or 0)
                item['date'] = item['date'].strftime('%d/%m')
            
            for item in by_branch:
                item['total_usd'] = float(item['total_usd'] or 0)
                item['total_fc'] = float(item['total_fc'] or 0)
            
            return JsonResponse({
                'success': True,
                'by_category': by_category,  # NOW RETURNS MULTIPLE CATEGORIES
                'trend': trend,
                'by_branch': by_branch,
                'total_usd': total_usd,  # PROPERLY CALCULATED
                'total_fc': total_fc     # PROPERLY CALCULATED
            })
            
        except Exception as e:
            import traceback
            print(f"Error in DepensesAnalyticsAPIView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

class CategoriesListAPIView(AdminRequiredMixin, View):
    """Get all categories + pending requests"""
    
    def get(self, request):
        try:
            # Get APPROVED categories (is_active=True)
            categories = CategorieDepense.objects.filter(is_active=True).order_by('nom')
            
            categories_data = [{
                'id': cat.id,
                'nom': cat.nom,
                'description': cat.description if cat.description else ''
            } for cat in categories]
            
            # Get PENDING category requests (is_active=False)
            pending_categories = CategorieDepense.objects.filter(
                is_active=False
            ).select_related('created_by', 'created_by__branche').order_by('-created_at')
            
            pending_data = []
            for cat in pending_categories:
                # Parse the description to extract info
                description_lines = cat.description.split('\n') if cat.description else []
                requested_by = description_lines[0].replace('Demandée par: ', '') if len(description_lines) > 0 else 'Inconnu'
                justification = description_lines[1].replace('Justification: ', '') if len(description_lines) > 1 else ''
                
                pending_data.append({
                    'id': cat.id,
                    'nom': cat.nom,
                    'created_by': requested_by,
                    'justification': justification,
                    'created_at': cat.created_at.strftime('%d/%m/%Y %H:%M') if hasattr(cat, 'created_at') else 'N/A'
                })
            
            return JsonResponse({
                'success': True,
                'categories': categories_data,
                'pending_requests': pending_data
            })
            
        except Exception as e:
            import traceback
            print(f"Error in CategoriesListAPIView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e),
                'categories': [],
                'pending_requests': []
            }, status=500)
        
class PendingCategoriesCountAPIView(AdminRequiredMixin, View):
    """Get count of pending category requests for badge"""
    
    def get(self, request):
        try:
            # Count categories with is_active=False
            pending_count = CategorieDepense.objects.filter(is_active=False).count()
            
            return JsonResponse({
                'success': True,
                'pending_count': pending_count
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'pending_count': 0
            }, status=500)

class ApproveCategoryRequestView(AdminRequiredMixin, View):
    """Approve a pending category request"""
    
    def post(self, request, category_id):
        try:
            # Get the pending category (is_active=False)
            category = CategorieDepense.objects.filter(
                id=category_id, 
                is_active=False
            ).first()
            
            if not category:
                return JsonResponse({
                    'success': False,
                    'message': 'Demande de catégorie non trouvée ou déjà approuvée'
                }, status=404)
            
            # Check if an ACTIVE category with the same name already exists
            # This handles the case where admin manually created it while request was pending
            existing_active = CategorieDepense.objects.filter(
                nom__iexact=category.nom,
                is_active=True
            ).exclude(id=category_id).first()
            
            if existing_active:
                # If active version exists, delete this pending request
                category.delete()
                return JsonResponse({
                    'success': False,
                    'message': f'Une catégorie "{category.nom}" existe déjà (approuvée précédemment)'
                }, status=400)
            
            # Approve the category by setting is_active=True
            category.is_active = True
            category.save()
            
            # Notify the requester if they exist
            if hasattr(category, 'created_by') and category.created_by:
                try:
                    Notification.objects.create(
                        destinataire=category.created_by,
                        titre=f"Catégorie approuvée: {category.nom}",
                        message=f"Votre demande de création de la catégorie '{category.nom}' a été approuvée par {request.user.get_full_name()}.",
                        type_notification='reponse_demande',
                        priorite='normale',
                        expediteur=request.user
                    )
                except Exception as e:
                    print(f"Error creating notification: {e}")
            
            return JsonResponse({
                'success': True,
                'message': f'Catégorie "{category.nom}" approuvée avec succès',
                'category': {
                    'id': category.id,
                    'nom': category.nom
                }
            })
            
        except Exception as e:
            import traceback
            print(f"Error approving category: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'approbation: {str(e)}'
            }, status=500)


class RejectCategoryRequestView(AdminRequiredMixin, View):
    """Reject a pending category request"""
    
    def post(self, request, category_id):
        try:
            # Get the pending category (is_active=False)
            category = CategorieDepense.objects.filter(
                id=category_id,
                is_active=False
            ).first()
            
            if not category:
                return JsonResponse({
                    'success': False,
                    'message': 'Demande de catégorie non trouvée ou déjà traitée'
                }, status=404)
            
            category_name = category.nom
            requester = category.created_by if hasattr(category, 'created_by') else None
            
            # Notify the requester before deletion
            if requester:
                try:
                    Notification.objects.create(
                        destinataire=requester,
                        titre=f"Catégorie rejetée: {category_name}",
                        message=f"Votre demande de création de la catégorie '{category_name}' a été rejetée par {request.user.get_full_name()}.",
                        type_notification='reponse_demande',
                        priorite='normale',
                        expediteur=request.user
                    )
                except Exception as e:
                    print(f"Error creating notification: {e}")
            
            # Delete the rejected category
            category.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Demande "{category_name}" rejetée avec succès'
            })
            
        except Exception as e:
            import traceback
            print(f"Error rejecting category: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors du rejet: {str(e)}'
            }, status=500)




class CategoryCreateAPIView(AdminRequiredMixin, View):
    """Create new category directly by admin"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            nom = data.get('nom', '').strip()
            
            if not nom:
                return JsonResponse({
                    'success': False,
                    'message': 'Nom de catégorie requis'
                }, status=400)
            
            # Check if category already exists (active or pending)
            if CategorieDepense.objects.filter(nom__iexact=nom).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Cette catégorie existe déjà'
                }, status=400)
            
            # Create category as active (admin creates directly approved)
            category = CategorieDepense.objects.create(
                nom=nom,
                description=data.get('description', ''),
                is_active=True,
                created_by=request.user
            )
            
            return JsonResponse({
                'success': True,
                'category': {
                    'id': category.id,
                    'nom': category.nom
                }
            })
            
        except Exception as e:
            import traceback
            print(f"Error creating category: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
        

class CategoryUpdateAPIView(AdminRequiredMixin, View):
    """Update category name"""
    
    def put(self, request, category_id):
        try:
            # Only update ACTIVE categories
            category = get_object_or_404(CategorieDepense, id=category_id, is_active=True)
            data = json.loads(request.body)
            
            nom = data.get('nom', '').strip()
            if not nom:
                return JsonResponse({
                    'success': False,
                    'message': 'Nom de catégorie requis'
                }, status=400)
            
            # Check if name already exists (excluding current category)
            if CategorieDepense.objects.filter(nom__iexact=nom).exclude(id=category_id).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce nom de catégorie existe déjà'
                }, status=400)
            
            category.nom = nom
            if 'description' in data:
                category.description = data['description']
            category.save()
            
            return JsonResponse({
                'success': True,
                'category': {
                    'id': category.id,
                    'nom': category.nom
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class CategoryDeleteAPIView(AdminRequiredMixin, View):
    """Delete category if not in use"""
    
    def delete(self, request, category_id):
        try:
            category = get_object_or_404(CategorieDepense, id=category_id, is_active=True)
            
            # Check if category has any expenses
            expense_count = Depense.objects.filter(categorie=category).count()
            
            if expense_count > 0:
                return JsonResponse({
                    'success': False,
                    'message': f'Impossible de supprimer. Cette catégorie a {expense_count} dépense(s) associée(s).'
                }, status=400)
            
            category_name = category.nom
            category.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Catégorie "{category_name}" supprimée'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    


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
    """
    Admin Dashboard Stats API
    Returns all data needed for the dashboard in one call
    """
    
    def get(self, request):
        try:
            # Get parameters
            branche_id = request.GET.get('branche_id', 'all')
            period = request.GET.get('period', 'month')
            devise = request.GET.get('devise', 'USD')
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            
            # Calculate date range
            if period == 'custom' and start_date and end_date:
                start = timezone.make_aware(datetime.strptime(start_date, '%Y-%m-%d'))
                end = timezone.make_aware(datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
            else:
                start, end = self.get_period_range(period)
            
            # Get previous period for trend calculation
            period_length = (end - start).days
            prev_start = start - timedelta(days=period_length)
            prev_end = start
            
            # Base querysets
            sales_qs = Vente.objects.filter(
                created_at__gte=start,
                created_at__lte=end,
                statut='validee'
            )
            
            expenses_qs = Depense.objects.filter(
                created_at__gte=start,
                created_at__lte=end,
                statut='approuvee'
            )
            
            # Apply branch filter
            if branche_id != 'all':
                sales_qs = sales_qs.filter(branche_id=branche_id)
                expenses_qs = expenses_qs.filter(branche_id=branche_id)
            
            # Calculate KPIs
            if devise == 'USD':
                total_sales = float(sales_qs.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0)
                total_expenses = float(expenses_qs.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0)
                
                # Previous period for trends
                prev_sales = float(Vente.objects.filter(
                    created_at__gte=prev_start,
                    created_at__lt=prev_end,
                    statut='validee'
                ).aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0)
                
                prev_expenses = float(Depense.objects.filter(
                    created_at__gte=prev_start,
                    created_at__lt=prev_end,
                    statut='approuvee',
                    devise='USD'
                ).aggregate(Sum('montant'))['montant__sum'] or 0)
            else:  # FC
                total_sales = float(sales_qs.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0)
                total_expenses = float(expenses_qs.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0)
                
                prev_sales = float(Vente.objects.filter(
                    created_at__gte=prev_start,
                    created_at__lt=prev_end,
                    statut='validee'
                ).aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0)
                
                prev_expenses = float(Depense.objects.filter(
                    created_at__gte=prev_start,
                    created_at__lt=prev_end,
                    statut='approuvee',
                    devise='FC'
                ).aggregate(Sum('montant'))['montant__sum'] or 0)
            
            # Calculate trends
            sales_trend = ((total_sales - prev_sales) / prev_sales * 100) if prev_sales > 0 else 0
            expenses_trend = ((total_expenses - prev_expenses) / prev_expenses * 100) if prev_expenses > 0 else 0
            
            # Get chart data
            chart_data = self.get_chart_data(sales_qs, expenses_qs, period, devise, start, end)
            
            # Get sales by fuel
            sales_by_fuel = self.get_sales_by_fuel(sales_qs, devise)
            
            # Get forex impact
            forex_impact = self.get_forex_impact(sales_qs, devise)
            
            # Get recent transactions (LIMIT TO 5)
            recent_transactions = self.get_recent_transactions(branche_id, devise, start, end)[:5]
            
            # Get stock alerts
            stock_alerts = self.get_stock_alerts(branche_id)
            
            return JsonResponse({
                'success': True,
                'total_sales': total_sales,
                'total_expenses': total_expenses,
                'sales_trend': round(sales_trend, 1),
                'expenses_trend': round(expenses_trend, 1),
                'chart_data': chart_data,
                'sales_by_fuel': sales_by_fuel,
                'forex_impact': forex_impact,
                'recent_transactions': recent_transactions,
                'stock_alerts': stock_alerts
            })
            
        except Exception as e:
            import traceback
            print(f"Dashboard API Error: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    
    def get_period_range(self, period):
        """Calculate start and end dates for period"""
        now = timezone.now()
        
        if period == 'day':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif period == 'week':
            start = now - timedelta(days=7)
            end = now
        elif period == 'month':
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
        
        return start, end
    
    def get_chart_data(self, sales_qs, expenses_qs, period, devise, start, end):
        """Generate chart data based on period"""
        labels = []
        sales_data = []
        expenses_data = []
        
        if period == 'day':
            # Hourly data for today
            for hour in range(24):
                hour_start = start.replace(hour=hour, minute=0, second=0)
                hour_end = start.replace(hour=hour, minute=59, second=59)
                
                labels.append(f"{hour:02d}h")
                
                if devise == 'USD':
                    sales_sum = sales_qs.filter(
                        created_at__gte=hour_start,
                        created_at__lte=hour_end
                    ).aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
                    
                    expenses_sum = expenses_qs.filter(
                        created_at__gte=hour_start,
                        created_at__lte=hour_end,
                        devise='USD'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                else:
                    sales_sum = sales_qs.filter(
                        created_at__gte=hour_start,
                        created_at__lte=hour_end
                    ).aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
                    
                    expenses_sum = expenses_qs.filter(
                        created_at__gte=hour_start,
                        created_at__lte=hour_end,
                        devise='FC'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                
                sales_data.append(float(sales_sum))
                expenses_data.append(float(expenses_sum))
        
        elif period == 'week':
            # Daily data for last 7 days
            for i in range(7):
                day = start + timedelta(days=i)
                day_start = day.replace(hour=0, minute=0, second=0)
                day_end = day.replace(hour=23, minute=59, second=59)
                
                labels.append(day.strftime('%d/%m'))
                
                if devise == 'USD':
                    sales_sum = sales_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end
                    ).aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
                    
                    expenses_sum = expenses_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end,
                        devise='USD'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                else:
                    sales_sum = sales_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end
                    ).aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
                    
                    expenses_sum = expenses_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end,
                        devise='FC'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                
                sales_data.append(float(sales_sum))
                expenses_data.append(float(expenses_sum))
        
        else:  # month or custom
            # Group by day
            days_count = (end - start).days + 1
            
            for i in range(min(days_count, 30)):  # Limit to 30 days for performance
                day = start + timedelta(days=i)
                day_start = day.replace(hour=0, minute=0, second=0)
                day_end = day.replace(hour=23, minute=59, second=59)
                
                labels.append(day.strftime('%d/%m'))
                
                if devise == 'USD':
                    sales_sum = sales_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end
                    ).aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
                    
                    expenses_sum = expenses_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end,
                        devise='USD'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                else:
                    sales_sum = sales_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end
                    ).aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
                    
                    expenses_sum = expenses_qs.filter(
                        created_at__gte=day_start,
                        created_at__lte=day_end,
                        devise='FC'
                    ).aggregate(Sum('montant'))['montant__sum'] or 0
                
                sales_data.append(float(sales_sum))
                expenses_data.append(float(expenses_sum))
        
        return {
            'labels': labels,
            'sales': sales_data,
            'expenses': expenses_data
        }
    
    def get_sales_by_fuel(self, sales_qs, devise):
        """Get sales breakdown by fuel type"""
        fuel_types = TypeCarburant.objects.filter(is_active=True)
        sales_by_fuel = []
        
        for fuel in fuel_types:
            fuel_sales = sales_qs.filter(type_carburant=fuel)
            
            quantity = float(fuel_sales.aggregate(Sum('quantite'))['quantite__sum'] or 0)
            
            if devise == 'USD':
                amount = float(fuel_sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0)
            else:
                amount = float(fuel_sales.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0)
            
            if quantity > 0:  # Only include fuels with sales
                sales_by_fuel.append({
                    'fuel_type': fuel.nom,
                    'quantity': quantity,
                    'amount': amount
                })
        
        return sales_by_fuel
    
    def get_forex_impact(self, sales_qs, devise):
        """Calculate forex impact"""
        try:
            current_rate = TauxChange.objects.filter(is_active=True).first()
            if not current_rate:
                return {
                    'total_impact': 0,
                    'gains': 0,
                    'losses': 0,
                    'avg_rate': 0,
                    'by_fuel': []
                }
            
            total_impact = Decimal('0')
            gains = Decimal('0')
            losses = Decimal('0')
            rates_sum = Decimal('0')
            rates_count = 0
            fuel_impacts = {}
            
            for sale in sales_qs:
                if sale.taux_change and sale.taux_change != current_rate.taux_usd_fc:
                    # Calculate impact
                    expected_fc = sale.montant_usd * current_rate.taux_usd_fc
                    actual_fc = sale.montant_fc
                    fc_diff = actual_fc - expected_fc
                    usd_impact = fc_diff / current_rate.taux_usd_fc if current_rate.taux_usd_fc > 0 else Decimal('0')
                    
                    total_impact += usd_impact
                    
                    if usd_impact > 0:
                        gains += usd_impact
                    else:
                        losses += usd_impact
                    
                    # Track by fuel type
                    if sale.type_carburant:
                        fuel_name = sale.type_carburant.nom
                        if fuel_name not in fuel_impacts:
                            fuel_impacts[fuel_name] = Decimal('0')
                        fuel_impacts[fuel_name] += usd_impact
                
                if sale.taux_change:
                    rates_sum += sale.taux_change
                    rates_count += 1
            
            avg_rate = float(rates_sum / rates_count) if rates_count > 0 else float(current_rate.taux_usd_fc)
            
            by_fuel = [
                {'fuel_type': fuel, 'impact': float(impact)}
                for fuel, impact in fuel_impacts.items()
            ]
            
            return {
                'total_impact': float(total_impact),
                'gains': float(gains),
                'losses': float(losses),
                'avg_rate': avg_rate,
                'by_fuel': by_fuel
            }
            
        except Exception as e:
            print(f"Forex impact error: {e}")
            return {
                'total_impact': 0,
                'gains': 0,
                'losses': 0,
                'avg_rate': 0,
                'by_fuel': []
            }
    
    def get_recent_transactions(self, branche_id, devise, start, end):
        """Get 5 most recent transactions"""
        transactions = []
        
        # Get recent sales
        sales = Vente.objects.filter(
            created_at__gte=start,
            created_at__lte=end,
            statut='validee'
        ).select_related('branche')
        
        if branche_id != 'all':
            sales = sales.filter(branche_id=branche_id)
        
        sales = sales.order_by('-created_at')[:3]
        
        for sale in sales:
            if devise == 'USD':
                amount = float(sale.montant_usd)
            else:
                amount = float(sale.montant_fc)
            
            transactions.append({
                'date': sale.created_at.strftime('%d/%m/%Y'),
                'time': sale.created_at.strftime('%H:%M'),
                'type': 'vente',
                'branche': sale.branche.nom if sale.branche else 'N/A',
                'amount': amount,
                'currency': devise
            })
        
        # Get recent expenses
        expenses = Depense.objects.filter(
            created_at__gte=start,
            created_at__lte=end,
            statut='approuvee'
        ).select_related('branche')
        
        if branche_id != 'all':
            expenses = expenses.filter(branche_id=branche_id)
        
        if devise:
            expenses = expenses.filter(devise=devise)
        
        expenses = expenses.order_by('-created_at')[:3]
        
        for expense in expenses:
            transactions.append({
                'date': expense.created_at.strftime('%d/%m/%Y'),
                'time': expense.created_at.strftime('%H:%M'),
                'type': 'depense',
                'branche': expense.branche.nom if expense.branche else 'N/A',
                'amount': float(expense.montant),
                'currency': expense.devise
            })
        
        # Sort by date/time and limit to 5
        transactions.sort(key=lambda x: f"{x['date']} {x['time']}", reverse=True)
        return transactions[:5]
    
    def get_stock_alerts(self, branche_id):
        """Get stock alerts for low inventory"""
        stocks = Stock.objects.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).select_related('branche', 'type_carburant')
        
        if branche_id != 'all':
            stocks = stocks.filter(branche_id=branche_id)
        
        alerts = []
        for stock in stocks[:10]:  # Limit to 10 alerts
            alerts.append({
                'fuel_type': stock.type_carburant.nom if stock.type_carburant else 'Inconnu',
                'branche': stock.branche.nom if stock.branche else 'N/A',
                'current_stock': float(stock.quantite_actuelle),
                'threshold': float(stock.seuil_alerte)
            })
        
        return alerts


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

# Add to apps/admin_module/views.py

class CurrentExchangeRateView(AdminRequiredMixin, View):
    """Get current active exchange rate"""
    
    def get(self, request):
        try:
            current_rate = TauxChange.objects.filter(is_active=True).first()
            
            if not current_rate:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun taux actif trouvé'
                }, status=404)
            
            return JsonResponse({
                'success': True,
                'rate': {
                    'taux': str(current_rate.taux_usd_fc),
                    'date_effective': current_rate.date_effective.strftime('%d/%m/%Y %H:%M'),
                    'created_by': current_rate.created_by.get_full_name() if current_rate.created_by else 'System',
                    'is_active': current_rate.is_active
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ForexImpactView(AdminRequiredMixin, View):
    """Get forex impact analysis"""
    
    def get(self, request):
        try:
            period = request.GET.get('period', 'month')
            
            # Get current rate
            current_rate_obj = TauxChange.objects.filter(is_active=True).first()
            current_rate = current_rate_obj.taux_usd_fc if current_rate_obj else Decimal('2800.00')
            
            # Calculate period
            today = timezone.now().date()
            if period == 'week':
                start_date = today - timedelta(days=7)
            elif period == 'month':
                start_date = today.replace(day=1)
            elif period == 'year':
                start_date = today.replace(month=1, day=1)
            else:
                start_date = today.replace(day=1)
            
            # Get sales
            ventes = Vente.objects.filter(
                created_at__date__gte=start_date,
                statut='validee'
            ).select_related('type_carburant')
            
            # Calculate impact
            total_impact = Decimal('0')
            gains = Decimal('0')
            losses = Decimal('0')
            forex_by_fuel = {}
            
            for vente in ventes:
                if vente.taux_change and vente.taux_change != current_rate:
                    expected_fc = vente.montant_usd * current_rate
                    actual_fc = vente.montant_fc
                    fc_difference = actual_fc - expected_fc
                    usd_impact = fc_difference / current_rate if current_rate > 0 else Decimal('0')
                    
                    total_impact += usd_impact
                    
                    if usd_impact > 0:
                        gains += usd_impact
                    else:
                        losses += abs(usd_impact)
                    
                    # By fuel
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
            
            return JsonResponse({
                'success': True,
                'current_rate': str(current_rate),
                'period': period,
                'summary': {
                    'total_impact': str(round(total_impact, 2)),
                    'gains': str(round(gains, 2)),
                    'losses': str(round(losses, 2)),
                    'transactions_count': ventes.count()
                },
                'by_fuel': [{
                    'nom': fuel['nom'],
                    'couleur': fuel['couleur'],
                    'impact': str(round(fuel['impact'], 2)),
                    'transactions': fuel['transactions']
                } for fuel in forex_by_fuel.values()]
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
        
class UpdateExchangeRateView(AdminRequiredMixin, View):
    """Update exchange rate (Admin only)"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            new_rate = data.get('taux_usd_fc')
            if not new_rate:
                return JsonResponse({
                    'success': False,
                    'message': 'Le taux de change est requis'
                }, status=400)
            
            try:
                new_rate = Decimal(str(new_rate))
                if new_rate <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le taux doit être supérieur à 0'
                    }, status=400)
                
                if new_rate < 1000 or new_rate > 10000:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le taux doit être entre 1000 et 10000 FC'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Taux de change invalide'
                }, status=400)
            
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
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class ExchangeRateHistoryView(AdminRequiredMixin, View):
    """Get exchange rate history"""
    
    def get(self, request):
        try:
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
                'success': True,
                'rates': rates_data,
                'count': len(rates_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)



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

class CreatePaymentView(LoginRequiredMixin, View):
    """
    Create a payment for an abonné
    Updates the abonné's balance
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
                    }, status=400)
            
            # Get abonné
            try:
                abonne = Abonne.objects.get(id=data['abonne_id'], is_active=True)
            except Abonne.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Abonné introuvable'
                }, status=404)
            
            # Validate amount
            try:
                montant = Decimal(str(data['montant']))
                if montant <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le montant doit être supérieur à 0'
                    }, status=400)
            except (ValueError, TypeError, InvalidOperation):
                return JsonResponse({
                    'success': False,
                    'message': 'Montant invalide'
                }, status=400)
            
            # Validate currency
            devise = data['devise']
            if devise not in ['USD', 'FC']:
                return JsonResponse({
                    'success': False,
                    'message': 'Devise invalide (USD ou FC uniquement)'
                }, status=400)
            
            # Validate payment method
            methode = data['methode_paiement']
            if methode not in ['cash', 'mobile_money', 'bank']:
                return JsonResponse({
                    'success': False,
                    'message': 'Méthode de paiement invalide'
                }, status=400)
            
            # Get or create "Paiements Abonnés" category
            categorie, created = CategorieDepense.objects.get_or_create(
                nom='Paiements Abonnés',
                defaults={
                    'description': 'Paiements reçus des abonnés (clients entreprise)',
                    'created_by': request.user
                }
            )
            
            # Create payment record as a negative expense (income)
            # Get user's branch (for admin, use first branch or None)
            if request.user.role == 'admin':
                branche = Branche.objects.first()
            else:
                branche = request.user.branche
            
            payment_record = Depense.objects.create(
                branche=branche,
                categorie=categorie,
                description=f'Paiement reçu de {abonne.nom_entreprise} ({abonne.code_client})',
                montant=-montant,  # Negative to indicate income
                devise=devise,
                methode_paiement=methode,
                created_by=request.user
            )
            
            # Update abonné balance (payment increases balance)
            abonne.update_solde_with_consumption(montant, devise, 'paiement')
            
            return JsonResponse({
                'success': True,
                'message': 'Paiement enregistré avec succès',
                'payment': {
                    'id': payment_record.id,
                    'montant': str(montant),
                    'devise': devise,
                    'abonne': {
                        'id': abonne.id,
                        'nom': abonne.nom_entreprise,
                        'solde_usd': str(abonne.solde_usd),
                        'solde_fc': str(abonne.solde_fc)
                    }
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Format JSON invalide'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur serveur: {str(e)}'
            }, status=500)

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

    
class RapportsView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Reports page"""
    template_name = 'admin/rapports.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all active branches for filter
        context['branches'] = Branche.objects.filter(is_active=True).order_by('nom')
        
        return context
        
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
    """Payroll management with complete employee data"""
    template_name = 'admin/salaires.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter parameters
        branche_id = self.request.GET.get('branche_id', 'all')
        period = self.request.GET.get('period', 'month')
        
        # Get payment history (last 50 payments)
        payments = PaiementSalaire.objects.select_related(
            'pompiste', 'branche', 'caissier', 'employe_user'
        ).order_by('-date_paiement')[:50]
        
        # Apply branch filter if specified
        if branche_id != 'all':
            payments = payments.filter(branche_id=branche_id)
        
        context['payments'] = payments
        
        # Get all active branches for filters
        context['branches'] = Branche.objects.filter(is_active=True).order_by('nom')
        
        # Get all active pompistes with their data
        pompistes = Pompiste.objects.filter(is_active=True).select_related('branche')
        context['pompistes'] = pompistes
        
        # Get all system users (managers and caissiers) with their data
        system_users = User.objects.filter(
            is_active=True,
            role__in=['manager', 'caissier']
        ).select_related('branche')
        context['system_users'] = system_users
        
        # Calculate statistics for current period
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Sum, Count
        
        today = timezone.now().date()
        if period == 'month':
            start_date = today.replace(day=1)
        else:  # year
            start_date = today.replace(month=1, day=1)
        
        # Get payments for period
        period_payments = PaiementSalaire.objects.filter(
            date_paiement__date__gte=start_date,
            statut='paye'
        )
        
        if branche_id != 'all':
            period_payments = period_payments.filter(branche_id=branche_id)
        
        # Calculate totals
        stats = {
            'total_usd': float(period_payments.filter(devise_paiement='USD').aggregate(
                Sum('montant_paye'))['montant_paye__sum'] or 0),
            'total_fc': float(period_payments.filter(devise_paiement='FC').aggregate(
                Sum('montant_paye'))['montant_paye__sum'] or 0),
            'employees_paid': period_payments.values('pompiste', 'employe_user').distinct().count(),
            'period': period
        }
        
        context['statistics'] = stats
        
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

class AdminRequiredMixin(UserPassesTestMixin):
    """Mixin to restrict access to admin users only"""
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == 'admin'


# ==================== EXPENSES CRUD APIs ====================

class DepensesListAPIView(AdminRequiredMixin, View):
    """
    Get list of expenses with filters and stats
    Returns expenses data, totals, and categories count
    """
    
    def get(self, request):
        try:
            # Get filter parameters
            branche_id = request.GET.get('branche_id', 'all')
            categorie_id = request.GET.get('categorie_id', 'all')
            devise = request.GET.get('devise', 'all')
            period = request.GET.get('period', 'month')
            
            # Base queryset
            depenses = Depense.objects.select_related(
                'branche', 'categorie', 'created_by'
            ).filter(statut='approuvee')
            
            # Apply filters
            if branche_id and branche_id != 'all':
                depenses = depenses.filter(branche_id=branche_id)
            
            if categorie_id and categorie_id != 'all':
                depenses = depenses.filter(categorie_id=categorie_id)
            
            if devise and devise != 'all':
                depenses = depenses.filter(devise=devise)
            
            # Period filter
            today = timezone.now().date()
            if period == 'today':
                depenses = depenses.filter(created_at__date=today)
            elif period == 'week':
                week_ago = today - timedelta(days=7)
                depenses = depenses.filter(created_at__date__gte=week_ago)
            elif period == 'month':
                month_ago = today - timedelta(days=30)
                depenses = depenses.filter(created_at__date__gte=month_ago)
            
            # Prepare response data
            depenses_data = []
            for depense in depenses.order_by('-created_at'):
                depenses_data.append({
                    'id': depense.id,
                    'date': depense.created_at.strftime('%d/%m/%Y'),
                    'time': depense.created_at.strftime('%H:%M'),
                    'branche': depense.branche.nom if depense.branche else 'N/A',
                    'branche_id': depense.branche.id if depense.branche else None,
                    'categorie': depense.categorie.nom if depense.categorie else 'N/A',
                    'categorie_id': depense.categorie.id if depense.categorie else None,
                    'description': depense.description,
                    'montant': str(depense.montant),
                    'devise': depense.devise,
                    'beneficiaire': depense.beneficiaire or '',
                    'statut': depense.statut,
                    'statut_display': depense.get_statut_display(),
                    'created_by': depense.created_by.get_full_name() if depense.created_by else 'N/A'
                })
            
            # Calculate totals
            total_usd = float(depenses.filter(devise='USD').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            total_fc = float(depenses.filter(devise='FC').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            
            # Categories count
            categories_count = CategorieDepense.objects.filter(is_active=True).count()
            
            return JsonResponse({
                'success': True,
                'depenses': depenses_data,
                'count': len(depenses_data),
                'total_usd': total_usd,
                'total_fc': total_fc,
                'categories_count': categories_count
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class CreateDepenseView(AdminRequiredMixin, View):
    """Create a new expense"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Required fields
            required_fields = ['branche_id', 'categorie_id', 'description', 'montant', 'devise']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Get branch
            try:
                branche = Branche.objects.get(id=data['branche_id'])
            except Branche.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Branche introuvable'
                }, status=400)
            
            # Get category
            try:
                categorie = CategorieDepense.objects.get(
                    id=data['categorie_id'],
                    is_active=True
                )
            except CategorieDepense.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Catégorie introuvable ou inactive'
                }, status=400)
            
            # Validate amount
            try:
                montant = Decimal(str(data['montant']))
                if montant <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le montant doit être supérieur à 0'
                    }, status=400)
            except (ValueError, TypeError, InvalidOperation):
                return JsonResponse({
                    'success': False,
                    'message': 'Montant invalide'
                }, status=400)
            
            # Validate currency
            if data['devise'] not in ['USD', 'FC']:
                return JsonResponse({
                    'success': False,
                    'message': 'Devise invalide (USD ou FC uniquement)'
                }, status=400)
            
            # Create expense
            depense = Depense.objects.create(
                branche=branche,
                categorie=categorie,
                created_by=request.user,
                description=data['description'],
                montant=montant,
                devise=data['devise'],
                beneficiaire=data.get('beneficiaire', ''),
                notes=data.get('notes', ''),
                statut='approuvee'  # Auto-approved for admin
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Dépense enregistrée avec succès',
                'depense': {
                    'id': depense.id,
                    'description': depense.description,
                    'montant': float(depense.montant),
                    'devise': depense.devise
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
                'message': f'Erreur: {str(e)}'
            }, status=500)


class DepenseDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about an expense"""
    
    def get(self, request, depense_id):
        try:
            depense = get_object_or_404(
                Depense.objects.select_related('branche', 'categorie', 'created_by'),
                id=depense_id
            )
            
            return JsonResponse({
                'success': True,
                'expense': {
                    'id': depense.id,
                    'date': depense.created_at.strftime('%d/%m/%Y %H:%M'),
                    'categorie': depense.categorie.nom,
                    'description': depense.description,
                    'montant': f"{float(depense.montant):.2f}",
                    'devise': depense.devise,
                    'branche': depense.branche.nom,
                    'beneficiaire': depense.beneficiaire or 'N/A',
                    'notes': depense.notes or '',
                    'created_by': depense.created_by.get_full_name() if depense.created_by else 'N/A',
                    'statut': depense.statut,
                    'statut_display': depense.get_statut_display()
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateDepenseView(AdminRequiredMixin, View):
    """Update an existing expense"""
    
    def put(self, request, depense_id):
        try:
            data = json.loads(request.body)
            depense = get_object_or_404(Depense, id=depense_id)
            
            # Update fields if provided
            if data.get('description'):
                depense.description = data['description']
            
            if data.get('montant'):
                try:
                    montant = Decimal(str(data['montant']))
                    if montant <= 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le montant doit être supérieur à 0'
                        }, status=400)
                    depense.montant = montant
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Montant invalide'
                    }, status=400)
            
            if data.get('devise') and data['devise'] in ['USD', 'FC']:
                depense.devise = data['devise']
            
            if data.get('categorie_id'):
                try:
                    categorie = CategorieDepense.objects.get(
                        id=data['categorie_id'],
                        is_active=True
                    )
                    depense.categorie = categorie
                except CategorieDepense.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Catégorie introuvable'
                    }, status=400)
            
            if 'beneficiaire' in data:
                depense.beneficiaire = data['beneficiaire']
            
            if 'notes' in data:
                depense.notes = data['notes']
            
            depense.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Dépense modifiée avec succès'
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


class DeleteDepenseView(AdminRequiredMixin, View):
    """Delete an expense"""
    
    def delete(self, request, depense_id):
        try:
            depense = get_object_or_404(Depense, id=depense_id)
            
            # Store info before deletion
            description = depense.description
            
            # Delete the expense
            depense.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Dépense "{description}" supprimée avec succès'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ExpensesStatsView(AdminRequiredMixin, View):
    """Get comprehensive expense statistics"""
    
    def get(self, request):
        try:
            # Get filter parameters
            branche_id = request.GET.get('branche_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Base queryset
            depenses = Depense.objects.filter(statut='approuvee')
            
            # Branch filter
            if branche_id and branche_id != 'all':
                depenses = depenses.filter(branche_id=branche_id)
            
            # Period filter
            today = timezone.now().date()
            if period == 'today':
                depenses = depenses.filter(created_at__date=today)
            elif period == 'week':
                week_ago = today - timedelta(days=7)
                depenses = depenses.filter(created_at__date__gte=week_ago)
            elif period == 'month':
                month_ago = today - timedelta(days=30)
                depenses = depenses.filter(created_at__date__gte=month_ago)
            
            # Calculate totals by currency
            total_usd = float(depenses.filter(devise='USD').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            total_fc = float(depenses.filter(devise='FC').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            
            # Get expenses by category
            by_category = depenses.values('categorie__nom').annotate(
                total=Sum('montant'),
                count=Count('id')
            ).order_by('-total')[:10]
            
            # Get expenses by branch
            by_branch = depenses.values('branche__nom').annotate(
                total_usd=Sum('montant', filter=Q(devise='USD')),
                total_fc=Sum('montant', filter=Q(devise='FC')),
                count=Count('id')
            ).order_by('-count')[:10]
            
            # Recent expenses
            recent = depenses.select_related('branche', 'categorie').order_by('-created_at')[:10]
            recent_data = [{
                'id': d.id,
                'date': d.created_at.strftime('%d/%m/%Y'),
                'categorie': d.categorie.nom,
                'description': d.description[:50],
                'montant': float(d.montant),
                'devise': d.devise,
                'branche': d.branche.nom
            } for d in recent]
            
            return JsonResponse({
                'success': True,
                'stats': {
                    'total_usd': total_usd,
                    'total_fc': total_fc,
                    'count': depenses.count(),
                    'by_category': list(by_category),
                    'by_branch': list(by_branch),
                    'recent': recent_data
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ExpensesAnalyticsAPIView(AdminRequiredMixin, View):
    """
    Get comprehensive analytics data for expenses
    Returns data for 4 charts: by category, trend, by branch, currency distribution
    """
    
    def get(self, request):
        try:
            # Get filter parameters
            period = request.GET.get('period', 'month')
            branche_id = request.GET.get('branche_id', 'all')
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'week':
                start_date = today - timedelta(days=7)
            elif period == 'month':
                start_date = today - timedelta(days=30)
            elif period == 'quarter':
                start_date = today - timedelta(days=90)
            else:
                start_date = today - timedelta(days=30)  # default to month
            
            # Base queryset
            depenses = Depense.objects.filter(
                created_at__date__gte=start_date,
                statut='approuvee'
            )
            
            # Apply branch filter if specified
            if branche_id and branche_id != 'all':
                depenses = depenses.filter(branche_id=branche_id)
            
            # 1. By Category
            by_category = depenses.values('categorie__nom').annotate(
                total=Sum('montant'),
                count=Count('id')
            ).order_by('-total')[:10]
            
            # 2. Trend (daily aggregation)
            trend = depenses.annotate(
                date=TruncDate('created_at')
            ).values('date').annotate(
                total=Sum('montant')
            ).order_by('date')
            
            # Fill in missing dates with zeros for smooth chart
            trend_dict = {str(t['date']): float(t['total']) for t in trend}
            filled_trend = []
            days_count = 30 if period == 'month' else 7 if period == 'week' else 90
            
            for i in range(days_count + 1):
                check_date = start_date + timedelta(days=i)
                date_str = str(check_date)
                filled_trend.append({
                    'date': date_str,
                    'date__date': date_str,  # For compatibility
                    'total': trend_dict.get(date_str, 0)
                })
            
            # 3. By Branch
            by_branch = depenses.values('branche__nom').annotate(
                total_usd=Sum('montant', filter=Q(devise='USD')),
                total_fc=Sum('montant', filter=Q(devise='FC')),
                count=Count('id')
            ).order_by('-total_usd')[:10]
            
            # 4. Totals by currency
            total_usd = float(depenses.filter(devise='USD').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            total_fc = float(depenses.filter(devise='FC').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            
            return JsonResponse({
                'success': True,
                'by_category': [
                    {
                        'categorie__nom': item['categorie__nom'],
                        'total': float(item['total']),
                        'count': item['count']
                    }
                    for item in by_category
                ],
                'trend': filled_trend,
                'by_branch': [
                    {
                        'branche__nom': item['branche__nom'],
                        'total_usd': float(item['total_usd'] or 0),
                        'total_fc': float(item['total_fc'] or 0),
                        'count': item['count']
                    }
                    for item in by_branch
                ],
                'total_usd': total_usd,
                'total_fc': total_fc
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================
# VIEW 3: Bulk Delete Expenses
# ============================================

class BulkDeleteExpensesView(AdminRequiredMixin, View):
    """
    Delete multiple expenses at once
    Accepts array of expense IDs
    """
    
    def delete(self, request):
        try:
            data = json.loads(request.body)
            ids = data.get('ids', [])
            
            if not ids:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucune dépense sélectionnée'
                }, status=400)
            
            # Validate IDs
            try:
                ids = [int(id) for id in ids]
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'IDs invalides'
                }, status=400)
            
            # Delete expenses
            deleted = Depense.objects.filter(id__in=ids).delete()
            
            return JsonResponse({
                'success': True,
                'deleted_count': deleted[0],
                'message': f'{deleted[0]} dépense(s) supprimée(s)'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================
# VIEW 4: Bulk Export Expenses to PDF
# ============================================

class BulkExportExpensesPDFView(AdminRequiredMixin, View):
    """
    Export selected expenses to PDF with professional formatting
    Can export specific IDs or use filters
    """
    
    def get(self, request):
        try:
            # Check if specific IDs provided
            ids_param = request.GET.get('ids', '')
            
            if ids_param:
                # Export specific expenses
                ids = [int(id.strip()) for id in ids_param.split(',') if id.strip()]
                depenses = Depense.objects.filter(id__in=ids)
                title_suffix = f'{len(ids)} sélectionnée(s)'
            else:
                # Export with filters
                branche_id = request.GET.get('branche_id', 'all')
                categorie_id = request.GET.get('categorie_id', 'all')
                devise = request.GET.get('devise', 'all')
                period = request.GET.get('period', 'month')
                
                depenses = Depense.objects.filter(statut='approuvee')
                
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
                
                title_suffix = 'avec filtres'
            
            depenses = depenses.select_related('branche', 'categorie', 'created_by')
            
            if not depenses.exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Aucune dépense trouvée'
                }, status=404)
            
            # Create PDF
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="depenses_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#DC2626'),
                spaceAfter=30,
                alignment=1
            )
            
            # Title
            elements.append(Paragraph('PETROX - Rapport des Dépenses', title_style))
            elements.append(Paragraph(f'Export: {title_suffix}', styles['Normal']))
            elements.append(Paragraph(f'Généré le: {timezone.now().strftime("%d/%m/%Y à %H:%M")}', styles['Normal']))
            elements.append(Spacer(1, 0.5*inch))
            
            # Summary
            total_usd = sum(float(d.montant) for d in depenses if d.devise == 'USD')
            total_fc = sum(float(d.montant) for d in depenses if d.devise == 'FC')
            
            summary_data = [
                ['Métrique', 'Valeur'],
                ['Nombre de dépenses', str(len(depenses))],
                ['Total USD', f'${total_usd:.2f}'],
                ['Total FC', f'{total_fc:.0f} FC']
            ]
            
            summary_table = Table(summary_data, colWidths=[2.5*inch, 2*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
            ]))
            
            elements.append(summary_table)
            elements.append(Spacer(1, 0.4*inch))
            
            # Detailed table
            elements.append(Paragraph('Détails des Dépenses', styles['Heading2']))
            elements.append(Spacer(1, 0.2*inch))
            
            data = [['Date', 'Branche', 'Catégorie', 'Description', 'Montant', 'Devise']]
            
            for dep in depenses.order_by('-created_at')[:50]:  # Limit to 50
                data.append([
                    dep.created_at.strftime('%d/%m/%Y'),
                    (dep.branche.nom if dep.branche else 'N/A')[:15],
                    (dep.categorie.nom if dep.categorie else 'N/A')[:15],
                    dep.description[:30],
                    f'{float(dep.montant):.2f}',
                    dep.devise
                ])
            
            detail_table = Table(data, colWidths=[0.9*inch, 1.3*inch, 1.2*inch, 2*inch, 0.9*inch, 0.6*inch])
            detail_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F2937')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            
            elements.append(detail_table)
            
            # Build PDF
            doc.build(elements)
            pdf = buffer.getvalue()
            buffer.close()
            response.write(pdf)
            
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur export PDF: {str(e)}'
            }, status=500)


# ============================================
# VIEW 5: Bulk Export Expenses to Excel
# ============================================

class BulkExportExpensesExcelView(AdminRequiredMixin, View):
    """
    Export expenses to Excel with formatting
    """
    
    def get(self, request):
        try:
            # Check if specific IDs provided
            ids_param = request.GET.get('ids', '')
            
            if ids_param:
                ids = [int(id.strip()) for id in ids_param.split(',') if id.strip()]
                depenses = Depense.objects.filter(id__in=ids)
            else:
                # Use filters
                branche_id = request.GET.get('branche_id', 'all')
                categorie_id = request.GET.get('categorie_id', 'all')
                devise = request.GET.get('devise', 'all')
                period = request.GET.get('period', 'month')
                
                depenses = Depense.objects.filter(statut='approuvee')
                
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
            
            depenses = depenses.select_related('branche', 'categorie', 'created_by')
            
            if not depenses.exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Aucune dépense trouvée'
                }, status=404)
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Dépenses'
            
            # Header styling
            header_fill = PatternFill(start_color='DC2626', end_color='DC2626', fill_type='solid')
            header_font = Font(bold=True, color='FFFFFF', size=12)
            border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # Headers
            headers = [
                'Date', 'Heure', 'Branche', 'Catégorie', 'Description',
                'Montant', 'Devise', 'Bénéficiaire', 'Enregistré par', 'Statut'
            ]
            
            for col_num, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_num)
                cell.value = header
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = border
            
            # Data rows
            for row_num, dep in enumerate(depenses.order_by('-created_at'), 2):
                ws.cell(row=row_num, column=1).value = dep.created_at.strftime('%d/%m/%Y')
                ws.cell(row=row_num, column=2).value = dep.created_at.strftime('%H:%M')
                ws.cell(row=row_num, column=3).value = dep.branche.nom if dep.branche else 'N/A'
                ws.cell(row=row_num, column=4).value = dep.categorie.nom if dep.categorie else 'N/A'
                ws.cell(row=row_num, column=5).value = dep.description
                ws.cell(row=row_num, column=6).value = float(dep.montant)
                ws.cell(row=row_num, column=7).value = dep.devise
                ws.cell(row=row_num, column=8).value = dep.beneficiaire or ''
                ws.cell(row=row_num, column=9).value = dep.created_by.get_full_name() if dep.created_by else 'N/A'
                ws.cell(row=row_num, column=10).value = dep.get_statut_display()
                
                # Apply border
                for col_num in range(1, 11):
                    ws.cell(row=row_num, column=col_num).border = border
            
            # Adjust column widths
            column_widths = [12, 8, 18, 15, 35, 12, 8, 20, 20, 12]
            for col_num, width in enumerate(column_widths, 1):
                ws.column_dimensions[openpyxl.utils.get_column_letter(col_num)].width = width
            
            # Summary row
            summary_row = len(list(depenses)) + 3
            ws.cell(row=summary_row, column=1).value = 'TOTAUX'
            ws.cell(row=summary_row, column=1).font = Font(bold=True, size=12)
            
            total_usd = sum(float(d.montant) for d in depenses if d.devise == 'USD')
            total_fc = sum(float(d.montant) for d in depenses if d.devise == 'FC')
            
            ws.cell(row=summary_row, column=5).value = f'USD: ${total_usd:.2f} | FC: {total_fc:.0f} FC'
            ws.cell(row=summary_row, column=5).font = Font(bold=True, size=12)
            
            # Save to response
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="depenses_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
            
            wb.save(response)
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur export Excel: {str(e)}'
            }, status=500)


# ============================================
# VIEW 6: Print Single Expense Receipt
# ============================================

class PrintExpenseReceiptView(AdminRequiredMixin, View):
    """
    Generate printable receipt for single expense
    Returns HTML formatted for printing
    """
    
    def get(self, request, expense_id):
        try:
            depense = get_object_or_404(
                Depense.objects.select_related(
                    'branche', 'categorie', 'created_by'
                ),
                id=expense_id
            )
            
            # Generate HTML receipt
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Reçu Dépense - {depense.id}</title>
                <style>
                    @media print {{
                        @page {{ margin: 0.5cm; }}
                        body {{ margin: 0; padding: 20px; }}
                    }}
                    body {{
                        font-family: 'Arial', sans-serif;
                        max-width: 80mm;
                        margin: 0 auto;
                        padding: 10px;
                    }}
                    .header {{
                        text-align: center;
                        border-bottom: 2px solid #DC2626;
                        padding-bottom: 10px;
                        margin-bottom: 15px;
                    }}
                    .logo {{
                        font-size: 24px;
                        font-weight: bold;
                        color: #DC2626;
                        margin-bottom: 5px;
                    }}
                    .branch {{
                        font-size: 14px;
                        color: #555;
                    }}
                    .section {{
                        margin-bottom: 15px;
                    }}
                    .label {{
                        font-size: 11px;
                        color: #666;
                        margin-bottom: 2px;
                    }}
                    .value {{
                        font-size: 13px;
                        font-weight: bold;
                        margin-bottom: 8px;
                    }}
                    .amount {{
                        text-align: center;
                        border: 2px solid #DC2626;
                        padding: 15px;
                        margin: 15px 0;
                    }}
                    .amount-label {{
                        font-size: 12px;
                        color: #666;
                        margin-bottom: 5px;
                    }}
                    .amount-value {{
                        font-size: 24px;
                        font-weight: bold;
                        color: #DC2626;
                    }}
                    .footer {{
                        text-align: center;
                        font-size: 10px;
                        color: #999;
                        border-top: 1px solid #ddd;
                        padding-top: 10px;
                        margin-top: 15px;
                    }}
                    .description {{
                        font-size: 11px;
                        color: #444;
                        padding: 10px;
                        background-color: #f9f9f9;
                        border-radius: 4px;
                        margin: 10px 0;
                    }}
                </style>
            </head>
            <body>
                <div class="header">
                    <div class="logo">PETROX</div>
                    <div class="branch">{depense.branche.nom if depense.branche else 'N/A'}</div>
                    <div style="font-size: 10px; color: #999;">
                        {depense.branche.adresse if depense.branche else ''}<br>
                        {depense.branche.ville if depense.branche else ''}, {depense.branche.province if depense.branche else ''}
                    </div>
                </div>
                
                <div class="section">
                    <div class="label">Numéro de Transaction</div>
                    <div class="value">DEP-{depense.id:06d}</div>
                    
                    <div class="label">Date et Heure</div>
                    <div class="value">{depense.created_at.strftime('%d/%m/%Y à %H:%M')}</div>
                    
                    <div class="label">Catégorie</div>
                    <div class="value">{depense.categorie.nom if depense.categorie else 'N/A'}</div>
                    
                    {f'<div class="label">Bénéficiaire</div><div class="value">{depense.beneficiaire}</div>' if depense.beneficiaire else ''}
                </div>
                
                <div class="description">
                    <div class="label">Description</div>
                    <div style="margin-top: 5px;">{depense.description}</div>
                </div>
                
                <div class="amount">
                    <div class="amount-label">MONTANT</div>
                    <div class="amount-value">
                        {depense.devise == 'USD' and f'${float(depense.montant):.2f}' or f'{float(depense.montant):.0f} FC'}
                    </div>
                </div>
                
                <div class="section">
                    <div class="label">Enregistré par</div>
                    <div class="value">{depense.created_by.get_full_name() if depense.created_by else 'N/A'}</div>
                    
                    <div class="label">Statut</div>
                    <div class="value">{depense.get_statut_display()}</div>
                </div>
                
                <div class="footer">
                    <div>PETROX - Gestion de Stations</div>
                    <div>Imprimé le {timezone.now().strftime('%d/%m/%Y à %H:%M')}</div>
                </div>
                
                <script>
                    window.onload = function() {{
                        window.print();
                    }};
                </script>
            </body>
            </html>
            """
            
            return HttpResponse(html_content, content_type='text/html')
            
        except Exception as e:
            return HttpResponse(f'<html><body><h3>Erreur: {str(e)}</h3></body></html>')




# ==================== EXPENSE CATEGORIES APIs ====================

# class CategoriesListAPIView(AdminRequiredMixin, View):
#     """Get list of expense categories"""
    
#     def get(self, request):
#         try:
#             # Get active categories
#             active_categories = CategorieDepense.objects.filter(is_active=True)
            
#             # Get pending category requests
#             pending_categories = CategorieDepense.objects.filter(is_active=False)
            
#             active_data = [{
#                 'id': cat.id,
#                 'nom': cat.nom,
#                 'description': cat.description or '',
#                 'is_active': cat.is_active,
#                 'created_at': cat.created_at.strftime('%Y-%m-%d')
#             } for cat in active_categories]
            
#             pending_data = [{
#                 'id': cat.id,
#                 'nom': cat.nom,
#                 'description': cat.description or '',
#                 'created_by': cat.created_by.get_full_name() if hasattr(cat, 'created_by') and cat.created_by else 'N/A',
#                 'created_at': cat.created_at.strftime('%Y-%m-%d')
#             } for cat in pending_categories]
            
#             return JsonResponse({
#                 'success': True,
#                 'active_categories': active_data,
#                 'pending_categories': pending_data,
#                 'active_count': len(active_data),
#                 'pending_count': len(pending_data)
#             })
            
#         except Exception as e:
#             return JsonResponse({
#                 'success': False,
#                 'message': str(e)
#             }, status=500)


class CreateCategoryView(AdminRequiredMixin, View):
    """Create a new expense category"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            if not data.get('nom'):
                return JsonResponse({
                    'success': False,
                    'message': 'Le nom de la catégorie est requis'
                }, status=400)
            
            # Check if category already exists
            if CategorieDepense.objects.filter(nom__iexact=data['nom']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Cette catégorie existe déjà'
                }, status=400)
            
            # Create category (active by default for admin)
            category = CategorieDepense.objects.create(
                nom=data['nom'],
                description=data.get('description', ''),
                is_active=True
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
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class UpdateCategoryView(AdminRequiredMixin, View):
    """Update an existing category"""
    
    def put(self, request, category_id):
        try:
            data = json.loads(request.body)
            category = get_object_or_404(CategorieDepense, id=category_id)
            
            # Update fields if provided
            if data.get('nom'):
                # Check if new name already exists
                if CategorieDepense.objects.filter(
                    nom__iexact=data['nom']
                ).exclude(id=category_id).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Cette catégorie existe déjà'
                    }, status=400)
                category.nom = data['nom']
            
            if 'description' in data:
                category.description = data['description']
            
            category.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Catégorie modifiée avec succès'
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


class DeleteCategoryView(AdminRequiredMixin, View):
    """Delete a category"""
    
    def delete(self, request, category_id):
        try:
            category = get_object_or_404(CategorieDepense, id=category_id)
            
            # Check if category is being used
            expenses_count = Depense.objects.filter(categorie=category).count()
            
            if expenses_count > 0:
                # Soft delete - deactivate instead
                category.is_active = False
                category.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Catégorie désactivée ({expenses_count} dépenses utilisent cette catégorie)'
                })
            else:
                # Hard delete if not used
                nom = category.nom
                category.delete()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Catégorie "{nom}" supprimée définitivement'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ApproveCategoryView(AdminRequiredMixin, View):
    """Approve a pending category request"""
    
    def patch(self, request, category_id):
        try:
            category = get_object_or_404(CategorieDepense, id=category_id)
            
            # Activate the category
            category.is_active = True
            category.save()
            
            # Notify the requester if exists
            if hasattr(category, 'created_by') and category.created_by:
                Notification.objects.create(
                    destinataire=category.created_by,
                    expediteur=request.user,
                    type_notification='system',
                    priorite='normale',
                    titre='Demande de catégorie approuvée',
                    message=f'Votre demande de création de la catégorie "{category.nom}" a été approuvée'
                )
            
            return JsonResponse({
                'success': True,
                'message': f'Catégorie "{category.nom}" approuvée avec succès'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ToggleCategoryView(AdminRequiredMixin, View):
    """Toggle category active status"""
    
    def patch(self, request, category_id):
        try:
            category = get_object_or_404(CategorieDepense, id=category_id)
            
            # Toggle active status
            category.is_active = not category.is_active
            category.save()
            
            status = 'activée' if category.is_active else 'désactivée'
            
            return JsonResponse({
                'success': True,
                'message': f'Catégorie {status} avec succès',
                'is_active': category.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class AdminRequiredMixin(UserPassesTestMixin):
    """Mixin to restrict access to admin users only"""
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == 'admin'


# ==================== SALES CRUD APIs ====================

class VentesListAPIView(AdminRequiredMixin, View):
    """Get list of sales with filters"""
    
    def get(self, request):
        try:
            # Get filter parameters
            branche_id = request.GET.get('branche_id', 'all')
            statut = request.GET.get('statut', 'all')
            pompiste_id = request.GET.get('pompiste_id', 'all')
            type_carburant_id = request.GET.get('type_carburant_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Base queryset
            ventes = Vente.objects.select_related(
                'branche', 'pompiste', 'manager', 'caissier',
                'type_carburant', 'moyen_paiement'
            )
            
            # Branch filter
            if branche_id and branche_id != 'all':
                ventes = ventes.filter(branche_id=branche_id)
            
            # Status filter
            if statut and statut != 'all':
                ventes = ventes.filter(statut=statut)
            
            # Pompiste filter
            if pompiste_id and pompiste_id != 'all':
                ventes = ventes.filter(pompiste_id=pompiste_id)
            
            # Fuel type filter
            if type_carburant_id and type_carburant_id != 'all':
                ventes = ventes.filter(type_carburant_id=type_carburant_id)
            
            # Period filter
            today = timezone.now().date()
            if period == 'today':
                ventes = ventes.filter(created_at__date=today)
            elif period == 'week':
                week_ago = today - timedelta(days=7)
                ventes = ventes.filter(created_at__date__gte=week_ago)
            elif period == 'month':
                month_ago = today - timedelta(days=30)
                ventes = ventes.filter(created_at__date__gte=month_ago)
            
            # Build response
            ventes_data = []
            for vente in ventes.order_by('-created_at')[:100]:  # Limit to 100
                ventes_data.append({
                    'id': vente.id,
                    'date': vente.created_at.strftime('%Y-%m-%d %H:%M'),
                    'branche': vente.branche.nom,
                    'branche_id': vente.branche.id,
                    'pompiste': vente.pompiste.get_full_name(),
                    'pompiste_id': vente.pompiste.id,
                    'manager': vente.manager.get_full_name() if vente.manager else 'N/A',
                    'caissier': vente.caissier.get_full_name() if vente.caissier else 'N/A',
                    'type_carburant': vente.type_carburant.nom,
                    'type_carburant_id': vente.type_carburant.id,
                    'quantite': float(vente.quantite),
                    'montant_usd': float(vente.montant_usd),
                    'montant_fc': float(vente.montant_fc),
                    'moyen_paiement': vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A',
                    'statut': vente.statut,
                    'statut_display': vente.get_statut_display(),
                    'manquant_usd': float(vente.manquant_usd) if vente.manquant_usd else 0,
                    'manquant_fc': float(vente.manquant_fc) if vente.manquant_fc else 0
                })
            
            # Calculate totals for validated sales only
            validated_sales = ventes.filter(statut='validee')
            total_usd = float(validated_sales.aggregate(
                Sum('montant_usd'))['montant_usd__sum'] or 0)
            total_fc = float(validated_sales.aggregate(
                Sum('montant_fc'))['montant_fc__sum'] or 0)
            
            return JsonResponse({
                'success': True,
                'ventes': ventes_data,
                'count': len(ventes_data),
                'total_usd': total_usd,
                'total_fc': total_fc,
                'validated_count': validated_sales.count(),
                'pending_count': ventes.filter(statut='en_attente').count(),
                'manquants_count': ventes.filter(statut='manquant').count()
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class VenteDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about a single sale"""
    
    def get(self, request, vente_id):
        try:
            vente = Vente.objects.select_related(
                'branche',
                'pompiste',
                'manager',
                'type_carburant',
                'moyen_paiement',
                'abonne',
                'caissier'
            ).get(id=vente_id)
            
            # Build response matching frontend expectations
            sale_data = {
                'id': vente.id,
                'date': vente.created_at.strftime('%d/%m/%Y %H:%M'),
                'branche': vente.branche.nom if vente.branche else 'N/A',
                'pompiste': f"{vente.pompiste.prenom} {vente.pompiste.nom}" if vente.pompiste else 'N/A',
                'manager': f"{vente.manager.prenom} {vente.manager.nom}" if vente.manager else 'N/A',
                'validated_by': f"{vente.caissier.prenom} {vente.caissier.nom}" if vente.caissier else None,
                
                # Fuel details
                'fuel_type': vente.type_carburant.nom if vente.type_carburant else 'N/A',
                'fuel_color': vente.type_carburant.couleur_hex if vente.type_carburant else '#000000',
                'quantite': float(vente.quantite),
                
                # FIXED: Get prix_unitaire from type_carburant, not from vente
                'prix_vente_usd': float(vente.type_carburant.prix_vente_usd) if vente.type_carburant else 0,
                'prix_vente_fc': float(vente.type_carburant.prix_vente_fc) if vente.type_carburant else 0,
                'montant_usd': float(vente.montant_usd),
                'montant_fc': float(vente.montant_fc),
                'taux_change': float(vente.taux_change),
                
                # Payment
                'moyen_paiement': vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A',
                
                # Status
                'statut': vente.statut,
                'statut_display': vente.get_statut_display() if hasattr(vente, 'get_statut_display') else vente.statut.replace('_', ' ').title(),
                
                # Manquant details (if applicable)
                'manquant_usd': float(vente.manquant_usd) if vente.manquant_usd else 0,
                'manquant_fc': float(vente.manquant_fc) if vente.manquant_fc else 0,
                'raison_manquant': vente.raison_manquant if hasattr(vente, 'raison_manquant') and vente.raison_manquant else None,
                
                # Notes
                'observations': vente.observations if hasattr(vente, 'observations') and vente.observations else None
            }
            
            return JsonResponse({
                'success': True,
                'sale': sale_data
            })
            
        except Vente.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Vente non trouvée'
            }, status=404)
        except Exception as e:
            import traceback
            print(f"Error in VenteDetailAPIView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class VentesStatsView(AdminRequiredMixin, View):
    """Get comprehensive sales statistics"""
    
    def get(self, request):
        try:
            # Get filter parameters
            branche_id = request.GET.get('branche_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Base queryset - only validated sales
            ventes = Vente.objects.filter(statut='validee')
            
            # Branch filter
            if branche_id and branche_id != 'all':
                ventes = ventes.filter(branche_id=branche_id)
            
            # Period filter
            today = timezone.now().date()
            if period == 'today':
                ventes = ventes.filter(created_at__date=today)
            elif period == 'week':
                week_ago = today - timedelta(days=7)
                ventes = ventes.filter(created_at__date__gte=week_ago)
            elif period == 'month':
                month_ago = today - timedelta(days=30)
                ventes = ventes.filter(created_at__date__gte=month_ago)
            
            # Calculate totals
            total_usd = float(ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0)
            total_fc = float(ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0)
            total_quantity = float(ventes.aggregate(Sum('quantite'))['quantite__sum'] or 0)
            
            # Get sales by fuel type
            by_fuel = ventes.values('type_carburant__nom').annotate(
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                quantity=Sum('quantite'),
                count=Count('id')
            ).order_by('-total_usd')
            
            # Get sales by branch
            by_branch = ventes.values('branche__nom').annotate(
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                count=Count('id')
            ).order_by('-total_usd')
            
            # Get sales by pompiste with manquants count
            by_pompiste = ventes.values(
                'pompiste__id',
                'pompiste__prenom',
                'pompiste__nom'
            ).annotate(
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                count=Count('id')
            ).order_by('-total_usd')[:10]
            
            # Add manquants count for each pompiste
            pompiste_stats = []
            for p in by_pompiste:
                manquants_count = Vente.objects.filter(
                    pompiste_id=p['pompiste__id'],
                    statut='manquant'
                ).count()
                
                pompiste_stats.append({
                    'pompiste': f"{p['pompiste__prenom']} {p['pompiste__nom']}",
                    'total_usd': float(p['total_usd'] or 0),
                    'total_fc': float(p['total_fc'] or 0),
                    'count': p['count'],
                    'manquants_count': manquants_count
                })
            
            # Recent sales
            recent = ventes.select_related(
                'branche', 'pompiste', 'type_carburant'
            ).order_by('-created_at')[:10]
            
            recent_data = [{
                'id': v.id,
                'date': v.created_at.strftime('%d/%m/%Y'),
                'branche': v.branche.nom,
                'pompiste': v.pompiste.get_full_name(),
                'carburant': v.type_carburant.nom,
                'quantite': float(v.quantite),
                'montant_usd': float(v.montant_usd),
                'montant_fc': float(v.montant_fc)
            } for v in recent]
            
            return JsonResponse({
                'success': True,
                'stats': {
                    'total_usd': total_usd,
                    'total_fc': total_fc,
                    'total_quantity': total_quantity,
                    'count': ventes.count(),
                    'by_fuel': list(by_fuel),
                    'by_branch': list(by_branch),
                    'by_pompiste': pompiste_stats,
                    'recent': recent_data
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class SalesByPompisteView(AdminRequiredMixin, View):
    """Get sales statistics grouped by pompiste"""
    
    def get(self, request):
        try:
            branche_id = request.GET.get('branche_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Base queryset
            ventes = Vente.objects.filter(statut='validee')
            
            # Filters
            if branche_id and branche_id != 'all':
                ventes = ventes.filter(branche_id=branche_id)
            
            # Period filter
            today = timezone.now().date()
            if period == 'today':
                ventes = ventes.filter(created_at__date=today)
            elif period == 'week':
                week_ago = today - timedelta(days=7)
                ventes = ventes.filter(created_at__date__gte=week_ago)
            elif period == 'month':
                month_ago = today - timedelta(days=30)
                ventes = ventes.filter(created_at__date__gte=month_ago)
            
            # Group by pompiste
            stats = ventes.values(
                'pompiste__id',
                'pompiste__prenom',
                'pompiste__nom',
                'pompiste__branche__nom'
            ).annotate(
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                total_quantity=Sum('quantite'),
                count=Count('id'),
                avg_sale_usd=Avg('montant_usd')
            ).order_by('-total_usd')
            
            # Add manquants for each pompiste
            pompiste_data = []
            for stat in stats:
                pompiste_id = stat['pompiste__id']
                
                # Get manquants count and total
                manquants = Vente.objects.filter(
                    pompiste_id=pompiste_id,
                    statut='manquant'
                )
                
                if period == 'today':
                    manquants = manquants.filter(created_at__date=today)
                elif period == 'week':
                    manquants = manquants.filter(created_at__date__gte=week_ago)
                elif period == 'month':
                    manquants = manquants.filter(created_at__date__gte=month_ago)
                
                manquants_stats = manquants.aggregate(
                    count=Count('id'),
                    total_usd=Sum('manquant_usd'),
                    total_fc=Sum('manquant_fc')
                )
                
                pompiste_data.append({
                    'pompiste_id': pompiste_id,
                    'pompiste': f"{stat['pompiste__prenom']} {stat['pompiste__nom']}",
                    'branche': stat['pompiste__branche__nom'],
                    'total_usd': float(stat['total_usd'] or 0),
                    'total_fc': float(stat['total_fc'] or 0),
                    'total_quantity': float(stat['total_quantity'] or 0),
                    'sales_count': stat['count'],
                    'avg_sale_usd': float(stat['avg_sale_usd'] or 0),
                    'manquants': {
                        'count': manquants_stats['count'] or 0,
                        'total_usd': float(manquants_stats['total_usd'] or 0),
                        'total_fc': float(manquants_stats['total_fc'] or 0)
                    }
                })
            
            return JsonResponse({
                'success': True,
                'pompistes': pompiste_data,
                'count': len(pompiste_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ManquantsReportView(AdminRequiredMixin, View):
    """Get detailed report on manquants (missing amounts)"""
    
    def get(self, request):
        try:
            branche_id = request.GET.get('branche_id', 'all')
            pompiste_id = request.GET.get('pompiste_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Base queryset - only manquants
            manquants = Vente.objects.filter(statut='manquant').select_related(
                'branche', 'pompiste', 'manager', 'caissier', 'type_carburant'
            )
            
            # Filters
            if branche_id and branche_id != 'all':
                manquants = manquants.filter(branche_id=branche_id)
            
            if pompiste_id and pompiste_id != 'all':
                manquants = manquants.filter(pompiste_id=pompiste_id)
            
            # Period filter
            today = timezone.now().date()
            if period == 'today':
                manquants = manquants.filter(created_at__date=today)
            elif period == 'week':
                week_ago = today - timedelta(days=7)
                manquants = manquants.filter(created_at__date__gte=week_ago)
            elif period == 'month':
                month_ago = today - timedelta(days=30)
                manquants = manquants.filter(created_at__date__gte=month_ago)
            
            # Calculate totals
            totals = manquants.aggregate(
                total_manquant_usd=Sum('manquant_usd'),
                total_manquant_fc=Sum('manquant_fc'),
                count=Count('id')
            )
            
            # Detailed list
            manquants_list = []
            for m in manquants.order_by('-created_at')[:50]:
                manquants_list.append({
                    'id': m.id,
                    'date': m.created_at.strftime('%d/%m/%Y %H:%M'),
                    'branche': m.branche.nom,
                    'pompiste': m.pompiste.get_full_name(),
                    'manager': m.manager.get_full_name() if m.manager else 'N/A',
                    'caissier': m.caissier.get_full_name() if m.caissier else 'N/A',
                    'carburant': m.type_carburant.nom,
                    'montant_vente_usd': float(m.montant_usd),
                    'montant_vente_fc': float(m.montant_fc),
                    'manquant_usd': float(m.manquant_usd),
                    'manquant_fc': float(m.manquant_fc),
                    'raison': m.raison_manquant or 'Non spécifié'
                })
            
            return JsonResponse({
                'success': True,
                'totals': {
                    'total_manquant_usd': float(totals['total_manquant_usd'] or 0),
                    'total_manquant_fc': float(totals['total_manquant_fc'] or 0),
                    'count': totals['count']
                },
                'manquants': manquants_list
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ==================== SYSTEM USERS CRUD APIs ====================

class CreateUserView(AdminRequiredMixin, View):
    """Create a new system user (admin, manager, caissier)"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Required fields
            required_fields = ['username', 'email', 'prenom', 'nom', 'role']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Validate role
            if data['role'] not in ['admin', 'manager', 'caissier']:
                return JsonResponse({
                    'success': False,
                    'message': 'Rôle invalide (admin, manager ou caissier)'
                }, status=400)
            
            # Check if username already exists
            if User.objects.filter(username=data['username']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce nom d\'utilisateur existe déjà'
                }, status=400)
            
            # Check if email already exists
            if User.objects.filter(email=data['email']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Cet email existe déjà'
                }, status=400)
            
            # Manager and Caissier must have a branch
            branche = None
            if data['role'] in ['manager', 'caissier']:
                if not data.get('branche_id'):
                    return JsonResponse({
                        'success': False,
                        'message': f'Une branche est requise pour le rôle {data["role"]}'
                    }, status=400)
                
                try:
                    branche = Branche.objects.get(id=data['branche_id'], is_active=True)
                except Branche.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Branche introuvable ou inactive'
                    }, status=400)
            
            # Generate password
            password = data.get('password', 'petrox123')  # Default password
            
            # Validate salary if provided
            salaire = None
            if data.get('salaire'):
                try:
                    salaire = Decimal(str(data['salaire']))
                    if salaire < 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le salaire ne peut pas être négatif'
                        }, status=400)
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Salaire invalide'
                    }, status=400)
            
            # Create user
            user = User.objects.create(
                username=data['username'],
                email=data['email'],
                prenom=data['prenom'],
                nom=data['nom'],
                role=data['role'],
                branche=branche,
                telephone=data.get('telephone', ''),
                date_naissance=data.get('date_naissance'),
                salaire=salaire,
                devise_salaire=data.get('devise_salaire', 'USD'),
                adresse=data.get('adresse', ''),
                password=make_password(password),
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {user.username} créé avec succès',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'full_name': user.get_full_name(),
                    'role': user.role,
                    'branche': branche.nom if branche else None,
                    'default_password': password
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
                'message': f'Erreur: {str(e)}'
            }, status=500)


class UserDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about a user"""
    
    def get(self, request, user_id):
        try:
            user = get_object_or_404(
                User.objects.select_related('branche'),
                id=user_id
            )
            
            # Get user statistics
            if user.role == 'manager':
                sales_count = user.ventes_enregistrees.count()
                validated_sales = user.ventes_enregistrees.filter(statut='validee').count()
            elif user.role == 'caissier':
                sales_count = user.ventes_validees.count()
                validated_sales = sales_count
            else:
                sales_count = 0
                validated_sales = 0
            
            return JsonResponse({
                'success': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'prenom': user.prenom,
                    'nom': user.nom,
                    'full_name': user.get_full_name(),
                    'role': user.role,
                    'role_display': user.get_role_display(),
                    'branche': user.branche.nom if user.branche else None,
                    'branche_id': user.branche.id if user.branche else None,
                    'telephone': user.telephone or '',
                    'date_naissance': user.date_naissance.strftime('%Y-%m-%d') if user.date_naissance else None,
                    'salaire': str(user.salaire) if user.salaire else None,
                    'devise_salaire': user.devise_salaire,
                    'adresse': user.adresse or '',
                    'is_active': user.is_active,
                    'date_joined': user.date_joined.strftime('%d/%m/%Y'),
                    'last_login': user.last_login.strftime('%d/%m/%Y %H:%M') if user.last_login else 'Jamais',
                    'statistics': {
                        'sales_count': sales_count,
                        'validated_sales': validated_sales
                    }
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateUserView(AdminRequiredMixin, View):
    """Update an existing user"""
    
    def put(self, request, user_id):
        try:
            data = json.loads(request.body)
            user = get_object_or_404(User, id=user_id)
            
            # Don't allow changing username to existing one
            if data.get('username') and data['username'] != user.username:
                if User.objects.filter(username=data['username']).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Ce nom d\'utilisateur existe déjà'
                    }, status=400)
                user.username = data['username']
            
            # Don't allow changing email to existing one
            if data.get('email') and data['email'] != user.email:
                if User.objects.filter(email=data['email']).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Cet email existe déjà'
                    }, status=400)
                user.email = data['email']
            
            # Update basic fields
            if data.get('prenom'):
                user.prenom = data['prenom']
            
            if data.get('nom'):
                user.nom = data['nom']
            
            if data.get('telephone'):
                user.telephone = data['telephone']
            
            if data.get('date_naissance'):
                user.date_naissance = data['date_naissance']
            
            if data.get('adresse'):
                user.adresse = data['adresse']
            
            # Update salary
            if 'salaire' in data:
                try:
                    salaire = Decimal(str(data['salaire'])) if data['salaire'] else None
                    if salaire and salaire < 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le salaire ne peut pas être négatif'
                        }, status=400)
                    user.salaire = salaire
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Salaire invalide'
                    }, status=400)
            
            if data.get('devise_salaire') and data['devise_salaire'] in ['USD', 'FC']:
                user.devise_salaire = data['devise_salaire']
            
            # Update branch (only for manager/caissier)
            if user.role in ['manager', 'caissier'] and data.get('branche_id'):
                try:
                    branche = Branche.objects.get(id=data['branche_id'], is_active=True)
                    user.branche = branche
                except Branche.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Branche introuvable'
                    }, status=400)
            
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Utilisateur modifié avec succès',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'full_name': user.get_full_name()
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


class ToggleUserActiveView(AdminRequiredMixin, View):
    """Toggle user active/inactive status"""
    
    def patch(self, request, user_id):
        try:
            user = get_object_or_404(User, id=user_id)
            
            # Don't allow deactivating yourself
            if user.id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'message': 'Vous ne pouvez pas vous désactiver vous-même'
                }, status=400)
            
            # Toggle status
            user.is_active = not user.is_active
            user.save()
            
            status = 'activé' if user.is_active else 'désactivé'
            
            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {status} avec succès',
                'is_active': user.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ResetPasswordView(AdminRequiredMixin, View):
    """Reset user password to default or random"""
    
    def post(self, request, user_id):
        try:
            user = get_object_or_404(User, id=user_id)
            
            # Generate random password or use default
            data = json.loads(request.body) if request.body else {}
            
            if data.get('use_random'):
                # Generate random 12-character password
                chars = string.ascii_letters + string.digits
                new_password = ''.join(random.choice(chars) for _ in range(12))
            else:
                # Use default password
                new_password = 'petrox123'
            
            # Update password
            user.password = make_password(new_password)
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Mot de passe réinitialisé avec succès',
                'new_password': new_password,
                'username': user.username
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ==================== POMPISTES CRUD APIs ====================

class PompistesListAPIView(AdminRequiredMixin, View):
    """Get list of pompistes with filters"""
    
    def get(self, request):
        try:
            branche_id = request.GET.get('branche_id', 'all')
            quart = request.GET.get('quart', 'all')
            
            # Base queryset
            pompistes = Pompiste.objects.select_related('branche')
            
            # Filters
            if branche_id and branche_id != 'all':
                pompistes = pompistes.filter(branche_id=branche_id)
            
            if quart and quart != 'all':
                pompistes = pompistes.filter(quart=quart)
            
            # Build response
            pompistes_data = []
            for pompiste in pompistes.order_by('branche__nom', 'prenom'):
                # Get sales statistics
                sales_count = pompiste.vente_set.count()
                validated_sales = pompiste.vente_set.filter(statut='validee').count()
                manquants_count = pompiste.vente_set.filter(statut='manquant').count()
                
                pompistes_data.append({
                    'id': pompiste.id,
                    'prenom': pompiste.prenom,
                    'nom': pompiste.nom,
                    'full_name': pompiste.get_full_name(),
                    'branche': pompiste.branche.nom,
                    'branche_id': pompiste.branche.id,
                    'telephone': pompiste.telephone or '',
                    'quart': pompiste.quart,
                    'quart_display': pompiste.get_quart_display(),
                    'salaire': float(pompiste.salaire) if pompiste.salaire else 0,
                    'devise_salaire': pompiste.devise_salaire,
                    'is_active': pompiste.is_active,
                    'statistics': {
                        'sales_count': sales_count,
                        'validated_sales': validated_sales,
                        'manquants_count': manquants_count
                    }
                })
            
            return JsonResponse({
                'success': True,
                'pompistes': pompistes_data,
                'count': len(pompistes_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class CreatePompisteView(AdminRequiredMixin, View):
    """Create a new pompiste"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Required fields
            required_fields = ['prenom', 'nom', 'branche_id', 'quart']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Get branch
            try:
                branche = Branche.objects.get(id=data['branche_id'], is_active=True)
            except Branche.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Branche introuvable ou inactive'
                }, status=400)
            
            # Validate quart
            if data['quart'] not in ['jour', 'nuit']:
                return JsonResponse({
                    'success': False,
                    'message': 'Quart invalide (jour ou nuit)'
                }, status=400)
            
            # Validate salary if provided
            salaire = None
            if data.get('salaire'):
                try:
                    salaire = Decimal(str(data['salaire']))
                    if salaire < 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le salaire ne peut pas être négatif'
                        }, status=400)
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Salaire invalide'
                    }, status=400)
            
            # Create pompiste
            pompiste = Pompiste.objects.create(
                prenom=data['prenom'],
                nom=data['nom'],
                branche=branche,
                telephone=data.get('telephone', ''),
                date_naissance=data.get('date_naissance'),
                quart=data['quart'],
                salaire=salaire,
                devise_salaire=data.get('devise_salaire', 'USD'),
                adresse=data.get('adresse', ''),
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Pompiste {pompiste.get_full_name()} créé avec succès',
                'pompiste': {
                    'id': pompiste.id,
                    'full_name': pompiste.get_full_name(),
                    'branche': branche.nom,
                    'quart': pompiste.get_quart_display()
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
                'message': f'Erreur: {str(e)}'
            }, status=500)


class PompisteDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about a pompiste"""
    
    def get(self, request, pompiste_id):
        try:
            pompiste = get_object_or_404(
                Pompiste.objects.select_related('branche'),
                id=pompiste_id
            )
            
            # Get sales statistics
            ventes = pompiste.vente_set.all()
            total_sales = ventes.count()
            validated = ventes.filter(statut='validee').count()
            pending = ventes.filter(statut='en_attente').count()
            manquants = ventes.filter(statut='manquant').count()
            
            # Total amounts
            validated_ventes = ventes.filter(statut='validee')
            total_usd = float(validated_ventes.aggregate(
                Sum('montant_usd'))['montant_usd__sum'] or 0)
            total_fc = float(validated_ventes.aggregate(
                Sum('montant_fc'))['montant_fc__sum'] or 0)
            
            # Manquants totals
            manquants_ventes = ventes.filter(statut='manquant')
            manquant_usd = float(manquants_ventes.aggregate(
                Sum('manquant_usd'))['manquant_usd__sum'] or 0)
            manquant_fc = float(manquants_ventes.aggregate(
                Sum('manquant_fc'))['manquant_fc__sum'] or 0)
            
            return JsonResponse({
                'success': True,
                'pompiste': {
                    'id': pompiste.id,
                    'prenom': pompiste.prenom,
                    'nom': pompiste.nom,
                    'full_name': pompiste.get_full_name(),
                    'branche': pompiste.branche.nom,
                    'branche_id': pompiste.branche.id,
                    'telephone': pompiste.telephone or '',
                    'date_naissance': pompiste.date_naissance.strftime('%Y-%m-%d') if pompiste.date_naissance else None,
                    'quart': pompiste.quart,
                    'quart_display': pompiste.get_quart_display(),
                    'salaire': str(pompiste.salaire) if pompiste.salaire else None,
                    'devise_salaire': pompiste.devise_salaire,
                    'adresse': pompiste.adresse or '',
                    'is_active': pompiste.is_active,
                    'created_at': pompiste.created_at.strftime('%d/%m/%Y'),
                    'statistics': {
                        'total_sales': total_sales,
                        'validated': validated,
                        'pending': pending,
                        'manquants': manquants,
                        'total_usd': total_usd,
                        'total_fc': total_fc,
                        'manquant_usd': manquant_usd,
                        'manquant_fc': manquant_fc
                    }
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdatePompisteView(AdminRequiredMixin, View):
    """Update an existing pompiste"""
    
    def put(self, request, pompiste_id):
        try:
            data = json.loads(request.body)
            pompiste = get_object_or_404(Pompiste, id=pompiste_id)
            
            # Update basic fields
            if data.get('prenom'):
                pompiste.prenom = data['prenom']
            
            if data.get('nom'):
                pompiste.nom = data['nom']
            
            if data.get('telephone'):
                pompiste.telephone = data['telephone']
            
            if data.get('date_naissance'):
                pompiste.date_naissance = data['date_naissance']
            
            if data.get('adresse'):
                pompiste.adresse = data['adresse']
            
            # Update quart
            if data.get('quart') and data['quart'] in ['jour', 'nuit']:
                pompiste.quart = data['quart']
            
            # Update salary
            if 'salaire' in data:
                try:
                    salaire = Decimal(str(data['salaire'])) if data['salaire'] else None
                    if salaire and salaire < 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le salaire ne peut pas être négatif'
                        }, status=400)
                    pompiste.salaire = salaire
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Salaire invalide'
                    }, status=400)
            
            if data.get('devise_salaire') and data['devise_salaire'] in ['USD', 'FC']:
                pompiste.devise_salaire = data['devise_salaire']
            
            # Update branch
            if data.get('branche_id'):
                try:
                    branche = Branche.objects.get(id=data['branche_id'], is_active=True)
                    pompiste.branche = branche
                except Branche.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Branche introuvable'
                    }, status=400)
            
            pompiste.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Pompiste modifié avec succès',
                'pompiste': {
                    'id': pompiste.id,
                    'full_name': pompiste.get_full_name()
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


class TogglePompisteActiveView(AdminRequiredMixin, View):
    """Toggle pompiste active/inactive status"""
    
    def patch(self, request, pompiste_id):
        try:
            pompiste = get_object_or_404(Pompiste, id=pompiste_id)
            
            # Toggle status
            pompiste.is_active = not pompiste.is_active
            pompiste.save()
            
            status = 'activé' if pompiste.is_active else 'désactivé'
            
            return JsonResponse({
                'success': True,
                'message': f'Pompiste {status} avec succès',
                'is_active': pompiste.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class DeletePompisteView(AdminRequiredMixin, View):
    """Delete a pompiste (soft delete if has sales, hard delete otherwise)"""
    
    def delete(self, request, pompiste_id):
        try:
            pompiste = get_object_or_404(Pompiste, id=pompiste_id)
            
            # Check if pompiste has sales
            has_sales = pompiste.vente_set.exists()
            
            pompiste_name = pompiste.get_full_name()
            
            if has_sales:
                # Soft delete - just deactivate
                pompiste.is_active = False
                pompiste.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Pompiste {pompiste_name} désactivé (a des ventes enregistrées)',
                    'type': 'soft_delete'
                })
            else:
                # Hard delete - completely remove
                pompiste.delete()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Pompiste {pompiste_name} supprimé définitivement',
                    'type': 'hard_delete'
                })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ==================== ABONNÉS CRUD APIs ====================

class AbonnesListAPIView(AdminRequiredMixin, View):
    """Get list of abonnés with filters"""
    
    def get(self, request):
        try:
            search = request.GET.get('search', '')
            type_filter = request.GET.get('type', 'all')
            
            # Base queryset
            abonnes = Abonne.objects.all()
            
            # Search filter
            if search:
                abonnes = abonnes.filter(
                    Q(nom_entreprise__icontains=search) |
                    Q(code_client__icontains=search) |
                    Q(contact_nom__icontains=search)
                )
            
            # Type filter
            if type_filter and type_filter != 'all':
                abonnes = abonnes.filter(type_abonnement=type_filter)
            
            # Build response
            abonnes_data = []
            for abonne in abonnes.order_by('nom_entreprise'):
                # Get consumption count
                consumption_count = ConsommationAbonne.objects.filter(abonne=abonne).count()
                
                # Get last consumption
                last_consumption = ConsommationAbonne.objects.filter(
                    abonne=abonne
                ).order_by('-created_at').first()
                
                abonnes_data.append({
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client,
                    'contact_nom': abonne.contact_nom,
                    'contact_telephone': abonne.contact_telephone,
                    'contact_email': abonne.contact_email or '',
                    'adresse': abonne.adresse or '',
                    'type_abonnement': abonne.type_abonnement,
                    'type_abonnement_display': abonne.get_type_abonnement_display(),
                    'solde_usd': float(abonne.solde_usd),
                    'solde_fc': float(abonne.solde_fc),
                    'limite_credit': float(abonne.limite_credit),
                    'is_active': abonne.is_active,
                    'consumption_count': consumption_count,
                    'last_consumption': last_consumption.created_at.strftime('%d/%m/%Y') if last_consumption else None
                })
            
            return JsonResponse({
                'success': True,
                'abonnes': abonnes_data,
                'count': len(abonnes_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class CreateAbonneView(AdminRequiredMixin, View):
    """Create a new abonné"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Required fields
            required_fields = ['nom_entreprise', 'code_client', 'contact_nom', 'contact_telephone', 'type_abonnement']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Check if code_client already exists
            if Abonne.objects.filter(code_client=data['code_client']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce code client existe déjà'
                }, status=400)
            
            # Validate type
            if data['type_abonnement'] not in ['prepaye', 'postpaye', 'credit']:
                return JsonResponse({
                    'success': False,
                    'message': 'Type d\'abonnement invalide'
                }, status=400)
            
            # Validate balances
            solde_usd = Decimal('0.00')
            solde_fc = Decimal('0.00')
            
            if data.get('solde_usd'):
                try:
                    solde_usd = Decimal(str(data['solde_usd']))
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Solde USD invalide'
                    }, status=400)
            
            if data.get('solde_fc'):
                try:
                    solde_fc = Decimal(str(data['solde_fc']))
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Solde FC invalide'
                    }, status=400)
            
            # Validate credit limit for credit type
            limite_credit = Decimal('0.00')
            if data['type_abonnement'] == 'credit':
                if not data.get('limite_credit'):
                    return JsonResponse({
                        'success': False,
                        'message': 'Limite de crédit requise pour type crédit'
                    }, status=400)
                try:
                    limite_credit = Decimal(str(data['limite_credit']))
                    if limite_credit <= 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Limite de crédit doit être > 0'
                        }, status=400)
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Limite de crédit invalide'
                    }, status=400)
            
            # Create abonné
            abonne = Abonne.objects.create(
                nom_entreprise=data['nom_entreprise'],
                code_client=data['code_client'],
                contact_nom=data['contact_nom'],
                contact_telephone=data['contact_telephone'],
                contact_email=data.get('contact_email', ''),
                adresse=data.get('adresse', ''),
                type_abonnement=data['type_abonnement'],
                solde_usd=solde_usd,
                solde_fc=solde_fc,
                limite_credit=limite_credit,
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Abonné {abonne.nom_entreprise} créé avec succès',
                'abonne': {
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client,
                    'type_abonnement_display': abonne.get_type_abonnement_display()
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
                'message': f'Erreur: {str(e)}'
            }, status=500)


class AbonneDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about an abonné"""
    
    def get(self, request, abonne_id):
        try:
            abonne = get_object_or_404(Abonne, id=abonne_id)
            
            # Get consumption statistics
            consumptions = ConsommationAbonne.objects.filter(abonne=abonne)
            total_consumptions = consumptions.count()
            
            # Total consumed amounts
            total_usd = float(consumptions.filter(devise='USD').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            total_fc = float(consumptions.filter(devise='FC').aggregate(
                Sum('montant'))['montant__sum'] or 0)
            
            # By branch
            by_branch = consumptions.values('branche__nom').annotate(
                count=Count('id'),
                total_quantity=Sum('quantite')
            ).order_by('-count')
            
            # Recent consumptions
            recent = consumptions.select_related('branche', 'type_carburant').order_by('-created_at')[:5]
            recent_data = [{
                'date': c.created_at.strftime('%d/%m/%Y %H:%M'),
                'branche': c.branche.nom if c.branche else 'N/A',
                'carburant': c.type_carburant.nom if c.type_carburant else 'N/A',
                'quantite': float(c.quantite),
                'montant': float(c.montant),
                'devise': c.devise
            } for c in recent]
            
            return JsonResponse({
                'success': True,
                'abonne': {
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client,
                    'contact_nom': abonne.contact_nom,
                    'contact_telephone': abonne.contact_telephone,
                    'contact_email': abonne.contact_email or '',
                    'adresse': abonne.adresse or '',
                    'type_abonnement': abonne.type_abonnement,
                    'type_abonnement_display': abonne.get_type_abonnement_display(),
                    'solde_usd': float(abonne.solde_usd),
                    'solde_fc': float(abonne.solde_fc),
                    'limite_credit': float(abonne.limite_credit),
                    'is_active': abonne.is_active,
                    'created_at': abonne.created_at.strftime('%d/%m/%Y'),
                    'statistics': {
                        'total_consumptions': total_consumptions,
                        'total_usd': total_usd,
                        'total_fc': total_fc,
                        'branches_count': by_branch.count(),
                        'by_branch': list(by_branch),
                        'recent': recent_data
                    }
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateAbonneView(AdminRequiredMixin, View):
    """Update an existing abonné"""
    
    def put(self, request, abonne_id):
        try:
            data = json.loads(request.body)
            abonne = get_object_or_404(Abonne, id=abonne_id)
            
            # Don't allow changing code_client to existing one
            if data.get('code_client') and data['code_client'] != abonne.code_client:
                if Abonne.objects.filter(code_client=data['code_client']).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Ce code client existe déjà'
                    }, status=400)
                abonne.code_client = data['code_client']
            
            # Update basic fields
            if data.get('nom_entreprise'):
                abonne.nom_entreprise = data['nom_entreprise']
            
            if data.get('contact_nom'):
                abonne.contact_nom = data['contact_nom']
            
            if data.get('contact_telephone'):
                abonne.contact_telephone = data['contact_telephone']
            
            if 'contact_email' in data:
                abonne.contact_email = data['contact_email']
            
            if 'adresse' in data:
                abonne.adresse = data['adresse']
            
            # Update type (careful - this affects balance logic)
            if data.get('type_abonnement') and data['type_abonnement'] in ['prepaye', 'postpaye', 'credit']:
                abonne.type_abonnement = data['type_abonnement']
            
            # Update credit limit
            if 'limite_credit' in data:
                try:
                    limite = Decimal(str(data['limite_credit']))
                    if limite < 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Limite de crédit ne peut pas être négative'
                        }, status=400)
                    abonne.limite_credit = limite
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Limite de crédit invalide'
                    }, status=400)
            
            abonne.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Abonné modifié avec succès',
                'abonne': {
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client
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


class ToggleAbonneStatusView(AdminRequiredMixin, View):
    """Toggle abonné active/inactive status"""
    
    def patch(self, request, abonne_id):
        try:
            abonne = get_object_or_404(Abonne, id=abonne_id)
            
            # Toggle status
            abonne.is_active = not abonne.is_active
            abonne.save()
            
            status = 'activé' if abonne.is_active else 'désactivé'
            
            return JsonResponse({
                'success': True,
                'message': f'Abonné {status} avec succès',
                'is_active': abonne.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class AbonneGlobalHistoryView(AdminRequiredMixin, View):
    """Get global consumption history across all branches"""
    
    def get(self, request, abonne_id):
        try:
            abonne = get_object_or_404(Abonne, id=abonne_id)
            
            # Get all consumptions
            consumptions = ConsommationAbonne.objects.filter(
                abonne=abonne
            ).select_related('branche', 'type_carburant').order_by('-created_at')
            
            # Summary by branch
            by_branch = consumptions.values('branche__nom').annotate(
                total_quantity=Sum('quantite'),
                total_usd=Sum('montant', filter=Q(devise='USD')),
                total_fc=Sum('montant', filter=Q(devise='FC')),
                count=Count('id')
            ).order_by('-count')
            
            # Detailed consumption list
            consumption_data = []
            for c in consumptions[:100]:  # Limit to 100
                consumption_data.append({
                    'id': c.id,
                    'date': c.created_at.strftime('%d/%m/%Y %H:%M'),
                    'branche': c.branche.nom if c.branche else 'N/A',
                    'carburant': c.type_carburant.nom if c.type_carburant else 'N/A',
                    'quantite': float(c.quantite),
                    'montant': float(c.montant),
                    'devise': c.devise
                })
            
            return JsonResponse({
                'success': True,
                'abonne': {
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client,
                    'type_abonnement_display': abonne.get_type_abonnement_display(),
                    'solde_usd': float(abonne.solde_usd),
                    'solde_fc': float(abonne.solde_fc)
                },
                'summary_by_branch': list(by_branch),
                'consumptions': consumption_data,
                'total_count': consumptions.count()
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class AddPaymentView(AdminRequiredMixin, View):
    """Add payment to abonné balance"""
    
    def post(self, request, abonne_id):
        try:
            data = json.loads(request.body)
            abonne = get_object_or_404(Abonne, id=abonne_id)
            
            # Required fields
            if not data.get('montant') or not data.get('devise'):
                return JsonResponse({
                    'success': False,
                    'message': 'Montant et devise sont requis'
                }, status=400)
            
            # Validate amount
            try:
                montant = Decimal(str(data['montant']))
                if montant <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le montant doit être supérieur à 0'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Montant invalide'
                }, status=400)
            
            # Validate currency
            if data['devise'] not in ['USD', 'FC']:
                return JsonResponse({
                    'success': False,
                    'message': 'Devise invalide (USD ou FC)'
                }, status=400)
            
            # Update balance
            abonne.update_solde_with_consumption(montant, data['devise'], 'paiement')
            
            return JsonResponse({
                'success': True,
                'message': f'Paiement de {montant} {data["devise"]} enregistré',
                'new_balance': {
                    'solde_usd': float(abonne.solde_usd),
                    'solde_fc': float(abonne.solde_fc)
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


class AbonneConsumptionStatsView(AdminRequiredMixin, View):
    """Get detailed consumption statistics for an abonné"""
    
    def get(self, request, abonne_id):
        try:
            abonne = get_object_or_404(Abonne, id=abonne_id)
            
            # Get consumptions
            consumptions = ConsommationAbonne.objects.filter(abonne=abonne)
            
            # By fuel type
            by_fuel = consumptions.values('type_carburant__nom').annotate(
                total_quantity=Sum('quantite'),
                total_usd=Sum('montant', filter=Q(devise='USD')),
                total_fc=Sum('montant', filter=Q(devise='FC')),
                count=Count('id')
            ).order_by('-total_quantity')
            
            # By branch
            by_branch = consumptions.values('branche__nom').annotate(
                total_quantity=Sum('quantite'),
                total_usd=Sum('montant', filter=Q(devise='USD')),
                total_fc=Sum('montant', filter=Q(devise='FC')),
                count=Count('id')
            ).order_by('-total_quantity')
            
            # Monthly trend (last 6 months)
            six_months_ago = timezone.now() - timedelta(days=180)
            monthly = consumptions.filter(created_at__gte=six_months_ago).extra(
                select={'month': 'EXTRACT(month FROM created_at)', 'year': 'EXTRACT(year FROM created_at)'}
            ).values('month', 'year').annotate(
                total_quantity=Sum('quantite'),
                total_usd=Sum('montant', filter=Q(devise='USD')),
                total_fc=Sum('montant', filter=Q(devise='FC')),
                count=Count('id')
            ).order_by('year', 'month')
            
            return JsonResponse({
                'success': True,
                'statistics': {
                    'by_fuel': list(by_fuel),
                    'by_branch': list(by_branch),
                    'monthly_trend': list(monthly),
                    'total_consumptions': consumptions.count()
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class AbonnesByTypeView(AdminRequiredMixin, View):
    """Get abonnés grouped by type with statistics"""
    
    def get(self, request):
        try:
            # Count by type
            stats = {
                'prepaye': {
                    'count': Abonne.objects.filter(type_abonnement='prepaye').count(),
                    'total_solde_usd': float(Abonne.objects.filter(
                        type_abonnement='prepaye'
                    ).aggregate(Sum('solde_usd'))['solde_usd__sum'] or 0),
                    'total_solde_fc': float(Abonne.objects.filter(
                        type_abonnement='prepaye'
                    ).aggregate(Sum('solde_fc'))['solde_fc__sum'] or 0)
                },
                'postpaye': {
                    'count': Abonne.objects.filter(type_abonnement='postpaye').count(),
                    'total_solde_usd': float(Abonne.objects.filter(
                        type_abonnement='postpaye'
                    ).aggregate(Sum('solde_usd'))['solde_usd__sum'] or 0),
                    'total_solde_fc': float(Abonne.objects.filter(
                        type_abonnement='postpaye'
                    ).aggregate(Sum('solde_fc'))['solde_fc__sum'] or 0)
                },
                'credit': {
                    'count': Abonne.objects.filter(type_abonnement='credit').count(),
                    'total_solde_usd': float(Abonne.objects.filter(
                        type_abonnement='credit'
                    ).aggregate(Sum('solde_usd'))['solde_usd__sum'] or 0),
                    'total_solde_fc': float(Abonne.objects.filter(
                        type_abonnement='credit'
                    ).aggregate(Sum('solde_fc'))['solde_fc__sum'] or 0),
                    'total_credit_limit': float(Abonne.objects.filter(
                        type_abonnement='credit'
                    ).aggregate(Sum('limite_credit'))['limite_credit__sum'] or 0)
                }
            }
            
            return JsonResponse({
                'success': True,
                'statistics': stats,
                'total_abonnes': Abonne.objects.count(),
                'active_abonnes': Abonne.objects.filter(is_active=True).count()
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

# ============================================
# VIEW 1: Export Abonnés to PDF
# ============================================

class ExportAbonnesPDFView(AdminRequiredMixin, View):
    """
    Export all abonnés to PDF with professional formatting
    Includes soldes, type, contact info
    """
    
    def get(self, request):
        try:
            # Get filters
            type_filter = request.GET.get('type', 'all')
            search = request.GET.get('search', '')
            
            # Base queryset
            abonnes = Abonne.objects.filter(is_active=True)
            
            # Apply filters
            if type_filter != 'all':
                abonnes = abonnes.filter(type_abonnement=type_filter)
            
            if search:
                abonnes = abonnes.filter(
                    Q(nom_entreprise__icontains=search) |
                    Q(code_client__icontains=search) |
                    Q(contact_nom__icontains=search)
                )
            
            abonnes = abonnes.order_by('nom_entreprise')
            
            if not abonnes.exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun abonné trouvé'
                }, status=404)
            
            # Create PDF
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="abonnes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#DC2626'),
                spaceAfter=30,
                alignment=1
            )
            
            # Title
            elements.append(Paragraph('PETROX - Liste des Abonnés', title_style))
            elements.append(Paragraph(f'Généré le: {timezone.now().strftime("%d/%m/%Y à %H:%M")}', styles['Normal']))
            if type_filter != 'all':
                filter_text = {'prepaye': 'Prépayés', 'postpaye': 'Postpayés', 'credit': 'Crédit'}
                elements.append(Paragraph(f'Type: {filter_text.get(type_filter, "Tous")}', styles['Normal']))
            elements.append(Spacer(1, 0.5*inch))
            
            # Summary
            total_prepaye = abonnes.filter(type_abonnement='prepaye').count()
            total_postpaye = abonnes.filter(type_abonnement='postpaye').count()
            total_credit = abonnes.filter(type_abonnement='credit').count()
            
            total_solde_usd = sum(float(a.solde_usd) for a in abonnes)
            total_solde_fc = sum(float(a.solde_fc) for a in abonnes)
            
            summary_data = [
                ['Métrique', 'Valeur'],
                ['Total Abonnés', str(len(abonnes))],
                ['Prépayés', str(total_prepaye)],
                ['Postpayés', str(total_postpaye)],
                ['Crédit', str(total_credit)],
                ['Solde Total USD', f'${total_solde_usd:.2f}'],
                ['Solde Total FC', f'{total_solde_fc:.0f} FC']
            ]
            
            summary_table = Table(summary_data, colWidths=[2.5*inch, 2*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
            ]))
            
            elements.append(summary_table)
            elements.append(Spacer(1, 0.4*inch))
            
            # Detailed table
            elements.append(Paragraph('Liste Détaillée', styles['Heading2']))
            elements.append(Spacer(1, 0.2*inch))
            
            data = [['Entreprise', 'Code Client', 'Type', 'Contact', 'Téléphone', 'Solde USD', 'Solde FC']]
            
            for abonne in abonnes:
                data.append([
                    abonne.nom_entreprise[:25],
                    abonne.code_client,
                    abonne.get_type_abonnement_display(),
                    abonne.contact_nom[:20],
                    abonne.contact_telephone,
                    f'${float(abonne.solde_usd):.2f}',
                    f'{float(abonne.solde_fc):.0f} FC'
                ])
            
            detail_table = Table(data, colWidths=[2.2*inch, 1*inch, 1*inch, 1.5*inch, 1.2*inch, 1*inch, 1*inch])
            detail_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F2937')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            
            elements.append(detail_table)
            
            # Build PDF
            doc.build(elements)
            pdf = buffer.getvalue()
            buffer.close()
            response.write(pdf)
            
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur export PDF: {str(e)}'
            }, status=500)


# ============================================
# VIEW 2: Export Abonnés to Excel
# ============================================

class ExportAbonnesExcelView(AdminRequiredMixin, View):
    """
    Export abonnés to Excel with formatting
    """
    
    def get(self, request):
        try:
            # Get filters
            type_filter = request.GET.get('type', 'all')
            search = request.GET.get('search', '')
            
            # Base queryset
            abonnes = Abonne.objects.filter(is_active=True)
            
            # Apply filters
            if type_filter != 'all':
                abonnes = abonnes.filter(type_abonnement=type_filter)
            
            if search:
                abonnes = abonnes.filter(
                    Q(nom_entreprise__icontains=search) |
                    Q(code_client__icontains=search) |
                    Q(contact_nom__icontains=search)
                )
            
            abonnes = abonnes.order_by('nom_entreprise')
            
            if not abonnes.exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun abonné trouvé'
                }, status=404)
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Abonnés'
            
            # Header styling
            header_fill = PatternFill(start_color='DC2626', end_color='DC2626', fill_type='solid')
            header_font = Font(bold=True, color='FFFFFF', size=12)
            border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # Headers
            headers = [
                'Entreprise', 'Code Client', 'Type Abonnement', 
                'Contact Nom', 'Contact Téléphone', 'Contact Email',
                'Adresse', 'Solde USD', 'Solde FC', 'Limite Crédit',
                'Statut', 'Date Création'
            ]
            
            for col_num, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_num)
                cell.value = header
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = border
            
            # Data rows
            for row_num, abonne in enumerate(abonnes, 2):
                ws.cell(row=row_num, column=1).value = abonne.nom_entreprise
                ws.cell(row=row_num, column=2).value = abonne.code_client
                ws.cell(row=row_num, column=3).value = abonne.get_type_abonnement_display()
                ws.cell(row=row_num, column=4).value = abonne.contact_nom
                ws.cell(row=row_num, column=5).value = abonne.contact_telephone
                ws.cell(row=row_num, column=6).value = abonne.contact_email
                ws.cell(row=row_num, column=7).value = abonne.adresse
                ws.cell(row=row_num, column=8).value = float(abonne.solde_usd)
                ws.cell(row=row_num, column=9).value = float(abonne.solde_fc)
                ws.cell(row=row_num, column=10).value = float(abonne.limite_credit)
                ws.cell(row=row_num, column=11).value = 'Actif' if abonne.is_active else 'Inactif'
                ws.cell(row=row_num, column=12).value = abonne.created_at.strftime('%d/%m/%Y')
                
                # Apply border
                for col_num in range(1, 13):
                    ws.cell(row=row_num, column=col_num).border = border
                
                # Color code soldes
                solde_usd_cell = ws.cell(row=row_num, column=8)
                solde_fc_cell = ws.cell(row=row_num, column=9)
                
                if float(abonne.solde_usd) < 0:
                    solde_usd_cell.font = Font(color='DC2626', bold=True)
                else:
                    solde_usd_cell.font = Font(color='10B981', bold=True)
                
                if float(abonne.solde_fc) < 0:
                    solde_fc_cell.font = Font(color='DC2626', bold=True)
                else:
                    solde_fc_cell.font = Font(color='10B981', bold=True)
            
            # Adjust column widths
            column_widths = [30, 15, 15, 20, 18, 25, 30, 12, 12, 12, 10, 15]
            for col_num, width in enumerate(column_widths, 1):
                ws.column_dimensions[openpyxl.utils.get_column_letter(col_num)].width = width
            
            # Summary row
            summary_row = len(list(abonnes)) + 3
            ws.cell(row=summary_row, column=1).value = 'TOTAUX'
            ws.cell(row=summary_row, column=1).font = Font(bold=True, size=12)
            
            total_usd = sum(float(a.solde_usd) for a in abonnes)
            total_fc = sum(float(a.solde_fc) for a in abonnes)
            
            ws.cell(row=summary_row, column=8).value = total_usd
            ws.cell(row=summary_row, column=8).font = Font(bold=True, size=12)
            ws.cell(row=summary_row, column=9).value = total_fc
            ws.cell(row=summary_row, column=9).font = Font(bold=True, size=12)
            
            # Save to response
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="abonnes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
            
            wb.save(response)
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur export Excel: {str(e)}'
            }, status=500)


# ============================================
# VIEW 3: Get Payment History for Abonné
# ============================================

class AbonnePaymentHistoryView(AdminRequiredMixin, View):
    """
    Get detailed payment history for an abonné
    Shows all payments made across all branches
    """
    
    def get(self, request, abonne_id):
        try:
            # Get abonné
            try:
                abonne = Abonne.objects.get(id=abonne_id)
            except Abonne.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Abonné introuvable'
                }, status=404)
            
            # Get date range filters
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')
            
            # Get payment records from Depense model
            # Payments are stored as negative amounts in Depense with category "Paiements Abonnés"
            payments_category = CategorieDepense.objects.filter(nom='Paiements Abonnés').first()
            
            if payments_category:
                payments = Depense.objects.filter(
                    categorie=payments_category,
                    description__icontains=abonne.code_client
                ).select_related('branche', 'created_by')
                
                # Apply date filters
                if start_date:
                    try:
                        start = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
                        payments = payments.filter(created_at__date__gte=start)
                    except ValueError:
                        pass
                
                if end_date:
                    try:
                        end = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
                        payments = payments.filter(created_at__date__lte=end)
                    except ValueError:
                        pass
                
                payments = payments.order_by('-created_at')
                
                # Prepare payment data
                payments_data = []
                total_paid_usd = 0
                total_paid_fc = 0
                
                for payment in payments:
                    amount = abs(float(payment.montant))  # Convert from negative
                    
                    if payment.devise == 'USD':
                        total_paid_usd += amount
                    else:
                        total_paid_fc += amount
                    
                    payments_data.append({
                        'id': payment.id,
                        'date': payment.created_at.strftime('%d/%m/%Y'),
                        'time': payment.created_at.strftime('%H:%M'),
                        'branche': payment.branche.nom if payment.branche else 'N/A',
                        'montant': amount,
                        'devise': payment.devise,
                        'methode': payment.methode_paiement if hasattr(payment, 'methode_paiement') else 'N/A',
                        'caissier': payment.created_by.get_full_name() if payment.created_by else 'N/A'
                    })
            else:
                payments_data = []
                total_paid_usd = 0
                total_paid_fc = 0
            
            return JsonResponse({
                'success': True,
                'abonne': {
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client,
                    'solde_actuel_usd': str(abonne.solde_usd),
                    'solde_actuel_fc': str(abonne.solde_fc)
                },
                'payments': payments_data,
                'count': len(payments_data),
                'totals': {
                    'total_paid_usd': total_paid_usd,
                    'total_paid_fc': total_paid_fc
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

# ==================== FUEL TYPES MANAGEMENT ====================

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

class FuelTypesListAPIView(AdminRequiredMixin, View):
    """Get list of all fuel types with stock summary"""
    
    def get(self, request):
        try:
            # Get all fuel types
            fuel_types = TypeCarburant.objects.all().order_by('nom')
            
            fuel_types_data = []
            for fuel in fuel_types:
                # Get total stock across all branches
                stocks = Stock.objects.filter(type_carburant=fuel)
                total_stock = float(stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0)
                total_capacity = float(stocks.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0)
                branches_count = stocks.values('branche').distinct().count()
                
                fuel_types_data.append({
                    'id': fuel.id,
                    'nom': fuel.nom,
                    'couleur_hex': fuel.couleur_hex,
                    'prix_vente_usd': float(fuel.prix_vente_usd),
                    'prix_vente_fc': float(fuel.prix_vente_fc),
                    'is_active': fuel.is_active,
                    'created_at': fuel.created_at.strftime('%d/%m/%Y'),
                    'total_stock': total_stock,
                    'total_capacity': total_capacity,
                    'branches_count': branches_count,
                    'fill_percentage': round((total_stock / total_capacity * 100), 1) if total_capacity > 0 else 0
                })
            
            return JsonResponse({
                'success': True,
                'fuel_types': fuel_types_data,
                'count': len(fuel_types_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class CreateFuelTypeView(AdminRequiredMixin, View):
    """Create a new fuel type"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Required fields
            required_fields = ['nom', 'couleur_hex', 'prix_vente_usd', 'prix_vente_fc']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Check if name already exists
            if TypeCarburant.objects.filter(nom__iexact=data['nom']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce nom de carburant existe déjà'
                }, status=400)
            
            # Generate unique code from name
            base_code = data['nom'][:10].upper().replace(' ', '_')
            code = base_code
            counter = 1
            while TypeCarburant.objects.filter(code=code).exists():
                code = f"{base_code}_{counter}"
                counter += 1
            
            # Validate hex color
            if not re.match(r'^#[0-9A-Fa-f]{6}$', data['couleur_hex']):
                return JsonResponse({
                    'success': False,
                    'message': 'Couleur hexadécimale invalide (format: #RRGGBB)'
                }, status=400)
            
            # Validate prices
            try:
                prix_usd = Decimal(str(data['prix_vente_usd']))
                prix_fc = Decimal(str(data['prix_vente_fc']))
                
                if prix_usd <= 0 or prix_fc <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Les prix doivent être supérieurs à 0'
                    }, status=400)
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Prix invalides'
                }, status=400)
            
            # Create fuel type
            fuel_type = TypeCarburant.objects.create(
                nom=data['nom'].strip(),
                code=code,  # <- ADD THIS LINE
                couleur_hex=data['couleur_hex'].upper(),
                prix_vente_usd=prix_usd,
                prix_vente_fc=prix_fc,
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Type de carburant "{fuel_type.nom}" créé avec succès',
                'fuel_type': {
                    'id': fuel_type.id,
                    'nom': fuel_type.nom,
                    'code': fuel_type.code,
                    'couleur_hex': fuel_type.couleur_hex
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
                'message': f'Erreur: {str(e)}'
            }, status=500)


class FuelTypeDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about a fuel type"""
    
    def get(self, request, fuel_id):
        try:
            fuel = get_object_or_404(TypeCarburant, id=fuel_id)
            
            # Get stock breakdown by branch
            stocks = Stock.objects.filter(type_carburant=fuel).select_related('branche')
            
            by_branch = []
            for stock in stocks:
                by_branch.append({
                    'branche_id': stock.branche.id,
                    'branche_nom': stock.branche.nom,
                    'branche_code': stock.branche.code,
                    'quantite_actuelle': float(stock.quantite_actuelle),
                    'capacite_max': float(stock.capacite_max),
                    'seuil_alerte': float(stock.seuil_alerte),
                    'pourcentage_rempli': round(stock.pourcentage_rempli, 1),
                    'niveau_alerte': stock.niveau_alerte,
                    'prix_achat': float(stock.prix_achat) if stock.prix_achat else None
                })
            
            # Get total sales statistics
            total_sales = Vente.objects.filter(
                type_carburant=fuel,
                statut='validee'
            ).aggregate(
                total_quantity=Sum('quantite'),
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc')
            )
            
            return JsonResponse({
                'success': True,
                'fuel_type': {
                    'id': fuel.id,
                    'nom': fuel.nom,
                    'couleur_hex': fuel.couleur_hex,
                    'prix_vente_usd': float(fuel.prix_vente_usd),
                    'prix_vente_fc': float(fuel.prix_vente_fc),
                    'is_active': fuel.is_active,
                    'created_at': fuel.created_at.strftime('%d/%m/%Y'),
                    'stock_by_branch': by_branch,
                    'total_branches': len(by_branch),
                    'total_stock': sum(s['quantite_actuelle'] for s in by_branch),
                    'sales_stats': {
                        'total_quantity': float(total_sales['total_quantity'] or 0),
                        'total_usd': float(total_sales['total_usd'] or 0),
                        'total_fc': float(total_sales['total_fc'] or 0)
                    }
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateFuelTypeView(AdminRequiredMixin, View):
    """Update an existing fuel type"""
    
    def put(self, request, fuel_id):
        try:
            data = json.loads(request.body)
            fuel = get_object_or_404(TypeCarburant, id=fuel_id)
            
            # Check if name is being changed and if it conflicts
            if data.get('nom') and data['nom'] != fuel.nom:
                if TypeCarburant.objects.filter(nom__iexact=data['nom']).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Ce nom de carburant existe déjà'
                    }, status=400)
                fuel.nom = data['nom'].strip()
            
            # Update color
            if data.get('couleur_hex'):
                if not re.match(r'^#[0-9A-Fa-f]{6}$', data['couleur_hex']):
                    return JsonResponse({
                        'success': False,
                        'message': 'Couleur hexadécimale invalide'
                    }, status=400)
                fuel.couleur_hex = data['couleur_hex'].upper()
            
            # Update prices
            if 'prix_vente_usd' in data:
                try:
                    prix_usd = Decimal(str(data['prix_vente_usd']))
                    if prix_usd <= 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le prix USD doit être supérieur à 0'
                        }, status=400)
                    fuel.prix_vente_usd = prix_usd
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Prix USD invalide'
                    }, status=400)
            
            if 'prix_vente_fc' in data:
                try:
                    prix_fc = Decimal(str(data['prix_vente_fc']))
                    if prix_fc <= 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le prix FC doit être supérieur à 0'
                        }, status=400)
                    fuel.prix_vente_fc = prix_fc
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Prix FC invalide'
                    }, status=400)
            
            fuel.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Type de carburant modifié avec succès',
                'fuel_type': {
                    'id': fuel.id,
                    'nom': fuel.nom,
                    'couleur_hex': fuel.couleur_hex
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


class ToggleFuelTypeStatusView(AdminRequiredMixin, View):
    """Toggle fuel type active/inactive status"""
    
    def patch(self, request, fuel_id):
        try:
            fuel = get_object_or_404(TypeCarburant, id=fuel_id)
            
            # Check if fuel is being used in any sales
            if fuel.is_active:
                sales_count = Vente.objects.filter(type_carburant=fuel).count()
                if sales_count > 0:
                    return JsonResponse({
                        'success': False,
                        'message': f'Impossible de désactiver: {sales_count} vente(s) utilisent ce carburant'
                    }, status=400)
            
            # Toggle status
            fuel.is_active = not fuel.is_active
            fuel.save()
            
            status = 'activé' if fuel.is_active else 'désactivé'
            
            return JsonResponse({
                'success': True,
                'message': f'Type de carburant {status} avec succès',
                'is_active': fuel.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class FuelTypeStatsView(AdminRequiredMixin, View):
    """Get detailed statistics for a fuel type"""
    
    def get(self, request, fuel_id):
        try:
            fuel = get_object_or_404(TypeCarburant, id=fuel_id)
            
            # Total stock
            stocks = Stock.objects.filter(type_carburant=fuel)
            total_stock = float(stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0)
            total_capacity = float(stocks.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0)
            
            # Sales statistics
            sales = Vente.objects.filter(type_carburant=fuel, statut='validee')
            sales_stats = sales.aggregate(
                total_quantity=Sum('quantite'),
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                count=Count('id')
            )
            
            # By branch
            by_branch = sales.values('branche__nom').annotate(
                quantity=Sum('quantite'),
                usd=Sum('montant_usd'),
                fc=Sum('montant_fc'),
                count=Count('id')
            ).order_by('-quantity')
            
            # Last 30 days trend
            thirty_days_ago = timezone.now() - timedelta(days=30)
            daily_sales = sales.filter(created_at__gte=thirty_days_ago).extra(
                select={'day': 'DATE(created_at)'}
            ).values('day').annotate(
                quantity=Sum('quantite'),
                count=Count('id')
            ).order_by('day')
            
            return JsonResponse({
                'success': True,
                'statistics': {
                    'stock': {
                        'total': total_stock,
                        'capacity': total_capacity,
                        'fill_percentage': round((total_stock / total_capacity * 100), 1) if total_capacity > 0 else 0,
                        'branches_count': stocks.count()
                    },
                    'sales': {
                        'total_quantity': float(sales_stats['total_quantity'] or 0),
                        'total_usd': float(sales_stats['total_usd'] or 0),
                        'total_fc': float(sales_stats['total_fc'] or 0),
                        'total_transactions': sales_stats['count'],
                        'by_branch': list(by_branch),
                        'daily_trend': list(daily_sales)
                    }
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ==================== STOCK MANAGEMENT ====================

class CreateStockView(AdminRequiredMixin, View):
    """Create a new stock record"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Required fields
            required_fields = ['branche_id', 'type_carburant_id', 'capacite_max', 'seuil_alerte']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Get branche
            try:
                branche = Branche.objects.get(id=data['branche_id'])
            except Branche.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Branche introuvable'
                }, status=400)
            
            # Get fuel type
            try:
                fuel_type = TypeCarburant.objects.get(id=data['type_carburant_id'])
            except TypeCarburant.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Type de carburant introuvable'
                }, status=400)
            
            # Check if stock already exists
            if Stock.objects.filter(branche=branche, type_carburant=fuel_type).exists():
                return JsonResponse({
                    'success': False,
                    'message': f'Un stock pour {fuel_type.nom} existe déjà à {branche.nom}'
                }, status=400)
            
            # Validate quantities
            try:
                quantite_actuelle = Decimal(str(data.get('quantite_actuelle', 0)))
                capacite_max = Decimal(str(data['capacite_max']))
                seuil_alerte = Decimal(str(data['seuil_alerte']))
                
                if capacite_max <= 0:
                    return JsonResponse({'success': False, 'message': 'La capacité doit être supérieure à 0'}, status=400)
                
                if seuil_alerte < 0:
                    return JsonResponse({'success': False, 'message': 'Le seuil ne peut pas être négatif'}, status=400)
                
                if quantite_actuelle > capacite_max:
                    return JsonResponse({'success': False, 'message': 'Le stock initial ne peut pas dépasser la capacité'}, status=400)
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'message': 'Quantités invalides'}, status=400)
            
            # Validate purchase price
            prix_achat = None
            if data.get('prix_achat'):
                try:
                    prix_achat = Decimal(str(data['prix_achat']))
                    if prix_achat < 0:
                        return JsonResponse({'success': False, 'message': 'Le prix ne peut pas être négatif'}, status=400)
                except (ValueError, TypeError):
                    return JsonResponse({'success': False, 'message': 'Prix invalide'}, status=400)
            
            # Create stock
            stock = Stock.objects.create(
                branche=branche,
                type_carburant=fuel_type,
                quantite_actuelle=quantite_actuelle,
                capacite_max=capacite_max,
                seuil_alerte=seuil_alerte,
                prix_achat=prix_achat
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Stock créé: {fuel_type.nom} à {branche.nom}',
                'stock': {
                    'id': stock.id,
                    'branche': branche.nom,
                    'type_carburant': fuel_type.nom,
                    'quantite_actuelle': float(stock.quantite_actuelle)
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Données JSON invalides'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Erreur: {str(e)}'}, status=500)


class StockListAPIView(AdminRequiredMixin, View):
    """Get list of all stocks with filters"""
    
    def get(self, request):
        try:
            branch_id = request.GET.get('branch_id', 'all')
            fuel_id = request.GET.get('fuel_id', 'all')
            alert_only = request.GET.get('alert_only', 'false').lower() == 'true'
            
            # Base queryset
            stocks = Stock.objects.select_related('branche', 'type_carburant')
            
            # Apply filters
            if branch_id and branch_id != 'all':
                stocks = stocks.filter(branche_id=branch_id)
            
            if fuel_id and fuel_id != 'all':
                stocks = stocks.filter(type_carburant_id=fuel_id)
            
            if alert_only:
                stocks = stocks.filter(quantite_actuelle__lte=F('seuil_alerte'))
            
            # Build response
            stocks_data = []
            for stock in stocks.order_by('branche__nom', 'type_carburant__nom'):
                stocks_data.append({
                    'id': stock.id,
                    'branche': {
                        'id': stock.branche.id,
                        'nom': stock.branche.nom,
                        'code': stock.branche.code
                    },
                    'type_carburant': {
                        'id': stock.type_carburant.id,
                        'nom': stock.type_carburant.nom,
                        'couleur_hex': stock.type_carburant.couleur_hex
                    },
                    'quantite_actuelle': float(stock.quantite_actuelle),
                    'capacite_max': float(stock.capacite_max),
                    'seuil_alerte': float(stock.seuil_alerte),
                    'prix_achat': float(stock.prix_achat) if stock.prix_achat else None,
                    'pourcentage_rempli': round(stock.pourcentage_rempli, 1),
                    'niveau_alerte': stock.niveau_alerte,
                    'updated_at': stock.updated_at.strftime('%d/%m/%Y %H:%M')
                })
            
            return JsonResponse({
                'success': True,
                'stocks': stocks_data,
                'count': len(stocks_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class StockDetailAPIView(AdminRequiredMixin, View):
    """Get detailed information about a stock"""
    
    def get(self, request, stock_id):
        try:
            stock = get_object_or_404(Stock.objects.select_related('branche', 'type_carburant'), id=stock_id)
            
            # Get recent deliveries (if Livraison model exists and is used)
            # This would need to be implemented when Livraison is added
            recent_deliveries = []
            
            # Get recent sales from this stock
            recent_sales = Vente.objects.filter(
                branche=stock.branche,
                type_carburant=stock.type_carburant,
                statut='validee'
            ).select_related('pompiste').order_by('-created_at')[:10]
            
            sales_data = []
            for sale in recent_sales:
                sales_data.append({
                    'id': sale.id,
                    'date': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                    'pompiste': sale.pompiste.get_full_name() if sale.pompiste else 'N/A',
                    'quantite': float(sale.quantite),
                    'montant_usd': float(sale.montant_usd),
                    'montant_fc': float(sale.montant_fc)
                })
            
            return JsonResponse({
                'success': True,
                'stock': {
                    'id': stock.id,
                    'branche': {
                        'id': stock.branche.id,
                        'nom': stock.branche.nom,
                        'code': stock.branche.code
                    },
                    'type_carburant': {
                        'id': stock.type_carburant.id,
                        'nom': stock.type_carburant.nom,
                        'couleur_hex': stock.type_carburant.couleur_hex,
                        'prix_vente_usd': float(stock.type_carburant.prix_vente_usd),
                        'prix_vente_fc': float(stock.type_carburant.prix_vente_fc)
                    },
                    'quantite_actuelle': float(stock.quantite_actuelle),
                    'capacite_max': float(stock.capacite_max),
                    'seuil_alerte': float(stock.seuil_alerte),
                    'prix_achat': float(stock.prix_achat) if stock.prix_achat else None,
                    'pourcentage_rempli': round(stock.pourcentage_rempli, 1),
                    'niveau_alerte': stock.niveau_alerte,
                    'updated_at': stock.updated_at.strftime('%d/%m/%Y %H:%M'),
                    'recent_deliveries': recent_deliveries,
                    'recent_sales': sales_data
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateStockSettingsView(AdminRequiredMixin, View):
    """Update stock settings (capacity, threshold, purchase price)"""
    
    def put(self, request, stock_id):
        try:
            data = json.loads(request.body)
            stock = get_object_or_404(Stock, id=stock_id)
            
            # Update capacity
            if 'capacite_max' in data:
                try:
                    capacite = Decimal(str(data['capacite_max']))
                    if capacite <= 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'La capacité doit être supérieure à 0'
                        }, status=400)
                    stock.capacite_max = capacite
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Capacité invalide'
                    }, status=400)
            
            # Update alert threshold
            if 'seuil_alerte' in data:
                try:
                    seuil = Decimal(str(data['seuil_alerte']))
                    if seuil < 0:
                        return JsonResponse({
                            'success': False,
                            'message': 'Le seuil ne peut pas être négatif'
                        }, status=400)
                    stock.seuil_alerte = seuil
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Seuil invalide'
                    }, status=400)
            
            # Update purchase price
            if 'prix_achat' in data:
                if data['prix_achat']:
                    try:
                        prix = Decimal(str(data['prix_achat']))
                        if prix < 0:
                            return JsonResponse({
                                'success': False,
                                'message': 'Le prix ne peut pas être négatif'
                            }, status=400)
                        stock.prix_achat = prix
                    except (ValueError, TypeError):
                        return JsonResponse({
                            'success': False,
                            'message': 'Prix invalide'
                        }, status=400)
                else:
                    stock.prix_achat = None
            
            stock.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Paramètres de stock mis à jour',
                'stock': {
                    'id': stock.id,
                    'capacite_max': float(stock.capacite_max),
                    'seuil_alerte': float(stock.seuil_alerte),
                    'prix_achat': float(stock.prix_achat) if stock.prix_achat else None
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


class StockHistoryView(AdminRequiredMixin, View):
    """Get stock history (deliveries and consumption)"""
    
    def get(self, request, stock_id):
        try:
            stock = get_object_or_404(Stock.objects.select_related('branche', 'type_carburant'), id=stock_id)
            
            # Get deliveries (when implemented)
            deliveries = []
            # TODO: Add when Livraison model is used
            # deliveries = Livraison.objects.filter(
            #     branche=stock.branche,
            #     type_carburant=stock.type_carburant
            # ).order_by('-created_at')[:50]
            
            # Get consumption (sales)
            sales = Vente.objects.filter(
                branche=stock.branche,
                type_carburant=stock.type_carburant,
                statut='validee'
            ).select_related('pompiste').order_by('-created_at')[:50]
            
            history_data = []
            
            # Add sales as negative movements
            for sale in sales:
                history_data.append({
                    'type': 'sale',
                    'date': sale.created_at.strftime('%d/%m/%Y %H:%M'),
                    'quantity': -float(sale.quantite),  # Negative for consumption
                    'reference': f'Vente #{sale.id}',
                    'actor': sale.pompiste.get_full_name() if sale.pompiste else 'N/A',
                    'notes': f'Vente par {sale.pompiste.get_full_name() if sale.pompiste else "N/A"}'
                })
            
            # Sort by date (most recent first)
            history_data.sort(key=lambda x: x['date'], reverse=True)
            
            return JsonResponse({
                'success': True,
                'stock_info': {
                    'branche': stock.branche.nom,
                    'carburant': stock.type_carburant.nom,
                    'quantite_actuelle': float(stock.quantite_actuelle)
                },
                'history': history_data,
                'total_records': len(history_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class StockAlertsView(AdminRequiredMixin, View):
    """Get all stocks with alerts"""
    
    def get(self, request):
        try:
            # Get stocks at or below alert threshold
            alert_stocks = Stock.objects.filter(
                quantite_actuelle__lte=F('seuil_alerte')
            ).select_related('branche', 'type_carburant').order_by('quantite_actuelle')
            
            critical_stocks = []
            warning_stocks = []
            
            for stock in alert_stocks:
                stock_data = {
                    'id': stock.id,
                    'branche': {
                        'id': stock.branche.id,
                        'nom': stock.branche.nom,
                        'code': stock.branche.code
                    },
                    'type_carburant': {
                        'id': stock.type_carburant.id,
                        'nom': stock.type_carburant.nom,
                        'couleur_hex': stock.type_carburant.couleur_hex
                    },
                    'quantite_actuelle': float(stock.quantite_actuelle),
                    'seuil_alerte': float(stock.seuil_alerte),
                    'capacite_max': float(stock.capacite_max),
                    'pourcentage_rempli': round(stock.pourcentage_rempli, 1),
                    'updated_at': stock.updated_at.strftime('%d/%m/%Y %H:%M')
                }
                
                # Critical if below 50% of threshold
                if stock.quantite_actuelle <= (stock.seuil_alerte * Decimal('0.5')):
                    stock_data['severity'] = 'critical'
                    critical_stocks.append(stock_data)
                else:
                    stock_data['severity'] = 'warning'
                    warning_stocks.append(stock_data)
            
            return JsonResponse({
                'success': True,
                'alerts': {
                    'critical': critical_stocks,
                    'warning': warning_stocks,
                    'total_count': len(critical_stocks) + len(warning_stocks),
                    'critical_count': len(critical_stocks),
                    'warning_count': len(warning_stocks)
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class StockSummaryView(AdminRequiredMixin, View):
    """Get global stock summary and statistics"""
    
    def get(self, request):
        try:
            # All stocks
            all_stocks = Stock.objects.select_related('branche', 'type_carburant')
            
            # Global totals
            totals = all_stocks.aggregate(
                total_stock=Sum('quantite_actuelle'),
                total_capacity=Sum('capacite_max')
            )
            
            total_stock = float(totals['total_stock'] or 0)
            total_capacity = float(totals['total_capacity'] or 0)
            fill_percentage = round((total_stock / total_capacity * 100), 1) if total_capacity > 0 else 0
            
            # Alerts count
            alerts_count = all_stocks.filter(quantite_actuelle__lte=F('seuil_alerte')).count()
            
            # By fuel type
            by_fuel = {}
            fuel_types = TypeCarburant.objects.filter(is_active=True)
            for fuel in fuel_types:
                stocks = all_stocks.filter(type_carburant=fuel)
                fuel_total = float(stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0)
                fuel_capacity = float(stocks.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0)
                
                by_fuel[fuel.nom] = {
                    'id': fuel.id,
                    'couleur_hex': fuel.couleur_hex,
                    'total_stock': fuel_total,
                    'total_capacity': fuel_capacity,
                    'fill_percentage': round((fuel_total / fuel_capacity * 100), 1) if fuel_capacity > 0 else 0,
                    'branches_count': stocks.values('branche').distinct().count()
                }
            
            # By branch
            by_branch = {}
            branches = Branche.objects.filter(is_active=True)
            for branch in branches:
                stocks = all_stocks.filter(branche=branch)
                branch_total = float(stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0)
                branch_capacity = float(stocks.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0)
                branch_alerts = stocks.filter(quantite_actuelle__lte=F('seuil_alerte')).count()
                
                by_branch[branch.nom] = {
                    'id': branch.id,
                    'code': branch.code,
                    'total_stock': branch_total,
                    'total_capacity': branch_capacity,
                    'fill_percentage': round((branch_total / branch_capacity * 100), 1) if branch_capacity > 0 else 0,
                    'fuel_types_count': stocks.values('type_carburant').distinct().count(),
                    'alerts_count': branch_alerts
                }
            
            return JsonResponse({
                'success': True,
                'summary': {
                    'global': {
                        'total_stock': total_stock,
                        'total_capacity': total_capacity,
                        'fill_percentage': fill_percentage,
                        'alerts_count': alerts_count,
                        'branches_count': len(by_branch),
                        'fuel_types_count': len(by_fuel)
                    },
                    'by_fuel_type': by_fuel,
                    'by_branch': by_branch
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# API VIEWS
class UploadDocumentView(AdminRequiredMixin, View):
    """Upload a new document"""
    
    def post(self, request):
        try:
            titre = request.POST.get('titre')
            description = request.POST.get('description', '')
            categorie_id = request.POST.get('categorie_id')
            visibilite = request.POST.get('visibilite', 'public')
            fichier = request.FILES.get('fichier')
            
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
                }, status=400)
            
            # File size limit (10MB)
            if fichier.size > 10 * 1024 * 1024:
                return JsonResponse({
                    'success': False,
                    'message': 'Fichier trop volumineux (max 10MB)'
                }, status=400)
            
            # Allowed extensions
            allowed_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.gif', '.txt']
            file_ext = os.path.splitext(fichier.name)[1].lower()
            
            if file_ext not in allowed_extensions:
                return JsonResponse({
                    'success': False,
                    'message': f'Type de fichier non autorisé. Extensions autorisées: {", ".join(allowed_extensions)}'
                }, status=400)
            
            # Create document
            document = Document.objects.create(
                titre=titre,
                description=description,
                fichier=fichier,
                categorie=categorie,
                visibilite=visibilite,
                uploaded_by=request.user,
                taille_fichier=fichier.size,
                type_fichier=fichier.content_type or 'application/octet-stream'
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Document uploadé avec succès',
                'document': {
                    'id': document.id,
                    'titre': document.titre
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class DownloadDocumentView(AdminRequiredMixin, View):
    """Download a document"""
    
    def get(self, request, document_id):
        try:
            document = Document.objects.get(id=document_id)
            
            # Check permissions
            user = request.user
            can_access = False
            
            if user.role == 'admin':
                can_access = True
            elif document.visibilite == 'public':
                can_access = True
            elif document.uploaded_by == user:
                can_access = True
            elif user.branche in document.branches_autorisees.all():
                can_access = True
            
            if not can_access:
                raise Http404("Document non trouvé")
            
            # Serve file
            if default_storage.exists(document.fichier.name):
                with default_storage.open(document.fichier.name, 'rb') as f:
                    response = HttpResponse(f.read(), content_type=document.type_fichier)
                    response['Content-Disposition'] = f'attachment; filename="{document.titre}{os.path.splitext(document.fichier.name)[1]}"'
                    return response
            else:
                raise Http404("Fichier introuvable")
                
        except Document.DoesNotExist:
            raise Http404("Document non trouvé")
        except Exception as e:
            return HttpResponse(f"Erreur: {str(e)}", status=500)


class DeleteDocumentView(AdminRequiredMixin, View):
    """Delete a document"""
    
    def delete(self, request, document_id):
        try:
            document = Document.objects.get(id=document_id)
            
            # Delete file from storage
            if default_storage.exists(document.fichier.name):
                default_storage.delete(document.fichier.name)
            
            # Delete document record
            document.delete()
            
            return JsonResponse({
                'success': True,
                'message': 'Document supprimé avec succès'
            })
            
        except Document.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Document introuvable'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class CreateDocumentCategoryView(AdminRequiredMixin, View):
    """Create a new document category"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            nom = data.get('nom')
            if not nom:
                return JsonResponse({
                    'success': False,
                    'message': 'Le nom est requis'
                }, status=400)
            
            # Check if category exists
            if DocumentCategory.objects.filter(nom__iexact=nom).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Cette catégorie existe déjà'
                }, status=400)
            
            # Create category
            category = DocumentCategory.objects.create(
                nom=nom,
                description=data.get('description', ''),
                created_by=request.user
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Catégorie créée avec succès',
                'category': {
                    'id': category.id,
                    'nom': category.nom
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
                'message': f'Erreur: {str(e)}'
            }, status=500)


class DocumentsListAPIView(AdminRequiredMixin, View):
    """Get list of documents (API)"""
    
    def get(self, request):
        try:
            # Get filters
            search = request.GET.get('search', '')
            category_id = request.GET.get('category_id', '')
            visibility = request.GET.get('visibility', '')
            
            # Base queryset
            documents = Document.objects.select_related('categorie', 'uploaded_by')
            
            # Apply filters
            if search:
                documents = documents.filter(
                    Q(titre__icontains=search) | Q(description__icontains=search)
                )
            
            if category_id:
                documents = documents.filter(categorie_id=category_id)
            
            if visibility:
                documents = documents.filter(visibilite=visibility)
            
            # Order
            documents = documents.order_by('-created_at')[:100]
            
            # Build response
            documents_data = []
            for doc in documents:
                documents_data.append({
                    'id': doc.id,
                    'titre': doc.titre,
                    'description': doc.description,
                    'categorie': doc.categorie.nom if doc.categorie else 'N/A',
                    'visibilite': doc.get_visibilite_display(),
                    'type_fichier': doc.type_fichier,
                    'uploaded_by': doc.uploaded_by.get_full_name() if doc.uploaded_by else 'N/A',
                    'created_at': doc.created_at.strftime('%d/%m/%Y %H:%M'),
                })
            
            return JsonResponse({
                'success': True,
                'documents': documents_data,
                'count': len(documents_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

class GetDocumentDetailView(AdminRequiredMixin, View):
    """Get document details"""
    
    def get(self, request, document_id):
        try:
            document = Document.objects.get(id=document_id)
            
            return JsonResponse({
                'success': True,
                'document': {
                    'id': document.id,
                    'titre': document.titre,
                    'description': document.description,
                    'categorie_id': document.categorie.id if document.categorie else None,
                    'visibilite': document.visibilite,
                    'type_fichier': document.type_fichier,
                    'uploaded_by': document.uploaded_by.get_full_name() if document.uploaded_by else 'N/A',
                    'created_at': document.created_at.strftime('%d/%m/%Y %H:%M')
                }
            })
            
        except Document.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Document introuvable'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateDocumentView(AdminRequiredMixin, View):
    """Update document metadata (not the file)"""
    
    def put(self, request, document_id):
        try:
            data = json.loads(request.body)
            
            document = Document.objects.get(id=document_id)
            
            # Update fields
            if 'titre' in data:
                document.titre = data['titre']
            
            if 'description' in data:
                document.description = data['description']
            
            if 'categorie_id' in data:
                try:
                    categorie = DocumentCategory.objects.get(id=data['categorie_id'], is_active=True)
                    document.categorie = categorie
                except DocumentCategory.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Catégorie introuvable'
                    }, status=400)
            
            if 'visibilite' in data:
                if data['visibilite'] in ['public', 'prive', 'confidentiel']:
                    document.visibilite = data['visibilite']
            
            document.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Document mis à jour avec succès',
                'document': {
                    'id': document.id,
                    'titre': document.titre
                }
            })
            
        except Document.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Document introuvable'
            }, status=404)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


#=================================================
## DOCUMENT CATEGORY VIEWS
#=================================================

class CategoryListAPIView(AdminRequiredMixin, View):
    """Get list of categories with document counts"""
    
    def get(self, request):
        try:
            categories = DocumentCategory.objects.filter(is_active=True).annotate(
                documents_count=Count('document')
            ).order_by('nom')
            
            categories_data = []
            for cat in categories:
                categories_data.append({
                    'id': cat.id,
                    'nom': cat.nom,
                    'description': cat.description or '',
                    'documents_count': cat.documents_count,
                    'created_at': cat.created_at.strftime('%d/%m/%Y')
                })
            
            return JsonResponse({
                'success': True,
                'categories': categories_data,
                'count': len(categories_data)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class UpdateDocumentCategoryView(AdminRequiredMixin, View):
    """Update a document category"""
    
    def put(self, request, category_id):
        try:
            data = json.loads(request.body)
            
            category = DocumentCategory.objects.get(id=category_id, is_active=True)
            
            # Update fields
            if 'nom' in data:
                # Check if name already exists (excluding current category)
                if DocumentCategory.objects.filter(nom__iexact=data['nom']).exclude(id=category_id).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Cette catégorie existe déjà'
                    }, status=400)
                category.nom = data['nom']
            
            if 'description' in data:
                category.description = data['description']
            
            category.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Catégorie modifiée avec succès',
                'category': {
                    'id': category.id,
                    'nom': category.nom
                }
            })
            
        except DocumentCategory.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Catégorie introuvable'
            }, status=404)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class DeleteDocumentCategoryView(AdminRequiredMixin, View):
    """Delete a document category"""
    
    def delete(self, request, category_id):
        try:
            category = DocumentCategory.objects.get(id=category_id)
            
            # Check if category has documents
            documents_count = Document.objects.filter(categorie=category).count()
            if documents_count > 0:
                return JsonResponse({
                    'success': False,
                    'message': f'Impossible de supprimer: {documents_count} document(s) utilisent cette catégorie'
                }, status=400)
            
            # Soft delete
            category.is_active = False
            category.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Catégorie supprimée avec succès'
            })
            
        except DocumentCategory.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Catégorie introuvable'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)
        


# TEMPLATE VIEW
class RapportsView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Reports page"""
    template_name = 'admin/rapports.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get all branches for filter
        context['branches'] = Branche.objects.filter(is_active=True).order_by('nom')
        
        return context


# REPORT API VIEWS
class FinancialReportAPIView(AdminRequiredMixin, View):
    """Financial report data"""
    
    def get(self, request):
        try:
            # Get parameters
            period = request.GET.get('period', 'month')
            branch_id = request.GET.get('branch_id', 'all')
            currency = request.GET.get('currency', 'both')
            
            # Calculate date range
            today = timezone.now().date()
            start_date, end_date = self._get_date_range(period, request)
            
            # Build filters
            filters = {
                'created_at__date__gte': start_date,
                'created_at__date__lte': end_date,
                'statut': 'validee'
            }
            
            if branch_id != 'all':
                filters['branche_id'] = branch_id
            
            # Get sales
            ventes = Vente.objects.filter(**filters)
            total_sales_usd = float(ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0)
            total_sales_fc = float(ventes.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0)
            
            # Get expenses
            exp_filters = {
                'created_at__date__gte': start_date,
                'created_at__date__lte': end_date,
                'statut': 'approuvee'
            }
            if branch_id != 'all':
                exp_filters['branche_id'] = branch_id
            
            depenses_usd = Depense.objects.filter(**exp_filters, devise='USD')
            depenses_fc = Depense.objects.filter(**exp_filters, devise='FC')
            
            total_expenses_usd = float(depenses_usd.aggregate(Sum('montant'))['montant__sum'] or 0)
            total_expenses_fc = float(depenses_fc.aggregate(Sum('montant'))['montant__sum'] or 0)
            
            # Calculate profit
            profit_usd = total_sales_usd - total_expenses_usd
            profit_fc = total_sales_fc - total_expenses_fc
            
            # Sales by branch
            sales_by_branch = ventes.values('branche__nom').annotate(
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                count=Count('id')
            ).order_by('-total_usd')
            
            return JsonResponse({
                'success': True,
                'period': {
                    'start': start_date.strftime('%d/%m/%Y'),
                    'end': end_date.strftime('%d/%m/%Y')
                },
                'summary': {
                    'Ventes USD': f'${total_sales_usd:,.2f}',
                    'Ventes FC': f'{total_sales_fc:,.2f} FC',
                    'Dépenses USD': f'${total_expenses_usd:,.2f}',
                    'Dépenses FC': f'{total_expenses_fc:,.2f} FC',
                    'Profit USD': f'${profit_usd:,.2f}',
                    'Profit FC': f'{profit_fc:,.2f} FC',
                    'Transactions': ventes.count()
                },
                'sales_by_branch': list(sales_by_branch)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    
    def _get_date_range(self, period, request):
        today = timezone.now().date()
        
        if period == 'today':
            return today, today
        elif period == 'week':
            return today - timedelta(days=7), today
        elif period == 'month':
            return today.replace(day=1), today
        elif period == 'year':
            return today.replace(month=1, day=1), today
        elif period == 'custom':
            start = request.GET.get('start_date')
            end = request.GET.get('end_date')
            if start and end:
                from datetime import datetime
                return datetime.strptime(start, '%Y-%m-%d').date(), datetime.strptime(end, '%Y-%m-%d').date()
        
        return today.replace(day=1), today


class SalesReportAPIView(AdminRequiredMixin, View):
    """Sales report data"""
    
    def get(self, request):
        try:
            period = request.GET.get('period', 'month')
            branch_id = request.GET.get('branch_id', 'all')
            
            today = timezone.now().date()
            start_date, end_date = FinancialReportAPIView()._get_date_range(period, request)
            
            filters = {
                'created_at__date__gte': start_date,
                'created_at__date__lte': end_date,
                'statut': 'validee'
            }
            
            if branch_id != 'all':
                filters['branche_id'] = branch_id
            
            ventes = Vente.objects.filter(**filters)
            
            # By fuel type
            by_fuel = ventes.values('type_carburant__nom').annotate(
                quantity=Sum('quantite'),
                total_usd=Sum('montant_usd'),
                total_fc=Sum('montant_fc'),
                count=Count('id')
            ).order_by('-total_usd')
            
            # By pompiste
            by_pompiste = ventes.values('pompiste__nom', 'pompiste__prenom').annotate(
                total_usd=Sum('montant_usd'),
                count=Count('id')
            ).order_by('-total_usd')[:10]
            
            return JsonResponse({
                'success': True,
                'period': {
                    'start': start_date.strftime('%d/%m/%Y'),
                    'end': end_date.strftime('%d/%m/%Y')
                },
                'summary': {
                    'Total transactions': ventes.count(),
                    'Total USD': f'${float(ventes.aggregate(Sum("montant_usd"))["montant_usd__sum"] or 0):,.2f}',
                    'Total FC': f'{float(ventes.aggregate(Sum("montant_fc"))["montant_fc__sum"] or 0):,.2f} FC',
                    'Quantité totale': f'{float(ventes.aggregate(Sum("quantite"))["quantite__sum"] or 0):,.2f} L'
                },
                'by_fuel': list(by_fuel),
                'by_pompiste': list(by_pompiste)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class PerformanceReportAPIView(AdminRequiredMixin, View):
    """Performance report by branch"""
    
    def get(self, request):
        try:
            period = request.GET.get('period', 'month')
            
            start_date, end_date = FinancialReportAPIView()._get_date_range(period, request)
            
            branches_data = []
            
            for branche in Branche.objects.filter(is_active=True):
                ventes = Vente.objects.filter(
                    branche=branche,
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date,
                    statut='validee'
                )
                
                sales_usd = float(ventes.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0)
                
                depenses = Depense.objects.filter(
                    branche=branche,
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date,
                    statut='approuvee',
                    devise='USD'
                ).aggregate(Sum('montant'))['montant__sum'] or 0
                
                branches_data.append({
                    'branche': branche.nom,
                    'sales_usd': sales_usd,
                    'expenses_usd': float(depenses),
                    'profit_usd': sales_usd - float(depenses),
                    'transactions': ventes.count()
                })
            
            return JsonResponse({
                'success': True,
                'period': {
                    'start': start_date.strftime('%d/%m/%Y'),
                    'end': end_date.strftime('%d/%m/%Y')
                },
                'summary': {
                    'Branches actives': len(branches_data),
                    'Meilleure branche': max(branches_data, key=lambda x: x['profit_usd'])['branche'] if branches_data else 'N/A'
                },
                'branches': branches_data
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ExportPDFReportView(AdminRequiredMixin, View):
    """Export report as PDF"""
    
    def get(self, request, report_type):
        try:
            period = request.GET.get('period', 'month')
            branch_id = request.GET.get('branch_id', 'all')
            
            start_date, end_date = FinancialReportAPIView()._get_date_range(period, request)
            
            # Generate PDF
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            
            styles = getSampleStyleSheet()
            elements = []
            
            # Title
            title = Paragraph(f"RAPPORT {report_type.upper()} - PETROX", styles['Title'])
            elements.append(title)
            elements.append(Spacer(1, 20))
            
            # Period
            period_text = Paragraph(
                f"Période: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
                styles['Normal']
            )
            elements.append(period_text)
            elements.append(Spacer(1, 20))
            
            # Get data based on report type
            if report_type == 'financial':
                self._add_financial_data(elements, styles, start_date, end_date, branch_id)
            elif report_type == 'sales':
                self._add_sales_data(elements, styles, start_date, end_date, branch_id)
            elif report_type == 'performance':
                self._add_performance_data(elements, styles, start_date, end_date)
            
            # Footer
            elements.append(Spacer(1, 30))
            footer = Paragraph(
                f"Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')} par {request.user.get_full_name()}",
                ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, alignment=TA_CENTER)
            )
            elements.append(footer)
            
            doc.build(elements)
            buffer.seek(0)
            
            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="rapport_{report_type}_{start_date}_{end_date}.pdf"'
            return response
            
        except Exception as e:
            return HttpResponse(f"Erreur: {str(e)}", status=500)
    
    def _add_financial_data(self, elements, styles, start_date, end_date, branch_id):
        # Summary table
        data = [['Métrique', 'Valeur']]
        data.append(['Période', f'{start_date} - {end_date}'])
        
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)
    
    def _add_sales_data(self, elements, styles, start_date, end_date, branch_id):
        pass
    
    def _add_performance_data(self, elements, styles, start_date, end_date):
        pass


class ExportExcelReportView(AdminRequiredMixin, View):
    """Export report as Excel"""
    
    def get(self, request, report_type):
        try:
            period = request.GET.get('period', 'month')
            branch_id = request.GET.get('branch_id', 'all')
            
            start_date, end_date = FinancialReportAPIView()._get_date_range(period, request)
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = f"Rapport {report_type}"
            
            # Header
            ws['A1'] = f"RAPPORT {report_type.upper()} - PETROX"
            ws['A1'].font = Font(bold=True, size=14)
            
            ws['A2'] = f"Période: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"
            
            # Add data based on report type
            if report_type == 'financial':
                self._add_excel_financial_data(ws, start_date, end_date, branch_id)
            
            # Save to buffer
            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            
            response = HttpResponse(
                buffer,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="rapport_{report_type}_{start_date}_{end_date}.xlsx"'
            return response
            
        except Exception as e:
            return HttpResponse(f"Erreur: {str(e)}", status=500)
    
    def _add_excel_financial_data(self, ws, start_date, end_date, branch_id):
        ws['A4'] = "Métrique"
        ws['B4'] = "Valeur"
        
        ws['A4'].font = Font(bold=True)
        ws['B4'].font = Font(bold=True)


class ExpensesReportAPIView(AdminRequiredMixin, View):
    """Expenses report data"""
    
    def get(self, request):
        try:
            period = request.GET.get('period', 'month')
            branch_id = request.GET.get('branch_id', 'all')
            
            start_date, end_date = FinancialReportAPIView()._get_date_range(period, request)
            
            filters = {
                'created_at__date__gte': start_date,
                'created_at__date__lte': end_date,
                'statut': 'approuvee'
            }
            
            if branch_id != 'all':
                filters['branche_id'] = branch_id
            
            depenses = Depense.objects.filter(**filters)
            
            # By category
            by_category = depenses.values('categorie__nom').annotate(
                total_usd=Sum(Case(When(devise='USD', then='montant'), default=0, output_field=DecimalField())),
                total_fc=Sum(Case(When(devise='FC', then='montant'), default=0, output_field=DecimalField())),
                count=Count('id')
            ).order_by('-total_usd')
            
            # By branch
            by_branch = depenses.values('branche__nom').annotate(
                total=Sum('montant'),
                count=Count('id')
            ).order_by('-total')
            
            total_usd = float(depenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0)
            total_fc = float(depenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0)
            
            return JsonResponse({
                'success': True,
                'period': {
                    'start': start_date.strftime('%d/%m/%Y'),
                    'end': end_date.strftime('%d/%m/%Y')
                },
                'summary': {
                    'Total dépenses USD': f'${total_usd:,.2f}',
                    'Total dépenses FC': f'{total_fc:,.2f} FC',
                    'Total transactions': depenses.count(),
                    'Nombre catégories': by_category.count()
                },
                'by_category': list(by_category),
                'by_branch': list(by_branch)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class ForexImpactReportAPIView(AdminRequiredMixin, View):
    """Forex impact report data"""
    
    def get(self, request):
        try:
            period = request.GET.get('period', 'month')
            branch_id = request.GET.get('branch_id', 'all')
            
            start_date, end_date = FinancialReportAPIView()._get_date_range(period, request)
            
            # Get current rate
            current_rate_obj = TauxChange.objects.filter(is_active=True).first()
            current_rate = current_rate_obj.taux_usd_fc if current_rate_obj else Decimal('2800.00')
            
            filters = {
                'created_at__date__gte': start_date,
                'created_at__date__lte': end_date,
                'statut': 'validee'
            }
            
            if branch_id != 'all':
                filters['branche_id'] = branch_id
            
            ventes = Vente.objects.filter(**filters)
            
            # Calculate forex impact
            total_impact = Decimal('0')
            gains = Decimal('0')
            losses = Decimal('0')
            
            for vente in ventes:
                if vente.taux_change and vente.taux_change != current_rate:
                    expected_fc = vente.montant_usd * current_rate
                    actual_fc = vente.montant_fc
                    fc_difference = actual_fc - expected_fc
                    usd_impact = fc_difference / current_rate if current_rate > 0 else Decimal('0')
                    
                    total_impact += usd_impact
                    if usd_impact > 0:
                        gains += usd_impact
                    else:
                        losses += abs(usd_impact)
            
            return JsonResponse({
                'success': True,
                'period': {
                    'start': start_date.strftime('%d/%m/%Y'),
                    'end': end_date.strftime('%d/%m/%Y')
                },
                'summary': {
                    'Impact total USD': f'${float(total_impact):,.2f}',
                    'Gains USD': f'${float(gains):,.2f}',
                    'Pertes USD': f'${float(losses):,.2f}',
                    'Taux actuel': f'{float(current_rate):,.2f} FC',
                    'Transactions analysées': ventes.count()
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class StockReportAPIView(AdminRequiredMixin, View):
    """Stock report data"""
    
    def get(self, request):
        try:
            branch_id = request.GET.get('branch_id', 'all')
            
            filters = {}
            if branch_id != 'all':
                filters['branche_id'] = branch_id
            
            stocks = Stock.objects.filter(**filters).select_related('branche', 'type_carburant')
            
            # By fuel type
            by_fuel = stocks.values('type_carburant__nom').annotate(
                total_quantity=Sum('quantite_actuelle'),
                total_capacity=Sum('capacite_max'),
                branches_count=Count('branche', distinct=True)
            ).order_by('-total_quantity')
            
            # Alerts
            alerts = stocks.filter(quantite_actuelle__lte=F('seuil_alerte'))
            critical = alerts.filter(quantite_actuelle__lte=F('seuil_alerte') / 2)
            
            total_stock = float(stocks.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0)
            total_capacity = float(stocks.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0)
            fill_percentage = round((total_stock / total_capacity * 100), 1) if total_capacity > 0 else 0
            
            return JsonResponse({
                'success': True,
                'summary': {
                    'Stock total': f'{total_stock:,.2f} L',
                    'Capacité totale': f'{total_capacity:,.2f} L',
                    'Taux de remplissage': f'{fill_percentage}%',
                    'Alertes': alerts.count(),
                    'Alertes critiques': critical.count()
                },
                'by_fuel': list(by_fuel)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# API VIEWS
class PaymentDetailAPIView(AdminRequiredMixin, View):
    """Get payment details - FIXED to handle both pompiste and employe_user"""
    
    def get(self, request, payment_id):
        try:
            payment = PaiementSalaire.objects.select_related(
                'pompiste', 'employe_user', 'branche', 'caissier'
            ).get(id=payment_id)
            
            # FIXED: Check both pompiste and employe_user
            if payment.pompiste:
                employee_name = payment.pompiste.get_full_name()
            elif payment.employe_user:
                employee_name = payment.employe_user.get_full_name()
            else:
                employee_name = 'N/A'
            
            # FIXED: Check caissier (who paid)
            if payment.caissier:
                paid_by = payment.caissier.get_full_name()
            else:
                paid_by = 'N/A'
            
            return JsonResponse({
                'success': True,
                'payment': {
                    'id': payment.id,
                    'employee_name': employee_name,
                    'branche': payment.branche.nom if payment.branche else 'N/A',
                    'periode': payment.mois_paiement.strftime('%m/%Y') if payment.mois_paiement else 'N/A',
                    'montant': str(payment.montant_paye),
                    'devise': payment.devise_paiement,
                    'methode_paiement': payment.methode_paiement or 'N/A',
                    'taux_change': str(payment.taux_change) if payment.taux_change else None,
                    'paid_by': paid_by,
                    'date_paiement': payment.date_paiement.strftime('%d/%m/%Y %H:%M'),
                    'notes': payment.notes or ''
                }
            })
            
        except PaiementSalaire.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Paiement introuvable'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class SalaryHistoryAPIView(AdminRequiredMixin, View):
    """Get salary payment history - FIXED to properly return employee names"""
    
    def get(self, request):
        try:
            branche_id = request.GET.get('branche_id')
            employee_id = request.GET.get('employee_id')
            period = request.GET.get('period', 'month')
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'month':
                start_date = today.replace(day=1)
            elif period == 'year':
                start_date = today.replace(month=1, day=1)
            else:
                start_date = today - timedelta(days=365)
            
            # Build filters
            filters = {
                'date_paiement__date__gte': start_date,
                'statut': 'paye'  # FIXED: Only show paid salaries
            }
            
            if branche_id and branche_id != 'all':
                filters['branche_id'] = branche_id
            
            if employee_id:
                # This would need employee_type to properly filter
                filters['pompiste_id'] = employee_id
            
            # Get payments with related objects
            payments = PaiementSalaire.objects.filter(**filters).select_related(
                'pompiste', 'employe_user', 'branche', 'caissier'
            ).order_by('-date_paiement')
            
            # Format data - FIXED to handle both pompiste and employe_user
            payments_data = []
            for payment in payments:
                # FIXED: Check both pompiste and employe_user
                if payment.pompiste:
                    employee = payment.pompiste.get_full_name()
                elif payment.employe_user:
                    employee = payment.employe_user.get_full_name()
                else:
                    employee = 'N/A'
                
                # FIXED: Check who paid (caissier)
                if payment.caissier:
                    paid_by = payment.caissier.get_full_name()
                else:
                    paid_by = 'N/A'
                
                payments_data.append({
                    'id': payment.id,
                    'employee': employee,
                    'branche': payment.branche.nom if payment.branche else 'N/A',
                    'periode': payment.mois_paiement.strftime('%m/%Y') if payment.mois_paiement else 'N/A',
                    'montant': str(payment.montant_paye),
                    'devise': payment.devise_paiement,
                    'paid_by': paid_by,
                    'date': payment.date_paiement.strftime('%d/%m/%Y %H:%M')
                })
            
            return JsonResponse({
                'success': True,
                'payments': payments_data,
                'count': len(payments_data)
            })
            
        except Exception as e:
            print(f"Error in SalaryHistoryAPIView: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class EmployeeSalaryReportAPIView(AdminRequiredMixin, View):
    """Get salary report by employee"""
    
    def get(self, request):
        try:
            period = request.GET.get('period', 'year')
            branche_id = request.GET.get('branche_id')
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'year':
                start_date = today.replace(month=1, day=1)
            else:
                start_date = today - timedelta(days=365)
            
            # Get all pompistes
            pompistes = Pompiste.objects.filter(is_active=True)
            
            if branche_id:
                pompistes = pompistes.filter(branche_id=branche_id)
            
            # Build report
            report_data = []
            
            for pompiste in pompistes:
                payments = PaiementSalaire.objects.filter(
                    pompiste=pompiste,
                    date_paiement__date__gte=start_date
                )
                
                total_paid_usd = float(payments.filter(devise_paiement='USD').aggregate(
                    Sum('montant_paye'))['montant_paye__sum'] or 0)
                total_paid_fc = float(payments.filter(devise_paiement='FC').aggregate(
                    Sum('montant_paye'))['montant_paye__sum'] or 0)
                
                report_data.append({
                    'employee': pompiste.get_full_name(),
                    'branche': pompiste.branche.nom if pompiste.branche else 'N/A',
                    'salary': f'{float(pompiste.salaire)} {pompiste.devise_salaire}',
                    'payments_count': payments.count(),
                    'total_paid_usd': total_paid_usd,
                    'total_paid_fc': total_paid_fc
                })
            
            return JsonResponse({
                'success': True,
                'period': {
                    'start': start_date.strftime('%d/%m/%Y'),
                    'end': today.strftime('%d/%m/%Y')
                },
                'employees': report_data
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

# TEMPLATE VIEW
class NotificationsView(AdminRequiredMixin, AdminContextMixin, TemplateView):
    """Notifications page"""
    template_name = 'admin/notifications.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Generate/update notifications
        self._generate_notifications()
        
        # Get all notifications
        notifications = self._build_notifications_list()
        
        context['notifications'] = notifications
        context['all_notifications_count'] = len(notifications)
        context['unread_count'] = sum(1 for n in notifications if not n['is_read'])
        
        # Count by type
        context['stock_alerts_count'] = sum(1 for n in notifications if n['type'] == 'stock')
        context['missing_sales_count'] = sum(1 for n in notifications if n['type'] == 'missing')
        context['category_requests_count'] = sum(1 for n in notifications if n['type'] == 'category')
        
        return context
    
    def _generate_notifications(self):
        """Generate notifications based on current system state"""
        notifications = []
        
        # 1. Stock Alerts
        low_stock = Stock.objects.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).select_related('branche', 'type_carburant')
        
        for stock in low_stock:
            percentage = (stock.quantite_actuelle / stock.capacite_max * 100) if stock.capacite_max > 0 else 0
            
            notifications.append({
                'type': 'stock',
                'title': f'Stock bas: {stock.type_carburant.nom}',
                'message': f'{stock.branche.nom} - Niveau: {percentage:.1f}% ({stock.quantite_actuelle}L / {stock.capacite_max}L)',
                'branche': stock.branche.nom,
                'action_url': '/dashboard/carburants/',
                'severity': 'critical' if percentage < 25 else 'warning'
            })
        
        # 2. Missing Sales (Manquants)
        missing_sales = Vente.objects.filter(
            statut='manquant',
            created_at__date__gte=timezone.now().date() - timedelta(days=7)
        ).select_related('branche', 'pompiste')
        
        for sale in missing_sales:
            total_missing = float(sale.manquant_usd or 0)
            
            notifications.append({
                'type': 'missing',
                'title': f'Manquant signalé',
                'message': f'{sale.branche.nom} - Pompiste: {sale.pompiste.get_full_name()} - Montant: ${total_missing:.2f}',
                'branche': sale.branche.nom,
                'action_url': f'/dashboard/ventes/?statut=manquant',
                'severity': 'warning'
            })
        
        # 3. Category Requests (from Caissiers/Managers)
        # This would need a CategoryRequest model - for now, placeholder
        # category_requests = CategoryRequest.objects.filter(statut='pending')
        
        return notifications
    
    def _build_notifications_list(self):
        """Build complete notifications list from various sources"""
        notifications = []
        
        # Stock alerts
        low_stock = Stock.objects.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).select_related('branche', 'type_carburant')
        
        for stock in low_stock:
            percentage = (stock.quantite_actuelle / stock.capacite_max * 100) if stock.capacite_max > 0 else 0
            
            notifications.append({
                'id': f'stock_{stock.id}',
                'type': 'stock',
                'title': f'Stock bas: {stock.type_carburant.nom}',
                'message': f'Niveau actuel: {percentage:.1f}% ({stock.quantite_actuelle}L / {stock.capacite_max}L)',
                'branche': stock.branche.nom,
                'action_url': '/dashboard/carburants/',
                'created_at': stock.updated_at,
                'is_read': False
            })
        
        # Missing sales
        missing_sales = Vente.objects.filter(
            statut='manquant',
            created_at__date__gte=timezone.now().date() - timedelta(days=7)
        ).select_related('branche', 'pompiste')
        
        for sale in missing_sales:
            total_missing = float(sale.manquant_usd or 0) + (float(sale.manquant_fc or 0) / 2800)
            
            notifications.append({
                'id': f'missing_{sale.id}',
                'type': 'missing',
                'title': f'Manquant - Vente #{sale.id}',
                'message': f'Pompiste: {sale.pompiste.get_full_name()} - Montant: ${total_missing:.2f} USD',
                'branche': sale.branche.nom,
                'action_url': f'/dashboard/ventes/?statut=manquant',
                'created_at': sale.created_at,
                'is_read': False
            })
        
        # Sort by date (newest first)
        notifications.sort(key=lambda x: x['created_at'], reverse=True)
        
        return notifications


# API VIEWS
class MarkNotificationReadView(AdminRequiredMixin, View):
    """Mark notification as read"""
    
    def post(self, request, notification_id):
        # In a full implementation, this would update a Notification model
        # For now, just return success
        return JsonResponse({
            'success': True,
            'message': 'Notification marquée comme lue'
        })


class MarkAllNotificationsReadView(AdminRequiredMixin, View):
    """Mark all notifications as read"""
    
    def post(self, request):
        # In a full implementation, this would update all Notification records
        return JsonResponse({
            'success': True,
            'message': 'Toutes les notifications marquées comme lues'
        })


class NotificationsAPIView(AdminRequiredMixin, View):
    """Get notifications via API"""
    
    def get(self, request):
        notification_type = request.GET.get('type', 'all')
        
        notifications = []
        
        # Stock alerts
        if notification_type in ['all', 'stock']:
            low_stock = Stock.objects.filter(
                quantite_actuelle__lte=F('seuil_alerte')
            ).select_related('branche', 'type_carburant')
            
            for stock in low_stock:
                percentage = (stock.quantite_actuelle / stock.capacite_max * 100) if stock.capacite_max > 0 else 0
                
                notifications.append({
                    'type': 'stock',
                    'title': f'Stock bas: {stock.type_carburant.nom}',
                    'message': f'{stock.branche.nom} - {percentage:.1f}%',
                    'severity': 'critical' if percentage < 25 else 'warning',
                    'timestamp': stock.updated_at.isoformat()
                })
        
        # Missing sales
        if notification_type in ['all', 'missing']:
            missing_sales = Vente.objects.filter(
                statut='manquant',
                created_at__date__gte=timezone.now().date() - timedelta(days=7)
            ).select_related('branche', 'pompiste')
            
            for sale in missing_sales:
                notifications.append({
                    'type': 'missing',
                    'title': 'Manquant signalé',
                    'message': f'Vente #{sale.id} - {sale.branche.nom}',
                    'severity': 'warning',
                    'timestamp': sale.created_at.isoformat()
                })
        
        return JsonResponse({
            'success': True,
            'notifications': notifications,
            'count': len(notifications)
        })


class NotificationCountAPIView(AdminRequiredMixin, View):
    """Get notification counts for badge"""
    
    def get(self, request):
        # Stock alerts
        stock_count = Stock.objects.filter(
            quantite_actuelle__lte=F('seuil_alerte')
        ).count()
        
        # Missing sales (last 7 days)
        missing_count = Vente.objects.filter(
            statut='manquant',
            created_at__date__gte=timezone.now().date() - timedelta(days=7)
        ).count()
        
        total_unread = stock_count + missing_count
        
        return JsonResponse({
            'success': True,
            'counts': {
                'stock': stock_count,
                'missing': missing_count,
                'total': total_unread
            }
        })


class CreatePaymentMethodView(AdminRequiredMixin, View):
    """Create a new payment method"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            nom = data.get('nom')
            code = data.get('code')
            
            if not nom or not code:
                return JsonResponse({
                    'success': False,
                    'message': 'Le nom et le code sont requis'
                }, status=400)
            
            # Check if already exists
            if MoyenPaiement.objects.filter(code=code).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce code existe déjà'
                }, status=400)
            
            # Create payment method
            payment_method = MoyenPaiement.objects.create(
                nom=nom,
                code=code,
                is_active=True
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Moyen de paiement créé avec succès',
                'payment_method': {
                    'id': payment_method.id,
                    'nom': payment_method.nom,
                    'code': payment_method.code
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
                'message': f'Erreur: {str(e)}'
            }, status=500)


class ToggleExpenseCategoryStatusView(AdminRequiredMixin, View):
    """Toggle expense category active status"""
    
    def post(self, request, category_id):
        try:
            category = CategorieDepense.objects.get(id=category_id)
            
            # Toggle status
            category.is_active = not category.is_active
            category.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Catégorie {"activée" if category.is_active else "désactivée"}',
                'is_active': category.is_active
            })
            
        except CategorieDepense.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Catégorie introuvable'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)
        

class ExportDashboardPDFView(AdminRequiredMixin, View):
    """Export dashboard statistics as PDF"""
    
    def get(self, request):
        try:
            # Get filters
            branche_id = request.GET.get('branche_id', 'all')
            period = request.GET.get('period', 'month')
            devise = request.GET.get('devise', 'USD')
            
            # Get data
            stats_data = self._get_dashboard_stats(request, branche_id, period, devise)
            
            # Create PDF
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
            
            # Container for the 'Flowable' objects
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#DC2626'),
                spaceAfter=30,
                alignment=TA_CENTER
            )
            
            # Title
            title = Paragraph("RAPPORT DASHBOARD PETROX", title_style)
            elements.append(title)
            elements.append(Spacer(1, 12))
            
            # Report Info
            report_info = [
                ['Période:', period.upper()],
                ['Devise:', devise],
                ['Branche:', self._get_branch_name(branche_id)],
                ['Date:', timezone.now().strftime('%d/%m/%Y %H:%M')],
            ]
            
            info_table = Table(report_info, colWidths=[2*inch, 4*inch])
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.grey),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            elements.append(info_table)
            elements.append(Spacer(1, 20))
            
            # KPIs Summary
            symbol = '$' if devise == 'USD' else 'FC'
            kpi_data = [
                ['KPI', 'Valeur', 'Tendance'],
                ['Ventes Totales', f'{symbol} {stats_data["total_sales"]:,.2f}', f'{stats_data.get("sales_trend", 0):+.1f}%'],
                ['Dépenses Totales', f'{symbol} {stats_data["total_expenses"]:,.2f}', f'{stats_data.get("expenses_trend", 0):+.1f}%'],
                ['Profit Net', f'{symbol} {stats_data["net_profit"]:,.2f}', f'{stats_data.get("profit_margin", 0):.1f}%'],
                ['Impact Forex', f'$ {stats_data.get("forex_impact", 0):,.2f}', ''],
            ]
            
            kpi_table = Table(kpi_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
            kpi_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('ALIGN', (2, 0), (2, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            elements.append(kpi_table)
            elements.append(Spacer(1, 20))
            
            # Ventes par carburant
            if stats_data.get('sales_by_fuel'):
                elements.append(Paragraph("Ventes par Type de Carburant", styles['Heading2']))
                elements.append(Spacer(1, 12))
                
                fuel_data = [['Carburant', 'Quantité (L)', f'Montant ({symbol})']]
                for fuel in stats_data['sales_by_fuel']:
                    fuel_data.append([
                        fuel['fuel_type'],
                        f"{fuel['quantity']:,.0f}",
                        f"{fuel['amount']:,.2f}"
                    ])
                
                fuel_table = Table(fuel_data, colWidths=[2.5*inch, 1.5*inch, 2*inch])
                fuel_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                ]))
                elements.append(fuel_table)
                elements.append(Spacer(1, 20))
            
            # Footer
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.grey,
                alignment=TA_CENTER
            )
            footer = Paragraph(
                f"Document généré par PETROX System - {timezone.now().strftime('%d/%m/%Y à %H:%M')}",
                footer_style
            )
            elements.append(Spacer(1, 30))
            elements.append(footer)
            
            # Build PDF
            doc.build(elements)
            
            # Get PDF from buffer
            pdf = buffer.getvalue()
            buffer.close()
            
            # Return response
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="dashboard_petrox_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            response.write(pdf)
            
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de la génération du PDF: {str(e)}'
            }, status=500)
    
    def _get_dashboard_stats(self, request, branche_id, period, devise):
        """Get dashboard statistics (reuse from DashboardStatsAPIView)"""
        # Filter by branch
        ventes = Vente.objects.filter(statut='validee')
        depenses = Depense.objects.all()
        
        if branche_id != 'all':
            try:
                branche = Branche.objects.get(id=branche_id)
                ventes = ventes.filter(branche=branche)
                depenses = depenses.filter(branche=branche)
            except Branche.DoesNotExist:
                pass
        
        # Filter by period
        now = timezone.now()
        if period == 'day':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = now - timedelta(days=now.weekday())
        elif period == 'month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        ventes = ventes.filter(created_at__gte=start_date)
        depenses = depenses.filter(created_at__gte=start_date)
        
        # Calculate stats
        if devise == 'USD':
            total_sales = ventes.aggregate(total=Sum('montant_usd'))['total'] or Decimal('0')
            total_expenses = depenses.filter(devise='USD').aggregate(total=Sum('montant'))['total'] or Decimal('0')
        else:
            total_sales = ventes.aggregate(total=Sum('montant_fc'))['total'] or Decimal('0')
            total_expenses = depenses.filter(devise='FC').aggregate(total=Sum('montant'))['total'] or Decimal('0')
        
        net_profit = total_sales - total_expenses
        profit_margin = (net_profit / total_sales * 100) if total_sales > 0 else Decimal('0')
        
        # Sales by fuel type
        sales_by_fuel = []
        fuel_types = TypeCarburant.objects.filter(is_active=True)
        for fuel in fuel_types:
            fuel_ventes = ventes.filter(type_carburant=fuel)
            quantity = fuel_ventes.aggregate(total=Sum('quantite'))['total'] or Decimal('0')
            if devise == 'USD':
                amount = fuel_ventes.aggregate(total=Sum('montant_usd'))['total'] or Decimal('0')
            else:
                amount = fuel_ventes.aggregate(total=Sum('montant_fc'))['total'] or Decimal('0')
            
            if quantity > 0:
                sales_by_fuel.append({
                    'fuel_type': fuel.nom,
                    'quantity': float(quantity),
                    'amount': float(amount)
                })
        
        # Forex impact
        forex_impact = ventes.aggregate(
            total=Sum(F('montant_usd') * (F('taux_change') - F('taux_change')))
        )['total'] or Decimal('0')
        
        return {
            'total_sales': float(total_sales),
            'total_expenses': float(total_expenses),
            'net_profit': float(net_profit),
            'profit_margin': float(profit_margin),
            'forex_impact': float(forex_impact),
            'sales_by_fuel': sales_by_fuel,
            'sales_trend': 0,  # Calculate from previous period if needed
            'expenses_trend': 0,
        }
    
    def _get_branch_name(self, branche_id):
        """Get branch name"""
        if branche_id == 'all':
            return 'Toutes les branches'
        try:
            branche = Branche.objects.get(id=branche_id)
            return branche.nom
        except Branche.DoesNotExist:
            return 'Inconnue'


class ExportDashboardExcelView(AdminRequiredMixin, View):
    """Export dashboard statistics as Excel"""
    
    def get(self, request):
        try:
            # Get filters
            branche_id = request.GET.get('branche_id', 'all')
            period = request.GET.get('period', 'month')
            devise = request.GET.get('devise', 'USD')
            
            # Get data
            stats_data = self._get_dashboard_stats(request, branche_id, period, devise)
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Dashboard"
            
            # Header styling
            header_fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True, size=14)
            center_align = Alignment(horizontal="center", vertical="center")
            right_align = Alignment(horizontal="right", vertical="center")
            
            # Title
            ws.merge_cells('A1:E1')
            ws['A1'] = 'RAPPORT DASHBOARD PETROX'
            ws['A1'].font = Font(bold=True, size=16, color="DC2626")
            ws['A1'].alignment = center_align
            
            # Report info
            ws['A3'] = 'Période:'
            ws['B3'] = period.upper()
            ws['A4'] = 'Devise:'
            ws['B4'] = devise
            ws['A5'] = 'Branche:'
            ws['B5'] = self._get_branch_name(branche_id)
            ws['A6'] = 'Date génération:'
            ws['B6'] = timezone.now().strftime('%d/%m/%Y %H:%M')
            
            # Style report info
            for row in range(3, 7):
                ws[f'A{row}'].font = Font(bold=True)
            
            # KPIs Header
            ws['A8'] = 'INDICATEURS CLÉS'
            ws.merge_cells('A8:D8')
            ws['A8'].font = Font(bold=True, size=12, color="DC2626")
            ws['A8'].alignment = center_align
            
            # KPI Headers
            headers = ['KPI', f'Valeur ({devise})', 'Tendance', '% Marge']
            for col, header in enumerate(headers, start=1):
                cell = ws.cell(row=9, column=col)
                cell.value = header
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = center_align
            
            # KPI Data
            symbol = '$' if devise == 'USD' else 'FC'
            kpi_data = [
                ['Ventes Totales', stats_data['total_sales'], f"{stats_data.get('sales_trend', 0):+.1f}%", ''],
                ['Dépenses Totales', stats_data['total_expenses'], f"{stats_data.get('expenses_trend', 0):+.1f}%", ''],
                ['Profit Net', stats_data['net_profit'], '', f"{stats_data.get('profit_margin', 0):.1f}%"],
                ['Impact Forex', stats_data.get('forex_impact', 0), '', ''],
            ]
            
            row_num = 10
            for kpi_row in kpi_data:
                ws.cell(row=row_num, column=1).value = kpi_row[0]
                ws.cell(row=row_num, column=1).font = Font(bold=True)
                
                ws.cell(row=row_num, column=2).value = kpi_row[1]
                ws.cell(row=row_num, column=2).number_format = '#,##0.00'
                ws.cell(row=row_num, column=2).alignment = right_align
                
                ws.cell(row=row_num, column=3).value = kpi_row[2]
                ws.cell(row=row_num, column=3).alignment = center_align
                
                ws.cell(row=row_num, column=4).value = kpi_row[3]
                ws.cell(row=row_num, column=4).alignment = center_align
                
                row_num += 1
            
            # Ventes par carburant
            if stats_data.get('sales_by_fuel'):
                row_num += 2
                ws[f'A{row_num}'] = 'VENTES PAR TYPE DE CARBURANT'
                ws.merge_cells(f'A{row_num}:D{row_num}')
                ws[f'A{row_num}'].font = Font(bold=True, size=12, color="DC2626")
                ws[f'A{row_num}'].alignment = center_align
                
                row_num += 1
                fuel_headers = ['Carburant', 'Quantité (L)', f'Montant ({symbol})', '% du Total']
                for col, header in enumerate(fuel_headers, start=1):
                    cell = ws.cell(row=row_num, column=col)
                    cell.value = header
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = center_align
                
                row_num += 1
                total_amount = sum(f['amount'] for f in stats_data['sales_by_fuel'])
                
                for fuel in stats_data['sales_by_fuel']:
                    ws.cell(row=row_num, column=1).value = fuel['fuel_type']
                    ws.cell(row=row_num, column=2).value = fuel['quantity']
                    ws.cell(row=row_num, column=2).number_format = '#,##0'
                    ws.cell(row=row_num, column=2).alignment = right_align
                    
                    ws.cell(row=row_num, column=3).value = fuel['amount']
                    ws.cell(row=row_num, column=3).number_format = '#,##0.00'
                    ws.cell(row=row_num, column=3).alignment = right_align
                    
                    percentage = (fuel['amount'] / total_amount * 100) if total_amount > 0 else 0
                    ws.cell(row=row_num, column=4).value = percentage / 100
                    ws.cell(row=row_num, column=4).number_format = '0.0%'
                    ws.cell(row=row_num, column=4).alignment = center_align
                    
                    row_num += 1
            
            # Adjust column widths
            ws.column_dimensions['A'].width = 25
            ws.column_dimensions['B'].width = 18
            ws.column_dimensions['C'].width = 15
            ws.column_dimensions['D'].width = 15
            
            # Add borders
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            for row in ws.iter_rows(min_row=9, max_row=row_num-1, min_col=1, max_col=4):
                for cell in row:
                    cell.border = thin_border
            
            # Save to buffer
            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            
            # Return response
            response = HttpResponse(
                buffer.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="dashboard_petrox_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
            
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de la génération du fichier Excel: {str(e)}'
            }, status=500)
    
    def _get_dashboard_stats(self, request, branche_id, period, devise):
        """Same as PDF export"""
        # Reuse the same logic from ExportDashboardPDFView
        return ExportDashboardPDFView()._get_dashboard_stats(request, branche_id, period, devise)
    
    def _get_branch_name(self, branche_id):
        """Same as PDF export"""
        return ExportDashboardPDFView()._get_branch_name(branche_id)
    

# ============================================
# NEW VIEW 1: Bulk Export PDF (Selected Sales)
# ============================================

class BulkExportSalesPDFView(AdminRequiredMixin, View):
    """
    Export selected sales to PDF
    Allows selection of specific sales for export
    """
    
    def get(self, request):
        try:
            # Get selected IDs
            ids_param = request.GET.get('ids', '')
            if not ids_param:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucune vente sélectionnée'
                }, status=400)
            
            sale_ids = [int(id.strip()) for id in ids_param.split(',') if id.strip()]
            
            # Get sales
            ventes = Vente.objects.filter(
                id__in=sale_ids
            ).select_related(
                'branche', 'pompiste', 'manager', 'caissier',
                'type_carburant', 'moyen_paiement'
            ).order_by('-created_at')
            
            if not ventes.exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Aucune vente trouvée'
                }, status=404)
            
            # Create PDF
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="ventes_selection_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#DC2626'),
                spaceAfter=30,
                alignment=1  # Center
            )
            
            # Title
            elements.append(Paragraph('PETROX - Rapport de Ventes', title_style))
            elements.append(Paragraph(f'Sélection de {len(ventes)} vente(s)', styles['Normal']))
            elements.append(Paragraph(f'Généré le: {timezone.now().strftime("%d/%m/%Y à %H:%M")}', styles['Normal']))
            elements.append(Spacer(1, 0.5*inch))
            
            # Table data
            data = [['Date', 'Branche', 'Pompiste', 'Carburant', 'Qté (L)', 'Montant USD', 'Statut']]
            
            for vente in ventes:
                data.append([
                    vente.created_at.strftime('%d/%m/%Y %H:%M'),
                    vente.branche.nom,
                    f"{vente.pompiste.prenom} {vente.pompiste.nom}",
                    vente.type_carburant.nom,
                    f"{float(vente.quantite):.2f}",
                    f"${float(vente.montant_usd):.2f}",
                    vente.get_statut_display()
                ])
            
            # Create table
            table = Table(data, colWidths=[1.2*inch, 1.2*inch, 1.2*inch, 1*inch, 0.8*inch, 1*inch, 0.8*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            
            elements.append(table)
            
            # Summary
            elements.append(Spacer(1, 0.5*inch))
            total_usd = sum(float(v.montant_usd) for v in ventes)
            total_fc = sum(float(v.montant_fc) for v in ventes)
            
            summary_data = [
                ['Total USD:', f'${total_usd:.2f}'],
                ['Total FC:', f'{total_fc:.0f} FC'],
                ['Nombre de ventes:', str(len(ventes))]
            ]
            
            summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            
            elements.append(summary_table)
            
            # Build PDF
            doc.build(elements)
            pdf = buffer.getvalue()
            buffer.close()
            response.write(pdf)
            
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'export PDF: {str(e)}'
            }, status=500)


# ============================================
# NEW VIEW 2: Bulk Export Excel (Selected Sales)
# ============================================

class BulkExportSalesExcelView(AdminRequiredMixin, View):
    """Export selected sales to Excel"""
    
    def get(self, request):
        try:
            # Get selected IDs
            ids = request.GET.get('ids', '')
            if not ids:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucune vente sélectionnée'
                }, status=400)
            
            id_list = [int(x) for x in ids.split(',') if x.strip()]
            
            # Get sales
            ventes = Vente.objects.filter(id__in=id_list).select_related(
                'branche', 'pompiste', 'manager', 'caissier',
                'type_carburant', 'moyen_paiement', 'abonne'
            ).order_by('-created_at')
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Ventes"
            
            # Header styling
            header_fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            # Headers
            headers = [
                'N°', 'Date', 'Heure', 'Branche', 'Pompiste', 
                'Carburant', 'Quantité (L)', 'Prix Unit. USD', 
                'Montant USD', 'Montant FC', 'Taux', 
                'Moyen Paiement', 'Statut', 'Validé par'
            ]
            
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
            
            # Data rows
            for idx, vente in enumerate(ventes, 2):
                # FIXED: Use prix_vente_usd instead of prix_unitaire_usd
                prix_unit = float(vente.type_carburant.prix_vente_usd) if vente.type_carburant and vente.type_carburant.prix_vente_usd else 0
                
                ws.cell(row=idx, column=1, value=vente.id)
                ws.cell(row=idx, column=2, value=vente.created_at.strftime('%d/%m/%Y'))
                ws.cell(row=idx, column=3, value=vente.created_at.strftime('%H:%M'))
                ws.cell(row=idx, column=4, value=vente.branche.nom if vente.branche else 'N/A')
                ws.cell(row=idx, column=5, value=f"{vente.pompiste.prenom} {vente.pompiste.nom}" if vente.pompiste else 'N/A')
                ws.cell(row=idx, column=6, value=vente.type_carburant.nom if vente.type_carburant else 'N/A')
                ws.cell(row=idx, column=7, value=float(vente.quantite))
                ws.cell(row=idx, column=8, value=prix_unit)
                ws.cell(row=idx, column=9, value=float(vente.montant_usd))
                ws.cell(row=idx, column=10, value=float(vente.montant_fc))
                ws.cell(row=idx, column=11, value=float(vente.taux_change))
                ws.cell(row=idx, column=12, value=vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A')
                ws.cell(row=idx, column=13, value=vente.get_statut_display())
                ws.cell(row=idx, column=14, value=f"{vente.caissier.prenom} {vente.caissier.nom}" if vente.caissier else 'N/A')
            
            # Adjust column widths
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column].width = adjusted_width
            
            # Save to response
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="ventes_selection_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
            wb.save(response)
            
            return response
            
        except Exception as e:
            import traceback
            print(f"Error in BulkExportSalesExcelView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'export Excel: {str(e)}'
            }, status=500)
        
class ExportSalesExcelView(AdminRequiredMixin, View):
    """Export all filtered sales to Excel"""
    
    def get(self, request):
        try:
            # Get filter parameters
            branche_id = request.GET.get('branche_id')
            period = request.GET.get('period')
            status = request.GET.get('status')
            carburant_id = request.GET.get('carburant_id')
            
            # Build queryset
            ventes = Vente.objects.select_related(
                'branche', 'pompiste', 'manager', 'caissier',
                'type_carburant', 'moyen_paiement', 'abonne'
            )
            
            # Apply filters
            if branche_id and branche_id != 'all':
                ventes = ventes.filter(branche_id=branche_id)
            
            if status and status != 'all':
                ventes = ventes.filter(statut=status)
            
            if carburant_id and carburant_id != 'all':
                ventes = ventes.filter(type_carburant_id=carburant_id)
            
            if period and period != 'all':
                from datetime import datetime, timedelta
                today = timezone.now()
                
                if period == 'today':
                    start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
                    ventes = ventes.filter(created_at__gte=start_date)
                elif period == 'week':
                    start_date = today - timedelta(days=7)
                    ventes = ventes.filter(created_at__gte=start_date)
                elif period == 'month':
                    start_date = today - timedelta(days=30)
                    ventes = ventes.filter(created_at__gte=start_date)
            
            ventes = ventes.order_by('-created_at')
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Ventes"
            
            # Header styling
            header_fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            # Headers
            headers = [
                'N°', 'Date', 'Heure', 'Branche', 'Pompiste', 
                'Carburant', 'Quantité (L)', 'Prix Unit. USD', 
                'Montant USD', 'Montant FC', 'Taux', 
                'Moyen Paiement', 'Statut', 'Validé par'
            ]
            
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
            
            # Data rows
            for idx, vente in enumerate(ventes, 2):
                # FIXED: Use prix_vente_usd instead of prix_unitaire_usd
                prix_unit = float(vente.type_carburant.prix_vente_usd) if vente.type_carburant and vente.type_carburant.prix_vente_usd else 0
                
                ws.cell(row=idx, column=1, value=vente.id)
                ws.cell(row=idx, column=2, value=vente.created_at.strftime('%d/%m/%Y'))
                ws.cell(row=idx, column=3, value=vente.created_at.strftime('%H:%M'))
                ws.cell(row=idx, column=4, value=vente.branche.nom if vente.branche else 'N/A')
                ws.cell(row=idx, column=5, value=f"{vente.pompiste.prenom} {vente.pompiste.nom}" if vente.pompiste else 'N/A')
                ws.cell(row=idx, column=6, value=vente.type_carburant.nom if vente.type_carburant else 'N/A')
                ws.cell(row=idx, column=7, value=float(vente.quantite))
                ws.cell(row=idx, column=8, value=prix_unit)
                ws.cell(row=idx, column=9, value=float(vente.montant_usd))
                ws.cell(row=idx, column=10, value=float(vente.montant_fc))
                ws.cell(row=idx, column=11, value=float(vente.taux_change))
                ws.cell(row=idx, column=12, value=vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A')
                ws.cell(row=idx, column=13, value=vente.get_statut_display())
                ws.cell(row=idx, column=14, value=f"{vente.caissier.prenom} {vente.caissier.nom}" if vente.caissier else 'N/A')
            
            # Adjust column widths
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column].width = adjusted_width
            
            # Save to response
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="ventes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
            wb.save(response)
            
            return response
            
        except Exception as e:
            import traceback
            print(f"Error in ExportSalesExcelView: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'export Excel: {str(e)}'
            }, status=500)


# ============================================
# NEW VIEW 3: Print Single Sale Receipt
# ============================================

class PrintSaleReceiptView(AdminRequiredMixin, View):
    """
    Generate printable receipt for a single sale
    Returns HTML that can be printed
    """
    
    def get(self, request, vente_id):
        try:
            vente = get_object_or_404(
                Vente.objects.select_related(
                    'branche', 'pompiste', 'manager', 'caissier',
                    'type_carburant', 'moyen_paiement', 'abonne'
                ),
                id=vente_id
            )
            
            # Get abonne name correctly
            abonne_name = vente.abonne.nom_entreprise if vente.abonne else None
            
            # CORRECT: Use prix_vente_usd (not prix_unitaire_usd)
            prix_unitaire = float(vente.type_carburant.prix_vente_usd) if vente.type_carburant and vente.type_carburant.prix_vente_usd else 0
            
            # Generate HTML receipt
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Reçu de Vente - {vente.id}</title>
                <style>
                    @media print {{
                        @page {{ margin: 0.5cm; }}
                        body {{ margin: 0; padding: 20px; }}
                    }}
                    body {{
                        font-family: 'Arial', sans-serif;
                        max-width: 80mm;
                        margin: 0 auto;
                        padding: 10px;
                    }}
                    .header {{
                        text-align: center;
                        border-bottom: 2px solid #DC2626;
                        padding-bottom: 10px;
                        margin-bottom: 15px;
                    }}
                    .logo {{
                        font-size: 24px;
                        font-weight: bold;
                        color: #DC2626;
                        margin-bottom: 5px;
                    }}
                    .branch {{
                        font-size: 14px;
                        color: #555;
                    }}
                    .section {{
                        margin-bottom: 15px;
                    }}
                    .label {{
                        font-size: 11px;
                        color: #666;
                        margin-bottom: 2px;
                    }}
                    .value {{
                        font-size: 13px;
                        font-weight: bold;
                        margin-bottom: 8px;
                    }}
                    .amount {{
                        text-align: center;
                        border: 2px solid #DC2626;
                        padding: 15px;
                        margin: 15px 0;
                    }}
                    .amount-label {{
                        font-size: 12px;
                        color: #666;
                        margin-bottom: 5px;
                    }}
                    .amount-value {{
                        font-size: 24px;
                        font-weight: bold;
                        color: #DC2626;
                    }}
                    .footer {{
                        text-align: center;
                        font-size: 10px;
                        color: #999;
                        border-top: 1px solid #ddd;
                        padding-top: 10px;
                        margin-top: 15px;
                    }}
                    .status {{
                        display: inline-block;
                        padding: 4px 8px;
                        border-radius: 4px;
                        font-size: 11px;
                        font-weight: bold;
                    }}
                    .status-validee {{ background-color: #10B981; color: white; }}
                    .status-en_attente {{ background-color: #F59E0B; color: white; }}
                    .status-manquant {{ background-color: #EF4444; color: white; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <div class="logo">PETROX</div>
                    <div class="branch">{vente.branche.nom}</div>
                    <div style="font-size: 10px; color: #999;">
                        {vente.branche.adresse if hasattr(vente.branche, 'adresse') and vente.branche.adresse else ''}<br>
                        {vente.branche.ville if hasattr(vente.branche, 'ville') and vente.branche.ville else ''}{', ' + vente.branche.province if hasattr(vente.branche, 'province') and vente.branche.province else ''}
                    </div>
                </div>
                
                <div class="section">
                    <div class="label">Numéro de Transaction</div>
                    <div class="value">VTE-{vente.id:06d}</div>
                    
                    <div class="label">Date et Heure</div>
                    <div class="value">{vente.created_at.strftime('%d/%m/%Y à %H:%M')}</div>
                    
                    <div class="label">Pompiste</div>
                    <div class="value">{vente.pompiste.prenom} {vente.pompiste.nom}</div>
                    
                    {f'<div class="label">Client Abonné</div><div class="value">{abonne_name}</div>' if abonne_name else ''}
                </div>
                
                <div class="section">
                    <div class="label">Type de Carburant</div>
                    <div class="value">{vente.type_carburant.nom}</div>
                    
                    <div class="label">Quantité</div>
                    <div class="value">{float(vente.quantite):.2f} Litres</div>
                    
                    <div class="label">Prix Unitaire</div>
                    <div class="value">${prix_unitaire:.2f} / L</div>
                    
                    <div class="label">Moyen de Paiement</div>
                    <div class="value">{vente.moyen_paiement.nom if vente.moyen_paiement else 'N/A'}</div>
                </div>
                
                <div class="amount">
                    <div class="amount-label">MONTANT TOTAL</div>
                    <div class="amount-value">${float(vente.montant_usd):.2f}</div>
                    <div style="font-size: 14px; color: #666; margin-top: 5px;">
                        {float(vente.montant_fc):.0f} FC
                    </div>
                    <div style="font-size: 10px; color: #999; margin-top: 5px;">
                        Taux: {float(vente.taux_change):.2f} FC
                    </div>
                </div>
                
                <div class="section">
                    <div class="label">Statut</div>
                    <div class="status status-{vente.statut}">{vente.get_statut_display()}</div>
                </div>
                
                {f'''
                <div class="section" style="background-color: #FEE2E2; padding: 10px; border-radius: 4px;">
                    <div class="label" style="color: #DC2626;">MANQUANT SIGNALÉ</div>
                    <div class="value" style="color: #DC2626;">
                        ${float(vente.manquant_usd):.2f} / {float(vente.manquant_fc):.0f} FC
                    </div>
                    {f'<div style="font-size: 10px; color: #991B1B;">{vente.raison_manquant}</div>' if hasattr(vente, 'raison_manquant') and vente.raison_manquant else ''}
                </div>
                ''' if vente.statut == 'manquant' else ''}
                
                <div class="footer">
                    <div>Merci de votre visite!</div>
                    <div>PETROX - Gestion de Stations</div>
                    <div>Imprimé le {timezone.now().strftime('%d/%m/%Y à %H:%M')}</div>
                </div>
                
                <script>
                    window.onload = function() {{
                        window.print();
                    }};
                </script>
            </body>
            </html>
            """
            
            return HttpResponse(html_content, content_type='text/html')
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error in PrintSaleReceiptView: {error_trace}")
            return HttpResponse(
                f'''<html><body style="font-family: Arial; padding: 20px;">
                <h3 style="color: #DC2626;">Erreur lors de l'impression</h3>
                <p><strong>Message:</strong> {str(e)}</p>
                <details>
                    <summary>Détails techniques</summary>
                    <pre style="background: #f5f5f5; padding: 10px; overflow: auto;">{error_trace}</pre>
                </details>
                </body></html>''', 
                status=500
            )


# ============================================
# NEW VIEW 4: Bulk Print Selected Sales
# ============================================

class BulkPrintSalesView(AdminRequiredMixin, View):
    """
    Print multiple sales receipts in one document
    """
    
    def get(self, request):
        try:
            # Get selected IDs
            ids_param = request.GET.get('ids', '')
            if not ids_param:
                return HttpResponse('<html><body><h3>Aucune vente sélectionnée</h3></body></html>')
            
            sale_ids = [int(id.strip()) for id in ids_param.split(',') if id.strip()]
            
            # Get sales
            ventes = Vente.objects.filter(
                id__in=sale_ids
            ).select_related(
                'branche', 'pompiste', 'manager', 'type_carburant', 'moyen_paiement', 'abonne'
            ).order_by('-created_at')
            
            if not ventes.exists():
                return HttpResponse('<html><body><h3>Aucune vente trouvée</h3></body></html>')
            
            # Generate combined HTML
            receipts_html = ''
            for idx, vente in enumerate(ventes):
                page_break = 'page-break-after: always;' if idx < len(ventes) - 1 else ''
                receipts_html += f'''
                <div style="{page_break}">
                    <!-- Receipt content similar to single receipt -->
                    <div style="border: 2px solid #DC2626; padding: 20px; margin-bottom: 20px;">
                        <h2 style="text-align: center; color: #DC2626;">PETROX</h2>
                        <p style="text-align: center;">{vente.branche.nom}</p>
                        <hr>
                        <p><strong>Transaction:</strong> VTE-{vente.id:06d}</p>
                        <p><strong>Date:</strong> {vente.created_at.strftime('%d/%m/%Y %H:%M')}</p>
                        <p><strong>Pompiste:</strong> {vente.pompiste.prenom} {vente.pompiste.nom}</p>
                        <p><strong>Carburant:</strong> {vente.type_carburant.nom}</p>
                        <p><strong>Quantité:</strong> {float(vente.quantite):.2f} L</p>
                        <h3 style="text-align: center; color: #DC2626;">TOTAL: ${float(vente.montant_usd):.2f}</h3>
                        <p style="text-align: center;">{float(vente.montant_fc):.0f} FC</p>
                    </div>
                </div>
                '''
            
            html_content = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Reçus de Ventes - Impression Multiple</title>
                <style>
                    @media print {{
                        @page {{ margin: 1cm; }}
                    }}
                    body {{ font-family: Arial, sans-serif; }}
                </style>
            </head>
            <body>
                {receipts_html}
                <script>
                    window.onload = function() {{ window.print(); }};
                </script>
            </body>
            </html>
            '''
            
            return HttpResponse(html_content, content_type='text/html')
            
        except Exception as e:
            return HttpResponse(f'<html><body><h3>Erreur: {str(e)}</h3></body></html>')

# ============================================
# NEW VIEW 1: Manquants Report with Analysis
# ============================================

class ManquantsReportAPIView(AdminRequiredMixin, View):
    """
    Complete manquants report with totals, analysis, and charts data
    This is the MAIN API endpoint for the manquants validation page
    """
    
    def get(self, request):
        try:
            # Get filter parameters
            branche_id = request.GET.get('branche_id', 'all')
            pompiste_id = request.GET.get('pompiste_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Base queryset - only manquants
            manquants = Vente.objects.filter(statut='manquant').select_related(
                'branche', 'pompiste', 'manager', 'caissier', 'type_carburant', 'moyen_paiement'
            )
            
            # Apply filters
            if branche_id and branche_id != 'all':
                manquants = manquants.filter(branche_id=branche_id)
            
            if pompiste_id and pompiste_id != 'all':
                manquants = manquants.filter(pompiste_id=pompiste_id)
            
            # Period filter
            today = timezone.now().date()
            if period == 'week':
                start_date = today - timedelta(days=7)
                manquants = manquants.filter(created_at__date__gte=start_date)
            elif period == 'month':
                start_date = today - timedelta(days=30)
                manquants = manquants.filter(created_at__date__gte=start_date)
            elif period == 'quarter':
                start_date = today - timedelta(days=90)
                manquants = manquants.filter(created_at__date__gte=start_date)
            elif period == 'year':
                start_date = today - timedelta(days=365)
                manquants = manquants.filter(created_at__date__gte=start_date)
            
            # Calculate totals
            totals = manquants.aggregate(
                total_manquant_usd=Sum('manquant_usd'),
                total_manquant_fc=Sum('manquant_fc'),
                count=Count('id')
            )
            
            # Analysis data for charts
            
            # 1. By Branch
            by_branch = manquants.values('branche__nom').annotate(
                count=Count('id'),
                total_usd=Sum('manquant_usd'),
                total_fc=Sum('manquant_fc')
            ).order_by('-total_usd')
            
            # 2. By Pompiste (Top 10)
            by_pompiste = manquants.values(
                'pompiste__id',
                'pompiste__prenom',
                'pompiste__nom'
            ).annotate(
                count=Count('id'),
                total_usd=Sum('manquant_usd'),
                total_fc=Sum('manquant_fc')
            ).order_by('-count')[:10]
            
            # 3. Trend (daily for last 30 days)
            if period in ['week', 'month', 'quarter']:
                trend_days = 30 if period == 'month' else 90 if period == 'quarter' else 7
                trend_start = today - timedelta(days=trend_days)
                
                trend = manquants.filter(
                    created_at__date__gte=trend_start
                ).annotate(
                    date=TruncDate('created_at')
                ).values('date').annotate(
                    count=Count('id'),
                    total_usd=Sum('manquant_usd')
                ).order_by('date')
                
                # Fill in missing dates with zeros
                trend_dict = {str(t['date']): t for t in trend}
                filled_trend = []
                for i in range(trend_days + 1):
                    check_date = trend_start + timedelta(days=i)
                    date_str = str(check_date)
                    if date_str in trend_dict:
                        filled_trend.append({
                            'date': check_date.strftime('%d/%m'),
                            'count': trend_dict[date_str]['count'],
                            'total_usd': float(trend_dict[date_str]['total_usd'] or 0)
                        })
                    else:
                        filled_trend.append({
                            'date': check_date.strftime('%d/%m'),
                            'count': 0,
                            'total_usd': 0
                        })
            else:
                filled_trend = []
            
            # Detailed list (limited to 100 most recent)
            manquants_list = []
            for m in manquants.order_by('-created_at')[:100]:
                manquants_list.append({
                    'id': m.id,
                    'date': m.created_at.strftime('%d/%m/%Y %H:%M'),
                    'branche': m.branche.nom if m.branche else 'N/A',
                    'pompiste': f"{m.pompiste.prenom} {m.pompiste.nom}" if m.pompiste else 'N/A',
                    'manager': f"{m.manager.prenom} {m.manager.nom}" if m.manager else 'N/A',
                    'caissier': f"{m.caissier.prenom} {m.caissier.nom}" if m.caissier else 'N/A',
                    'carburant': m.type_carburant.nom if m.type_carburant else 'N/A',
                    'montant_vente_usd': float(m.montant_usd),
                    'montant_vente_fc': float(m.montant_fc),
                    'manquant_usd': float(m.manquant_usd),
                    'manquant_fc': float(m.manquant_fc),
                    'raison': m.raison_manquant or 'Non spécifié'
                })
            
            # Count unique branches
            branches_count = manquants.values('branche').distinct().count()
            
            return JsonResponse({
                'success': True,
                'totals': {
                    'total_manquant_usd': float(totals['total_manquant_usd'] or 0),
                    'total_manquant_fc': float(totals['total_manquant_fc'] or 0),
                    'count': totals['count']
                },
                'analysis': {
                    'branches_count': branches_count,
                    'by_branch': [
                        {
                            'branche': b['branche__nom'],
                            'count': b['count'],
                            'total_usd': float(b['total_usd'] or 0),
                            'total_fc': float(b['total_fc'] or 0)
                        }
                        for b in by_branch
                    ],
                    'by_pompiste': [
                        {
                            'pompiste': f"{p['pompiste__prenom']} {p['pompiste__nom']}",
                            'count': p['count'],
                            'total_usd': float(p['total_usd'] or 0),
                            'total_fc': float(p['total_fc'] or 0)
                        }
                        for p in by_pompiste
                    ],
                    'trend': filled_trend
                },
                'manquants': manquants_list
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================
# NEW VIEW 2: Export Manquants to PDF
# ============================================

class ExportManquantsPDFView(AdminRequiredMixin, View):
    """
    Export manquants report to PDF with professional formatting
    """
    
    def get(self, request):
        try:
            # Get filters (same as report view)
            branche_id = request.GET.get('branche_id', 'all')
            pompiste_id = request.GET.get('pompiste_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Get manquants
            manquants = Vente.objects.filter(statut='manquant').select_related(
                'branche', 'pompiste', 'manager', 'caissier', 'type_carburant'
            )
            
            # Apply filters
            if branche_id and branche_id != 'all':
                manquants = manquants.filter(branche_id=branche_id)
            if pompiste_id and pompiste_id != 'all':
                manquants = manquants.filter(pompiste_id=pompiste_id)
            
            today = timezone.now().date()
            if period == 'week':
                start_date = today - timedelta(days=7)
                manquants = manquants.filter(created_at__date__gte=start_date)
            elif period == 'month':
                start_date = today - timedelta(days=30)
                manquants = manquants.filter(created_at__date__gte=start_date)
            elif period == 'quarter':
                start_date = today - timedelta(days=90)
                manquants = manquants.filter(created_at__date__gte=start_date)
            
            if not manquants.exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun manquant trouvé pour les filtres sélectionnés'
                }, status=404)
            
            # Create PDF
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="rapport_manquants_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = styles['Heading1']
            title_style.textColor = colors.HexColor('#DC2626')
            
            # Title
            elements.append(Paragraph('PETROX - Rapport des Manquants', title_style))
            elements.append(Paragraph(f'Généré le: {timezone.now().strftime("%d/%m/%Y à %H:%M")}', styles['Normal']))
            elements.append(Spacer(1, 0.3*inch))
            
            # Summary
            totals = manquants.aggregate(
                total_usd=Sum('manquant_usd'),
                total_fc=Sum('manquant_fc'),
                count=Count('id')
            )
            
            summary_data = [
                ['Métrique', 'Valeur'],
                ['Nombre total de manquants', str(totals['count'])],
                ['Total Manquant USD', f"${float(totals['total_usd'] or 0):.2f}"],
                ['Total Manquant FC', f"{float(totals['total_fc'] or 0):.0f} FC"]
            ]
            
            summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
            ]))
            
            elements.append(summary_table)
            elements.append(Spacer(1, 0.4*inch))
            
            # Detailed table
            elements.append(Paragraph('Détails des Manquants', styles['Heading2']))
            elements.append(Spacer(1, 0.2*inch))
            
            data = [['Date', 'Branche', 'Pompiste', 'Vente USD', 'Manquant USD', 'Raison']]
            
            for m in manquants.order_by('-created_at')[:50]:  # Limit to 50 for PDF
                data.append([
                    m.created_at.strftime('%d/%m/%Y'),
                    m.branche.nom[:15] if m.branche else 'N/A',
                    f"{m.pompiste.prenom} {m.pompiste.nom}"[:20] if m.pompiste else 'N/A',
                    f"${float(m.montant_usd):.2f}",
                    f"${float(m.manquant_usd):.2f}",
                    (m.raison_manquant or 'N/A')[:25]
                ])
            
            detail_table = Table(data, colWidths=[0.9*inch, 1.2*inch, 1.3*inch, 0.9*inch, 1*inch, 1.5*inch])
            detail_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F2937')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            
            elements.append(detail_table)
            
            # Build PDF
            doc.build(elements)
            pdf = buffer.getvalue()
            buffer.close()
            response.write(pdf)
            
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'export PDF: {str(e)}'
            }, status=500)


# ============================================
# NEW VIEW 3: Export Manquants to Excel
# ============================================

class ExportManquantsExcelView(AdminRequiredMixin, View):
    """
    Export manquants report to Excel with formatting and charts
    """
    
    def get(self, request):
        try:
            # Get filters
            branche_id = request.GET.get('branche_id', 'all')
            pompiste_id = request.GET.get('pompiste_id', 'all')
            period = request.GET.get('period', 'month')
            
            # Get manquants
            manquants = Vente.objects.filter(statut='manquant').select_related(
                'branche', 'pompiste', 'manager', 'caissier', 'type_carburant', 'moyen_paiement'
            )
            
            # Apply filters
            if branche_id and branche_id != 'all':
                manquants = manquants.filter(branche_id=branche_id)
            if pompiste_id and pompiste_id != 'all':
                manquants = manquants.filter(pompiste_id=pompiste_id)
            
            today = timezone.now().date()
            if period == 'week':
                start_date = today - timedelta(days=7)
                manquants = manquants.filter(created_at__date__gte=start_date)
            elif period == 'month':
                start_date = today - timedelta(days=30)
                manquants = manquants.filter(created_at__date__gte=start_date)
            elif period == 'quarter':
                start_date = today - timedelta(days=90)
                manquants = manquants.filter(created_at__date__gte=start_date)
            
            if not manquants.exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Aucun manquant trouvé'
                }, status=404)
            
            # Create workbook
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Manquants'
            
            # Header styling
            header_fill = PatternFill(start_color='DC2626', end_color='DC2626', fill_type='solid')
            header_font = Font(bold=True, color='FFFFFF', size=12)
            border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # Headers
            headers = [
                'Date', 'Heure', 'Branche', 'Pompiste', 'Manager', 'Caissier',
                'Carburant', 'Vente USD', 'Vente FC', 'Manquant USD', 
                'Manquant FC', 'Moyen Paiement', 'Raison'
            ]
            
            for col_num, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_num)
                cell.value = header
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = border
            
            # Data rows
            for row_num, m in enumerate(manquants.order_by('-created_at'), 2):
                ws.cell(row=row_num, column=1).value = m.created_at.strftime('%d/%m/%Y')
                ws.cell(row=row_num, column=2).value = m.created_at.strftime('%H:%M')
                ws.cell(row=row_num, column=3).value = m.branche.nom if m.branche else 'N/A'
                ws.cell(row=row_num, column=4).value = f"{m.pompiste.prenom} {m.pompiste.nom}" if m.pompiste else 'N/A'
                ws.cell(row=row_num, column=5).value = f"{m.manager.prenom} {m.manager.nom}" if m.manager else 'N/A'
                ws.cell(row=row_num, column=6).value = f"{m.caissier.prenom} {m.caissier.nom}" if m.caissier else 'N/A'
                ws.cell(row=row_num, column=7).value = m.type_carburant.nom if m.type_carburant else 'N/A'
                ws.cell(row=row_num, column=8).value = float(m.montant_usd)
                ws.cell(row=row_num, column=9).value = float(m.montant_fc)
                ws.cell(row=row_num, column=10).value = float(m.manquant_usd)
                ws.cell(row=row_num, column=11).value = float(m.manquant_fc)
                ws.cell(row=row_num, column=12).value = m.moyen_paiement.nom if m.moyen_paiement else 'N/A'
                ws.cell(row=row_num, column=13).value = m.raison_manquant or 'Non spécifié'
                
                # Apply border and highlight manquant cells
                for col_num in range(1, 14):
                    cell = ws.cell(row=row_num, column=col_num)
                    cell.border = border
                    if col_num in [10, 11]:  # Manquant columns
                        cell.fill = PatternFill(start_color='FEE2E2', end_color='FEE2E2', fill_type='solid')
                        cell.font = Font(bold=True, color='DC2626')
            
            # Adjust column widths
            column_widths = [12, 8, 18, 20, 20, 20, 12, 12, 12, 12, 12, 15, 30]
            for col_num, width in enumerate(column_widths, 1):
                ws.column_dimensions[openpyxl.utils.get_column_letter(col_num)].width = width
            
            # Summary row
            summary_row = len(list(manquants)) + 3
            ws.cell(row=summary_row, column=1).value = 'TOTAUX'
            ws.cell(row=summary_row, column=1).font = Font(bold=True, size=12)
            
            total_vente_usd = sum(float(m.montant_usd) for m in manquants)
            total_vente_fc = sum(float(m.montant_fc) for m in manquants)
            total_manquant_usd = sum(float(m.manquant_usd) for m in manquants)
            total_manquant_fc = sum(float(m.manquant_fc) for m in manquants)
            
            ws.cell(row=summary_row, column=8).value = total_vente_usd
            ws.cell(row=summary_row, column=8).font = Font(bold=True, size=12)
            ws.cell(row=summary_row, column=9).value = total_vente_fc
            ws.cell(row=summary_row, column=9).font = Font(bold=True, size=12)
            ws.cell(row=summary_row, column=10).value = total_manquant_usd
            ws.cell(row=summary_row, column=10).font = Font(bold=True, size=12, color='DC2626')
            ws.cell(row=summary_row, column=11).value = total_manquant_fc
            ws.cell(row=summary_row, column=11).font = Font(bold=True, size=12, color='DC2626')
            
            # Save to response
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="manquants_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
            
            wb.save(response)
            return response
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'export Excel: {str(e)}'
            }, status=500)


class PaySalaryAdminView(AdminRequiredMixin, View):
    """
    Admin can pay salary to any employee (Pompiste or User)
    Creates PaiementSalaire record and Depense record
    """
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['employee_type', 'employee_id', 'branche_id', 'montant', 'devise', 'periode']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    }, status=400)
            
            # Validate employee type
            if data['employee_type'] not in ['pompiste', 'user']:
                return JsonResponse({
                    'success': False,
                    'message': 'Type d\'employé invalide (pompiste ou user)'
                }, status=400)
            
            # Get employee
            employee = None
            employee_name = ''
            
            if data['employee_type'] == 'pompiste':
                try:
                    employee = Pompiste.objects.get(id=data['employee_id'], is_active=True)
                    employee_name = employee.get_full_name()
                except Pompiste.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Pompiste introuvable'
                    }, status=404)
            else:  # user
                try:
                    employee = User.objects.get(id=data['employee_id'], is_active=True)
                    employee_name = employee.get_full_name()
                except User.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Utilisateur introuvable'
                    }, status=404)
            
            # Get branche
            try:
                branche = Branche.objects.get(id=data['branche_id'], is_active=True)
            except Branche.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Branche introuvable'
                }, status=404)
            
            # Validate amount
            try:
                montant = Decimal(str(data['montant']))
                if montant <= 0:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le montant doit être supérieur à 0'
                    }, status=400)
            except (ValueError, TypeError, InvalidOperation):
                return JsonResponse({
                    'success': False,
                    'message': 'Montant invalide'
                }, status=400)
            
            # Validate currency
            if data['devise'] not in ['USD', 'FC']:
                return JsonResponse({
                    'success': False,
                    'message': 'Devise invalide (USD ou FC)'
                }, status=400)
            
            # Parse period (YYYY-MM format)
            try:
                periode = datetime.strptime(data['periode'], '%Y-%m').date()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': 'Format de période invalide (YYYY-MM attendu)'
                }, status=400)
            
            # Check if salary already paid for this period
            if data['employee_type'] == 'pompiste':
                existing = PaiementSalaire.objects.filter(
                    pompiste=employee,
                    mois_paiement=periode,
                    statut='paye'
                ).exists()
            else:
                existing = PaiementSalaire.objects.filter(
                    employe_user=employee,
                    mois_paiement=periode,
                    statut='paye'
                ).exists()
            
            if existing:
                return JsonResponse({
                    'success': False,
                    'message': f'Salaire déjà payé pour {periode.strftime("%m/%Y")}'
                }, status=400)
            
            # Get current exchange rate
            current_rate = TauxChange.objects.filter(is_active=True).first()
            taux = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
            
            # Create payment record
            payment_data = {
                'branche': branche,
                'caissier': request.user,
                'mois_paiement': periode,
                'montant_paye': montant,
                'devise_paiement': data['devise'],
                'taux_change': taux,
                'methode_paiement': data.get('methode_paiement', 'cash'),
                'notes': data.get('notes', ''),
                'statut': 'paye',
                'date_paiement': timezone.now()
            }
            
            if data['employee_type'] == 'pompiste':
                payment_data['pompiste'] = employee
            else:
                payment_data['employe_user'] = employee
            
            paiement = PaiementSalaire.objects.create(**payment_data)
            
            # Create expense record (salary as expense)
            categorie, created = CategorieDepense.objects.get_or_create(
                nom='Salaires',
                defaults={
                    'description': 'Paiements de salaires aux employés',
                    'created_by': request.user
                }
            )
            
            Depense.objects.create(
                branche=branche,
                categorie=categorie,
                description=f'Salaire {employee_name} - {periode.strftime("%m/%Y")}',
                montant=montant,
                devise=data['devise'],
                methode_paiement=data.get('methode_paiement', 'cash'),
                beneficiaire=employee_name,
                created_by=request.user,
                statut='approuvee'  # Auto-approved
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Salaire payé à {employee_name} pour {periode.strftime("%m/%Y")}',
                'payment': {
                    'id': paiement.id,
                    'employee': employee_name,
                    'branche': branche.nom,
                    'montant': str(montant),
                    'devise': data['devise'],
                    'periode': periode.strftime('%m/%Y'),
                    'date_paiement': paiement.date_paiement.strftime('%d/%m/%Y %H:%M')
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Format JSON invalide'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)


class EmployeesListView(AdminRequiredMixin, View):
    """
    Get list of all employees (Pompistes + Users) with salary info
    """
    
    def get(self, request):
        try:
            branche_id = request.GET.get('branche_id')
            employee_type = request.GET.get('employee_type', 'all')  # all, pompiste, user
            
            employees = []
            current_month = timezone.now().date().replace(day=1)
            
            # Get Pompistes
            if employee_type in ['all', 'pompiste']:
                pompistes = Pompiste.objects.filter(is_active=True).select_related('branche')
                
                if branche_id and branche_id != 'all':
                    pompistes = pompistes.filter(branche_id=branche_id)
                
                for pompiste in pompistes:
                    # Check if paid this month
                    last_payment = PaiementSalaire.objects.filter(
                        pompiste=pompiste
                    ).order_by('-date_paiement').first()
                    
                    paid_this_month = PaiementSalaire.objects.filter(
                        pompiste=pompiste,
                        mois_paiement=current_month,
                        statut='paye'
                    ).exists()
                    
                    employees.append({
                        'id': pompiste.id,
                        'type': 'pompiste',
                        'name': pompiste.get_full_name(),
                        'branche': pompiste.branche.nom if pompiste.branche else 'N/A',
                        'branche_id': pompiste.branche.id if pompiste.branche else None,
                        'salaire': float(pompiste.salaire),
                        'devise': pompiste.devise_salaire,
                        'last_payment_date': last_payment.date_paiement.strftime('%d/%m/%Y') if last_payment else 'Jamais',
                        'last_payment_amount': str(last_payment.montant_paye) if last_payment else '0',
                        'paid_this_month': paid_this_month,
                        'status': 'Payé' if paid_this_month else 'En attente',
                        'quart': pompiste.get_quart_display() if pompiste.quart else 'N/A'
                    })
            
            # Get System Users (Manager, Caissier)
            if employee_type in ['all', 'user']:
                users = User.objects.filter(
                    is_active=True,
                    role__in=['manager', 'caissier']
                ).select_related('branche')
                
                if branche_id and branche_id != 'all':
                    users = users.filter(branche_id=branche_id)
                
                for user in users:
                    last_payment = PaiementSalaire.objects.filter(
                        employe_user=user
                    ).order_by('-date_paiement').first()
                    
                    paid_this_month = PaiementSalaire.objects.filter(
                        employe_user=user,
                        mois_paiement=current_month,
                        statut='paye'
                    ).exists()
                    
                    employees.append({
                        'id': user.id,
                        'type': 'user',
                        'name': user.get_full_name(),
                        'branche': user.branche.nom if user.branche else 'N/A',
                        'branche_id': user.branche.id if user.branche else None,
                        'salaire': float(user.salaire) if user.salaire else 0,
                        'devise': user.devise_salaire if user.devise_salaire else 'USD',
                        'last_payment_date': last_payment.date_paiement.strftime('%d/%m/%Y') if last_payment else 'Jamais',
                        'last_payment_amount': str(last_payment.montant_paye) if last_payment else '0',
                        'paid_this_month': paid_this_month,
                        'status': 'Payé' if paid_this_month else 'En attente',
                        'role': user.get_role_display()
                    })
            
            return JsonResponse({
                'success': True,
                'employees': employees,
                'count': len(employees)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class SalaryStatisticsView(AdminRequiredMixin, View):
    """
    Get salary statistics (totals, counts, pending)
    """
    
    def get(self, request):
        try:
            branche_id = request.GET.get('branche_id')
            period = request.GET.get('period', 'month')  # month, year
            
            # Calculate date range
            today = timezone.now().date()
            if period == 'month':
                start_date = today.replace(day=1)
            else:  # year
                start_date = today.replace(month=1, day=1)
            
            # Base query
            payments = PaiementSalaire.objects.filter(
                date_paiement__date__gte=start_date,
                statut='paye'
            )
            
            if branche_id and branche_id != 'all':
                payments = payments.filter(branche_id=branche_id)
            
            # Calculate totals
            total_usd = payments.filter(devise_paiement='USD').aggregate(
                Sum('montant_paye'))['montant_paye__sum'] or Decimal('0')
            
            total_fc = payments.filter(devise_paiement='FC').aggregate(
                Sum('montant_paye'))['montant_paye__sum'] or Decimal('0')
            
            # Count employees paid
            employees_paid = payments.values('pompiste', 'employe_user').distinct().count()
            
            # Get pending payments (employees not paid this month)
            current_month = today.replace(day=1)
            
            # Count pompistes not paid
            all_pompistes = Pompiste.objects.filter(is_active=True)
            if branche_id and branche_id != 'all':
                all_pompistes = all_pompistes.filter(branche_id=branche_id)
            
            paid_pompistes = PaiementSalaire.objects.filter(
                mois_paiement=current_month,
                statut='paye',
                pompiste__isnull=False
            ).values_list('pompiste_id', flat=True)
            
            pending_pompistes = all_pompistes.exclude(id__in=paid_pompistes).count()
            
            # Count users not paid
            all_users = User.objects.filter(
                is_active=True,
                role__in=['manager', 'caissier']
            )
            if branche_id and branche_id != 'all':
                all_users = all_users.filter(branche_id=branche_id)
            
            paid_users = PaiementSalaire.objects.filter(
                mois_paiement=current_month,
                statut='paye',
                employe_user__isnull=False
            ).values_list('employe_user_id', flat=True)
            
            pending_users = all_users.exclude(id__in=paid_users).count()
            
            pending_total = pending_pompistes + pending_users
            
            # Get payment trends (last 6 months)
            trends = []
            for i in range(5, -1, -1):
                month_date = (today.replace(day=1) - timedelta(days=i*30)).replace(day=1)
                
                month_payments = PaiementSalaire.objects.filter(
                    mois_paiement=month_date,
                    statut='paye'
                )
                
                if branche_id and branche_id != 'all':
                    month_payments = month_payments.filter(branche_id=branche_id)
                
                month_usd = month_payments.filter(devise_paiement='USD').aggregate(
                    Sum('montant_paye'))['montant_paye__sum'] or Decimal('0')
                
                month_fc = month_payments.filter(devise_paiement='FC').aggregate(
                    Sum('montant_paye'))['montant_paye__sum'] or Decimal('0')
                
                trends.append({
                    'month': month_date.strftime('%b %Y'),
                    'total_usd': float(month_usd),
                    'total_fc': float(month_fc),
                    'count': month_payments.count()
                })
            
            return JsonResponse({
                'success': True,
                'statistics': {
                    'total_usd': float(total_usd),
                    'total_fc': float(total_fc),
                    'employees_paid': employees_paid,
                    'pending_payments': pending_total,
                    'pending_pompistes': pending_pompistes,
                    'pending_users': pending_users,
                    'period': period
                },
                'trends': trends
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class EmployeeSalaryHistoryView(AdminRequiredMixin, View):
    """
    Get complete salary history for a specific employee
    """
    
    def get(self, request, employee_type, employee_id):
        try:
            # Get employee
            employee = None
            employee_name = ''
            
            if employee_type == 'pompiste':
                try:
                    employee = Pompiste.objects.get(id=employee_id)
                    employee_name = employee.get_full_name()
                    payments = PaiementSalaire.objects.filter(pompiste=employee)
                except Pompiste.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Pompiste introuvable'
                    }, status=404)
            elif employee_type == 'user':
                try:
                    employee = User.objects.get(id=employee_id)
                    employee_name = employee.get_full_name()
                    payments = PaiementSalaire.objects.filter(employe_user=employee)
                except User.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'message': 'Utilisateur introuvable'
                    }, status=404)
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Type d\'employé invalide'
                }, status=400)
            
            # Get all payments
            payments = payments.select_related('branche', 'caissier').order_by('-date_paiement')
            
            # Serialize
            payments_data = [{
                'id': p.id,
                'branche': p.branche.nom if p.branche else 'N/A',
                'periode': p.mois_paiement.strftime('%m/%Y') if p.mois_paiement else 'N/A',
                'montant': str(p.montant_paye),
                'devise': p.devise_paiement,
                'methode': p.get_methode_paiement_display(),
                'paid_by': p.caissier.get_full_name() if p.caissier else 'N/A',
                'date_paiement': p.date_paiement.strftime('%d/%m/%Y %H:%M'),
                'statut': p.get_statut_display(),
                'notes': p.notes
            } for p in payments]
            
            # Calculate totals
            total_usd = payments.filter(devise_paiement='USD').aggregate(
                Sum('montant_paye'))['montant_paye__sum'] or Decimal('0')
            
            total_fc = payments.filter(devise_paiement='FC').aggregate(
                Sum('montant_paye'))['montant_paye__sum'] or Decimal('0')
            
            return JsonResponse({
                'success': True,
                'employee': {
                    'name': employee_name,
                    'type': employee_type,
                    'id': employee_id
                },
                'payments': payments_data,
                'summary': {
                    'total_payments': payments.count(),
                    'total_usd': float(total_usd),
                    'total_fc': float(total_fc)
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

class PartnersListView(AdminRequiredMixin, View):
    """List all fuel partners"""
    
    def get(self, request):
        partners = Partenaire.objects.filter(is_active=True).order_by('nom')
        
        context = {
            'partners': partners,
            'partners_count': partners.count(),
            'partners_with_debt': partners.filter(
                Q(solde_usd__gt=0) | Q(solde_fc__gt=0)
            ).count(),
            'partners_we_owe': partners.filter(
                Q(solde_usd__lt=0) | Q(solde_fc__lt=0)
            ).count(),
        }
        
        return render(request, 'admin/partners.html', context)


class PartnerCreateAPIView(AdminRequiredMixin, View):
    """Create new partner"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Check if code exists
            if Partenaire.objects.filter(code=data['code']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce code partenaire existe déjà'
                }, status=400)
            
            partner = Partenaire.objects.create(
                nom=data['nom'],
                code=data['code'],
                contact=data.get('contact', ''),
                telephone=data.get('telephone', ''),
                email=data.get('email', ''),
                adresse=data.get('adresse', ''),
                notes=data.get('notes', ''),
                created_by=request.user
            )
            
            return JsonResponse({
                'success': True,
                'partner': {
                    'id': partner.id,
                    'nom': partner.nom,
                    'code': partner.code
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class PartnerDetailAPIView(AdminRequiredMixin, View):
    """Get partner details"""
    
    def get(self, request, partner_id):
        try:
            partner = get_object_or_404(Partenaire, id=partner_id)
            
            # Get recent deliveries
            deliveries = LivraisonCarburant.objects.filter(
                partenaire=partner
            ).select_related(
                'type_carburant', 'branche'
            ).order_by('-date_prevue')[:10]
            
            # Get payments
            payments = PaiementPartenaire.objects.filter(
                partenaire=partner
            ).order_by('-date_paiement')[:10]
            
            return JsonResponse({
                'success': True,
                'partner': {
                    'id': partner.id,
                    'nom': partner.nom,
                    'code': partner.code,
                    'contact': partner.contact,
                    'telephone': partner.telephone,
                    'email': partner.email,
                    'adresse': partner.adresse,
                    'solde_usd': float(partner.solde_usd),
                    'solde_fc': float(partner.solde_fc),
                    'notes': partner.notes,
                },
                'deliveries': [{
                    'numero': d.numero,
                    'type': d.get_type_livraison_display(),
                    'carburant': d.type_carburant.nom,
                    'branche': d.branche.nom,
                    'quantite': float(d.quantite_prevue),
                    'statut': d.get_statut_display(),
                    'date': d.date_prevue.strftime('%d/%m/%Y')
                } for d in deliveries],
                'payments': [{
                    'numero': p.numero,
                    'type': p.get_type_transaction_display(),
                    'montant': float(p.montant),
                    'devise': p.devise,
                    'date': p.date_paiement.strftime('%d/%m/%Y')
                } for p in payments]
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================================================
# DELIVERY VIEWS
# ============================================================================

class DeliveriesListView(AdminRequiredMixin, View):
    """List all fuel deliveries"""
    
    def get(self, request):
        # Filters
        statut = request.GET.get('statut', 'all')
        branch_id = request.GET.get('branche_id')
        partner_id = request.GET.get('partenaire_id')
        
        deliveries = LivraisonCarburant.objects.select_related(
            'type_carburant', 'branche', 'partenaire', 
            'planifiee_par', 'confirmee_par'
        ).order_by('-date_prevue', '-created_at')
        
        if statut != 'all':
            deliveries = deliveries.filter(statut=statut)
        
        if branch_id:
            deliveries = deliveries.filter(branche_id=branch_id)
        
        if partner_id:
            deliveries = deliveries.filter(partenaire_id=partner_id)
        
        # Stats
        total_deliveries = deliveries.count()
        pending_confirmation = deliveries.filter(statut='livree').count()
        confirmed_today = deliveries.filter(
            statut='confirmee',
            date_confirmation__date=timezone.now().date()
        ).count()
        
        context = {
            'deliveries': deliveries,
            'total_deliveries': total_deliveries,
            'pending_confirmation': pending_confirmation,
            'confirmed_today': confirmed_today,
            'all_branches': Branche.objects.filter(is_active=True),
            'partners': Partenaire.objects.filter(is_active=True),
            'fuel_types': TypeCarburant.objects.filter(is_active=True),
        }
        
        return render(request, 'admin/deliveries.html', context)


class DeliveryPlanAPIView(AdminRequiredMixin, View):
    """Plan a new delivery"""
    
    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            type_livraison = data['type_livraison']
            branche_id = data['branche_id']
            type_carburant_id = data['type_carburant_id']
            quantite = Decimal(str(data['quantite_prevue']))
            
            # Validate capacity
            stock = Stock.objects.filter(
                branche_id=branche_id,
                type_carburant_id=type_carburant_id
            ).first()
            
            if not stock:
                return JsonResponse({
                    'success': False,
                    'message': 'Stock non trouvé pour cette branche et ce carburant'
                }, status=400)
            
            # Check if delivery fits in capacity
            if type_livraison in ['propre', 'partenaire_donne']:
                espace_disponible = stock.capacite_max - stock.quantite_actuelle
                if quantite > espace_disponible:
                    return JsonResponse({
                        'success': False,
                        'message': f'Capacité insuffisante. Espace disponible: {espace_disponible}L'
                    }, status=400)
            
            # Check if partner provided for partner deliveries
            if type_livraison in ['partenaire_donne', 'partenaire_prend']:
                if not data.get('partenaire_id'):
                    return JsonResponse({
                        'success': False,
                        'message': 'Partenaire requis pour ce type de livraison'
                    }, status=400)
            
            # Create delivery
            delivery = LivraisonCarburant.objects.create(
                type_livraison=type_livraison,
                type_carburant_id=type_carburant_id,
                branche_id=branche_id,
                quantite_prevue=quantite,
                partenaire_id=data.get('partenaire_id'),
                prix_unitaire=data.get('prix_unitaire'),
                devise=data.get('devise', 'USD'),
                date_prevue=data['date_prevue'],
                bon_livraison=data.get('bon_livraison', ''),
                transporteur=data.get('transporteur', ''),
                immatriculation=data.get('immatriculation', ''),
                observations_admin=data.get('observations', ''),
                planifiee_par=request.user,
                statut_paiement='non_requis' if type_livraison == 'propre' else 'en_attente'
            )
            
            # Notify branch manager
            manager = User.objects.filter(
                role='gestionnaire',
                branche_id=branche_id,
                is_active=True
            ).first()
            
            if manager:
                action_text = "reçoit" if type_livraison != 'partenaire_prend' else "donne"
                Notification.objects.create(
                    destinataire=manager,
                    titre=f"Nouvelle livraison planifiée: {delivery.numero}",
                    message=f"Une livraison de {quantite}L de {delivery.type_carburant.nom} est planifiée pour le {delivery.date_prevue.strftime('%d/%m/%Y')}. Votre branche {action_text} ce carburant.",
                    type_notification='livraison_planifiee',
                    priorite='haute',
                    expediteur=request.user,
                    objet_id=delivery.id
                )
            
            return JsonResponse({
                'success': True,
                'delivery': {
                    'id': delivery.id,
                    'numero': delivery.numero
                }
            })
            
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class DeliveryConfirmAPIView(View):
    """Manager confirms delivery reception"""
    
    @transaction.atomic
    def post(self, request, delivery_id):
        try:
            data = json.loads(request.body)
            
            delivery = get_object_or_404(
                LivraisonCarburant,
                id=delivery_id
            )
            
            # Only manager of the branch or admin can confirm
            if request.user.role == 'gestionnaire':
                if request.user.branche_id != delivery.branche_id:
                    return JsonResponse({
                        'success': False,
                        'message': 'Vous ne pouvez confirmer que les livraisons de votre branche'
                    }, status=403)
            elif request.user.role != 'admin':
                return JsonResponse({
                    'success': False,
                    'message': 'Permission refusée'
                }, status=403)
            
            if delivery.statut == 'confirmee':
                return JsonResponse({
                    'success': False,
                    'message': 'Cette livraison a déjà été confirmée'
                }, status=400)
            
            quantite_recue = Decimal(str(data['quantite_recue']))
            
            # Update delivery
            delivery.quantite_recue = quantite_recue
            delivery.statut = 'confirmee'
            delivery.date_confirmation = timezone.now()
            delivery.confirmee_par = request.user
            delivery.observations_manager = data.get('observations', '')
            delivery.save()
            
            # Update stock
            stock = Stock.objects.get(
                branche=delivery.branche,
                type_carburant=delivery.type_carburant
            )
            
            if delivery.type_livraison in ['propre', 'partenaire_donne']:
                # Increase stock
                stock.quantite_actuelle += quantite_recue
            else:  # partenaire_prend
                # Decrease stock
                stock.quantite_actuelle -= quantite_recue
            
            stock.save()
            
            # Update partner balance if applicable
            if delivery.partenaire and delivery.prix_unitaire:
                montant = delivery.montant_total
                
                if delivery.type_livraison == 'partenaire_donne':
                    # They gave us fuel - we owe them
                    if delivery.devise == 'USD':
                        delivery.partenaire.solde_usd -= montant  # Negative = we owe
                    else:
                        delivery.partenaire.solde_fc -= montant
                    
                elif delivery.type_livraison == 'partenaire_prend':
                    # They took fuel - they owe us
                    if delivery.devise == 'USD':
                        delivery.partenaire.solde_usd += montant  # Positive = they owe
                    else:
                        delivery.partenaire.solde_fc += montant
                
                delivery.partenaire.save()
            
            # Notify admin if there's a discrepancy
            if delivery.has_ecart:
                admins = User.objects.filter(role='admin', is_active=True)
                for admin in admins:
                    Notification.objects.create(
                        destinataire=admin,
                        titre=f"Écart de livraison: {delivery.numero}",
                        message=f"Écart de {delivery.ecart_quantite}L ({delivery.ecart_percentage:.1f}%) détecté sur la livraison {delivery.numero}. Prévu: {delivery.quantite_prevue}L, Reçu: {delivery.quantite_recue}L",
                        type_notification='ecart_livraison',
                        priorite='haute',
                        expediteur=request.user,
                        objet_id=delivery.id
                    )
            
            return JsonResponse({
                'success': True,
                'message': 'Livraison confirmée avec succès',
                'delivery': {
                    'numero': delivery.numero,
                    'quantite_recue': float(quantite_recue),
                    'ecart': float(delivery.ecart_quantite),
                    'has_ecart': delivery.has_ecart
                }
            })
            
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)

class DeliveryDetailAPIView(View):
    """Get delivery details"""
    
    def get(self, request, delivery_id):
        try:
            delivery = get_object_or_404(
                LivraisonCarburant.objects.select_related(
                    'type_carburant', 'branche', 'partenaire',
                    'planifiee_par', 'confirmee_par'
                ),
                id=delivery_id
            )
            
            return JsonResponse({
                'success': True,
                'delivery': {
                    'id': delivery.id,
                    'numero': delivery.numero,
                    'type_livraison': delivery.type_livraison,
                    'type_livraison_display': delivery.get_type_livraison_display(),
                    'statut': delivery.statut,
                    'statut_display': delivery.get_statut_display(),
                    'carburant': delivery.type_carburant.nom,
                    'branche': delivery.branche.nom,
                    'partenaire': delivery.partenaire.nom if delivery.partenaire else None,
                    'quantite_prevue': float(delivery.quantite_prevue),
                    'quantite_recue': float(delivery.quantite_recue) if delivery.quantite_recue else None,
                    'ecart': float(delivery.ecart_quantite),
                    'ecart_percentage': float(delivery.ecart_percentage),
                    'prix_unitaire': float(delivery.prix_unitaire) if delivery.prix_unitaire else None,
                    'devise': delivery.devise,
                    'montant_total': float(delivery.montant_total),
                    'statut_paiement': delivery.statut_paiement,
                    'date_prevue': delivery.date_prevue.strftime('%d/%m/%Y'),
                    'date_livraison': delivery.date_livraison.strftime('%d/%m/%Y %H:%M') if delivery.date_livraison else None,
                    'date_confirmation': delivery.date_confirmation.strftime('%d/%m/%Y %H:%M') if delivery.date_confirmation else None,
                    'bon_livraison': delivery.bon_livraison,
                    'transporteur': delivery.transporteur,
                    'immatriculation': delivery.immatriculation,
                    'observations_admin': delivery.observations_admin,
                    'observations_manager': delivery.observations_manager,
                    'planifiee_par': delivery.planifiee_par.get_full_name() if delivery.planifiee_par else None,
                    'confirmee_par': delivery.confirmee_par.get_full_name() if delivery.confirmee_par else None,
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class DeliveryCancelAPIView(AdminRequiredMixin, View):
    """Cancel a delivery"""
    
    def post(self, request, delivery_id):
        try:
            delivery = get_object_or_404(LivraisonCarburant, id=delivery_id)
            
            if delivery.statut == 'confirmee':
                return JsonResponse({
                    'success': False,
                    'message': 'Impossible d\'annuler une livraison déjà confirmée'
                }, status=400)
            
            delivery.statut = 'annulee'
            delivery.save()
            
            # Notify manager
            manager = User.objects.filter(
                role='gestionnaire',
                branche=delivery.branche,
                is_active=True
            ).first()
            
            if manager:
                Notification.objects.create(
                    destinataire=manager,
                    titre=f"Livraison annulée: {delivery.numero}",
                    message=f"La livraison de {delivery.quantite_prevue}L de {delivery.type_carburant.nom} prévue pour le {delivery.date_prevue.strftime('%d/%m/%Y')} a été annulée.",
                    type_notification='livraison_annulee',
                    priorite='normale',
                    expediteur=request.user,
                    objet_id=delivery.id
                )
            
            return JsonResponse({
                'success': True,
                'message': 'Livraison annulée'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class PendingDeliveriesAPIView(View):
    """Get pending deliveries for manager"""
    
    def get(self, request):
        try:
            # For managers, only their branch
            if request.user.role == 'gestionnaire':
                deliveries = LivraisonCarburant.objects.filter(
                    branche=request.user.branche,
                    statut__in=['planifiee', 'en_transit', 'livree']
                ).select_related('type_carburant', 'partenaire').order_by('date_prevue')
            else:
                # Admins see all
                deliveries = LivraisonCarburant.objects.filter(
                    statut__in=['planifiee', 'en_transit', 'livree']
                ).select_related('type_carburant', 'branche', 'partenaire').order_by('date_prevue')
            
            return JsonResponse({
                'success': True,
                'deliveries': [{
                    'id': d.id,
                    'numero': d.numero,
                    'type': d.get_type_livraison_display(),
                    'carburant': d.type_carburant.nom,
                    'branche': d.branche.nom,
                    'partenaire': d.partenaire.nom if d.partenaire else None,
                    'quantite': float(d.quantite_prevue),
                    'date_prevue': d.date_prevue.strftime('%d/%m/%Y'),
                    'statut': d.get_statut_display(),
                    'can_confirm': d.statut in ['livree', 'en_transit']
                } for d in deliveries]
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================================================
# PARTNER PAYMENT VIEWS
# ============================================================================

class PartnerPaymentAPIView(AdminRequiredMixin, View):
    """Record payment to/from partner"""
    
    @transaction.atomic
    def post(self, request, partner_id):
        try:
            data = json.loads(request.body)
            partner = get_object_or_404(Partenaire, id=partner_id)
            
            payment = PaiementPartenaire.objects.create(
                partenaire=partner,
                type_transaction=data['type_transaction'],
                montant=Decimal(str(data['montant'])),
                devise=data['devise'],
                livraison_id=data.get('livraison_id'),
                date_paiement=data['date_paiement'],
                mode_paiement=data['mode_paiement'],
                reference=data.get('reference', ''),
                notes=data.get('notes', ''),
                enregistre_par=request.user
            )
            
            return JsonResponse({
                'success': True,
                'payment': {
                    'numero': payment.numero,
                    'montant': float(payment.montant),
                    'devise': payment.devise
                },
                'new_balance_usd': float(partner.solde_usd),
                'new_balance_fc': float(partner.solde_fc)
            })
            
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


class PartnerUpdateAPIView(AdminRequiredMixin, View):
    """Update partner info"""
    
    def put(self, request, partner_id):
        try:
            partner = get_object_or_404(Partenaire, id=partner_id)
            data = json.loads(request.body)
            
            # Check code uniqueness
            if data.get('code') and data['code'] != partner.code:
                if Partenaire.objects.filter(code=data['code']).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Ce code existe déjà'
                    }, status=400)
            
            # Update fields
            for field in ['nom', 'code', 'contact', 'telephone', 'email', 'adresse', 'notes']:
                if field in data:
                    setattr(partner, field, data[field])
            
            partner.save()
            
            return JsonResponse({
                'success': True,
                'partner': {
                    'id': partner.id,
                    'nom': partner.nom
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)


# ============================================================================
# STOCK VIEWS (Updated to prevent direct modification)
# ============================================================================

class StockUpdateSettingsAPIView(AdminRequiredMixin, View):
    """Update stock settings ONLY (not quantity)"""
    
    def put(self, request, stock_id):
        try:
            stock = get_object_or_404(Stock, id=stock_id)
            data = json.loads(request.body)
            
            # ONLY allow updating settings, NOT quantity
            stock.capacite_max = Decimal(str(data['capacite_max']))
            stock.seuil_alerte = Decimal(str(data['seuil_alerte']))
            
            if data.get('prix_achat'):
                stock.prix_achat = Decimal(str(data['prix_achat']))
            
            stock.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Paramètres mis à jour'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)