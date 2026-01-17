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
    User, Branche, TauxChange, CategorieDepense, Vente, Depense, 
    PaiementSalaire, Pompiste
)
from decimal import Decimal
import json


class CaissierRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return (self.request.user.is_authenticated and 
                self.request.user.role == 'caissier' and 
                self.request.user.branche is not None)


class CaissierDashboardView(CaissierRequiredMixin, TemplateView):
    template_name = 'caissier/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_branche'] = self.request.user.branche
        context['categories_depense'] = CategorieDepense.objects.filter(is_active=True)
        context['pompistes'] = Pompiste.objects.filter(
            branche=self.request.user.branche,
            is_active=True
        )
        return context


class CaissierDashboardStatsAPIView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        today = timezone.now().date()
        
        # Calculate total entries (validated sales) for today
        validated_sales_today = Vente.objects.filter(
            branche=branche,
            created_at__date=today,
            statut='validee'
        )
        
        total_entries_usd = validated_sales_today.aggregate(
            Sum('montant_usd')
        )['montant_usd__sum'] or 0
        
        total_entries_fc = validated_sales_today.aggregate(
            Sum('montant_fc')
        )['montant_fc__sum'] or 0
        
        # Calculate total expenses for today
        expenses_today = Depense.objects.filter(
            branche=branche,
            created_at__date=today,
            statut='approuvee'
        )
        
        total_expenses_usd = expenses_today.filter(devise='USD').aggregate(
            Sum('montant')
        )['montant__sum'] or 0
        
        total_expenses_fc = expenses_today.filter(devise='FC').aggregate(
            Sum('montant')
        )['montant__sum'] or 0
        
        # Count pending validations
        pending_validations = Vente.objects.filter(
            branche=branche,
            statut='en_attente'
        ).count()
        
        # Count missing reports today
        missing_reports = Vente.objects.filter(
            branche=branche,
            created_at__date=today,
            statut='manquant'
        ).count()
        
        # Calculate daily balance
        balance_usd = total_entries_usd - total_expenses_usd
        balance_fc = total_entries_fc - total_expenses_fc
        
        # Get current exchange rate
        current_rate = TauxChange.objects.filter(is_active=True).first()
        current_rate_value = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        # Convert balance to primary currency for display
        balance_total_usd = balance_usd + (balance_fc / current_rate_value)
        
        # Determine balance status
        if balance_total_usd >= 0:
            balance_status = "Positif"
        else:
            balance_status = "Négatif"
        
        stats = {
            'branche_nom': branche.nom,
            'branche_code': branche.code,
            'total_entries_today': f"{total_entries_usd:.2f}",
            'total_entries_today_fc': f"{total_entries_fc:.0f}",
            'total_expenses_today': f"{total_expenses_usd:.2f}",
            'total_expenses_today_fc': f"{total_expenses_fc:.0f}",
            'balance_today': f"{balance_total_usd:.2f}",
            'balance_usd': f"{balance_usd:.2f}",
            'balance_fc': f"{balance_fc:.0f}",
            'balance_status': balance_status,
            'pending_validations': pending_validations,
            'missing_reports': missing_reports,
            'pending_count': pending_validations,
            'current_rate': f"{current_rate_value:.2f}"
        }
        
        return JsonResponse(stats)


class PendingSalesView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get pending sales for validation
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
                'manager': sale.manager.get_full_name(),
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


class ValidateSaleView(CaissierRequiredMixin, View):
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
                # Validate the sale
                vente.statut = 'validee'
                vente.caissier = request.user
                vente.validated_at = timezone.now()
                vente.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Vente #{vente.id} validée avec succès',
                    'sale_id': vente.id
                })
                
            elif action == 'report_missing':
                # Report missing amounts
                manquant_usd = data.get('manquant_usd', 0)
                manquant_fc = data.get('manquant_fc', 0)
                raison_manquant = data.get('raison_manquant', '')
                
                try:
                    manquant_usd = Decimal(str(manquant_usd)) if manquant_usd else Decimal('0')
                    manquant_fc = Decimal(str(manquant_fc)) if manquant_fc else Decimal('0')
                except (ValueError, TypeError):
                    return JsonResponse({
                        'success': False,
                        'message': 'Montants manquants invalides'
                    })
                
                # Validate that missing amounts don't exceed sale amounts
                if manquant_usd > vente.montant_usd:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le manquant USD ne peut pas dépasser le montant de la vente'
                    })
                
                if manquant_fc > vente.montant_fc:
                    return JsonResponse({
                        'success': False,
                        'message': 'Le manquant FC ne peut pas dépasser le montant de la vente'
                    })
                
                # Update sale with missing information
                vente.statut = 'manquant'
                vente.caissier = request.user
                vente.validated_at = timezone.now()
                vente.manquant_usd = manquant_usd
                vente.manquant_fc = manquant_fc
                vente.raison_manquant = raison_manquant
                vente.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Manquant signalé pour la vente #{vente.id}',
                    'sale_id': vente.id,
                    'manquant_usd': str(manquant_usd),
                    'manquant_fc': str(manquant_fc)
                })
            
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Action non reconnue'
                })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors du traitement: {str(e)}'
            })


class RegisterExpenseView(CaissierRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['categorie_id', 'description', 'montant', 'devise']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Get category
            try:
                categorie = CategorieDepense.objects.get(
                    id=data['categorie_id'],
                    is_active=True
                )
            except CategorieDepense.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Catégorie de dépense introuvable'
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
            methode_paiement = data.get('methode_paiement', 'cash')
            if methode_paiement not in ['cash', 'mobile_money', 'bank']:
                return JsonResponse({
                    'success': False,
                    'message': 'Méthode de paiement invalide'
                })
            
            # Create expense
            depense = Depense.objects.create(
                branche=request.user.branche,
                categorie=categorie,
                created_by=request.user,
                description=data['description'],
                montant=montant,
                devise=data['devise'],
                methode_paiement=methode_paiement,
                beneficiaire=data.get('beneficiaire', ''),
                notes=data.get('notes', ''),
                statut='approuvee'  # Auto-approved for caissier
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Dépense enregistrée avec succès',
                'expense': {
                    'id': depense.id,
                    'description': depense.description,
                    'montant': str(depense.montant),
                    'devise': depense.devise,
                    'categorie': categorie.nom,
                    'created_at': depense.created_at.strftime('%d/%m/%Y %H:%M')
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


class CaissierExpensesListView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get filters
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        categorie_id = request.GET.get('categorie_id')
        devise = request.GET.get('devise')
        
        # Base queryset
        expenses = Depense.objects.filter(branche=branche).select_related(
            'categorie', 'created_by'
        )
        
        # Apply filters
        if date_start:
            try:
                start_date = datetime.strptime(date_start, '%Y-%m-%d').date()
                expenses = expenses.filter(created_at__date__gte=start_date)
            except ValueError:
                pass
        
        if date_end:
            try:
                end_date = datetime.strptime(date_end, '%Y-%m-%d').date()
                expenses = expenses.filter(created_at__date__lte=end_date)
            except ValueError:
                pass
        
        if categorie_id:
            expenses = expenses.filter(categorie_id=categorie_id)
        
        if devise:
            expenses = expenses.filter(devise=devise)
        
        # Order by most recent
        expenses = expenses.order_by('-created_at')[:100]
        
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
                'notes': expense.notes or '',
                'approved_at': expense.approved_at.strftime('%d/%m/%Y %H:%M') if expense.approved_at else None
            })
        
        return JsonResponse({'expenses': expenses_data})


class PaySalaryView(CaissierRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            required_fields = ['pompiste_id', 'montant', 'devise', 'periode']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
                    })
            
            # Get pompiste
            try:
                pompiste = Pompiste.objects.get(
                    id=data['pompiste_id'],
                    branche=request.user.branche,
                    is_active=True
                )
            except Pompiste.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Pompiste introuvable'
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
            
            # Parse period
            try:
                periode = datetime.strptime(data['periode'], '%Y-%m').date()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': 'Format de période invalide (YYYY-MM attendu)'
                })
            
            # Check if salary already paid for this period
            existing_payment = PaiementSalaire.objects.filter(
                pompiste=pompiste,
                mois_paiement=periode,
                statut='paye'
            ).exists()
            
            if existing_payment:
                return JsonResponse({
                    'success': False,
                    'message': f'Salaire déjà payé pour {periode.strftime("%m/%Y")}'
                })
            
            # Get current exchange rate
            current_rate = TauxChange.objects.filter(is_active=True).first()
            
            # Create salary payment record
            paiement = PaiementSalaire.objects.create(
                pompiste=pompiste,
                branche=request.user.branche,
                caissier=request.user,
                mois_paiement=periode,
                montant_paye=montant,
                devise_paiement=data['devise'],
                taux_change=current_rate.taux_usd_fc if current_rate else Decimal('2800.00'),
                methode_paiement=data.get('methode_paiement', 'cash'),
                notes=data.get('notes', ''),
                statut='paye',
                date_paiement=timezone.now()
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Salaire payé à {pompiste.get_full_name()} pour {periode.strftime("%m/%Y")}',
                'payment': {
                    'id': paiement.id,
                    'pompiste': pompiste.get_full_name(),
                    'montant': str(montant),
                    'devise': data['devise'],
                    'periode': periode.strftime('%m/%Y'),
                    'date_paiement': paiement.date_paiement.strftime('%d/%m/%Y %H:%M')
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
                'message': f'Erreur lors du paiement: {str(e)}'
            })