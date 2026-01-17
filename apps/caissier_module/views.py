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
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, Count
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import datetime, timedelta
from apps.core.models import (
    User, Branche, TauxChange, CategorieDepense, Vente, Depense, 
    PaiementSalaire, Pompiste, Abonne, ConsommationAbonne
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

class ValidatedSalesHistoryView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get filters
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        statut = request.GET.get('statut')
        pompiste_id = request.GET.get('pompiste_id')
        
        # Base query for validated sales
        sales = Vente.objects.filter(
            branche=branche,
            caissier=request.user,
            statut__in=['validee', 'manquant']
        ).select_related('pompiste', 'manager', 'type_carburant', 'moyen_paiement')
        
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
        
        if statut:
            sales = sales.filter(statut=statut)
        
        if pompiste_id:
            sales = sales.filter(pompiste_id=pompiste_id)
        
        # Order and paginate
        sales = sales.order_by('-validated_at')
        paginator = Paginator(sales, 50)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        sales_data = []
        for sale in page_obj:
            sales_data.append({
                'id': sale.id,
                'pompiste': sale.pompiste.get_full_name(),
                'manager': sale.manager.get_full_name(),
                'type_carburant': sale.type_carburant.nom,
                'quantite': str(sale.quantite),
                'montant_usd': str(sale.montant_usd),
                'montant_fc': str(sale.montant_fc),
                'moyen_paiement': sale.moyen_paiement.nom,
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


class RequestExpenseCategoryView(CaissierRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            if not data.get('nom'):
                return JsonResponse({
                    'success': False,
                    'message': 'Le nom de la catégorie est requis'
                })
            
            # Check if category already exists
            if CategorieDepense.objects.filter(nom=data['nom']).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Cette catégorie existe déjà'
                })
            
            # Create category request (initially inactive, waiting for admin approval)
            category_request = CategorieDepense.objects.create(
                nom=data['nom'],
                description=data.get('description', ''),
                is_active=False,  # Will be activated by admin
                created_by=request.user
            )
            
            # Create notification for admin
            from apps.core.models import Notification
            admin_users = User.objects.filter(role='admin', is_active=True)
            
            for admin in admin_users:
                Notification.objects.create(
                    destinataire=admin,
                    expediteur=request.user,
                    type_notification='system',
                    priorite='normale',
                    titre='Nouvelle demande de catégorie de dépense',
                    message=f'{request.user.get_full_name()} demande la création de la catégorie "{data["nom"]}"',
                    objet_id=category_request.id
                )
            
            return JsonResponse({
                'success': True,
                'message': 'Demande de catégorie envoyée à l\'administrateur pour validation',
                'category_request': {
                    'id': category_request.id,
                    'nom': category_request.nom,
                    'description': category_request.description
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


class SalaryPaymentHistoryView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get filters
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        pompiste_id = request.GET.get('pompiste_id')
        devise = request.GET.get('devise')
        
        # Base query
        payments = PaiementSalaire.objects.filter(
            branche=branche,
            caissier=request.user
        ).select_related('pompiste')
        
        # Apply filters
        if date_start:
            try:
                start_date = datetime.strptime(date_start, '%Y-%m-%d').date()
                payments = payments.filter(date_paiement__date__gte=start_date)
            except ValueError:
                pass
        
        if date_end:
            try:
                end_date = datetime.strptime(date_end, '%Y-%m-%d').date()
                payments = payments.filter(date_paiement__date__lte=end_date)
            except ValueError:
                pass
        
        if pompiste_id:
            payments = payments.filter(pompiste_id=pompiste_id)
        
        if devise:
            payments = payments.filter(devise_paiement=devise)
        
        # Order and paginate
        payments = payments.order_by('-date_paiement')
        paginator = Paginator(payments, 50)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        payments_data = []
        for payment in page_obj:
            payments_data.append({
                'id': payment.id,
                'pompiste': payment.pompiste.get_full_name(),
                'mois_paiement': payment.mois_paiement.strftime('%m/%Y'),
                'montant_paye': str(payment.montant_paye),
                'devise_paiement': payment.devise_paiement,
                'taux_change': str(payment.taux_change),
                'methode_paiement': payment.get_methode_paiement_display(),
                'statut': payment.statut,
                'statut_display': payment.get_statut_display(),
                'notes': payment.notes,
                'date_paiement': payment.date_paiement.strftime('%d/%m/%Y %H:%M')
            })
        
        # Calculate totals
        total_usd = payments.filter(devise_paiement='USD').aggregate(Sum('montant_paye'))['montant_paye__sum'] or 0
        total_fc = payments.filter(devise_paiement='FC').aggregate(Sum('montant_paye'))['montant_paye__sum'] or 0
        
        return JsonResponse({
            'payments': payments_data,
            'summary': {
                'total_payments': payments.count(),
                'total_usd': str(total_usd),
                'total_fc': str(total_fc)
            },
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'total_count': paginator.count
            }
        })


class AbonnePaymentsView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get abonnés who have consumed in this branch and have debt
        abonnes_with_debt = Abonne.objects.filter(
            is_active=True
        ).filter(
            Q(solde_usd__lt=0) | Q(solde_fc__lt=0)
        )
        
        # Filter by search if provided
        search = request.GET.get('search')
        if search:
            abonnes_with_debt = abonnes_with_debt.filter(
                Q(nom_entreprise__icontains=search) |
                Q(code_client__icontains=search) |
                Q(contact_nom__icontains=search)
            )
        
        abonnes_data = []
        for abonne in abonnes_with_debt:
            # Check if abonné has consumed in this branch
            has_consumed_here = ConsommationAbonne.objects.filter(
                abonne=abonne,
                branche=branche
            ).exists()
            
            if has_consumed_here or request.user.role == 'admin':
                # Get recent consumption in this branch
                recent_consumption = ConsommationAbonne.objects.filter(
                    abonne=abonne,
                    branche=branche
                ).order_by('-created_at').first()
                
                debt_usd = abs(float(abonne.solde_usd)) if abonne.solde_usd < 0 else 0
                debt_fc = abs(float(abonne.solde_fc)) if abonne.solde_fc < 0 else 0
                
                abonnes_data.append({
                    'id': abonne.id,
                    'nom_entreprise': abonne.nom_entreprise,
                    'code_client': abonne.code_client,
                    'contact_nom': abonne.contact_nom,
                    'contact_telephone': abonne.contact_telephone,
                    'type_abonnement': abonne.get_type_abonnement_display(),
                    'debt_usd': debt_usd,
                    'debt_fc': debt_fc,
                    'solde_usd': str(abonne.solde_usd),
                    'solde_fc': str(abonne.solde_fc),
                    'recent_consumption': {
                        'date': recent_consumption.created_at.strftime('%d/%m/%Y') if recent_consumption else None,
                        'montant': str(recent_consumption.montant) + ' ' + recent_consumption.devise if recent_consumption else None
                    },
                    'limite_credit': str(abonne.limite_credit)
                })
        
        return JsonResponse({
            'abonnes_with_debt': abonnes_data,
            'branch_info': {
                'nom': branche.nom,
                'code': branche.code
            }
        })


class RegisterAbonnePaymentView(CaissierRequiredMixin, View):
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
            
            # Get abonne
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
            
            # Validate currency and payment method
            if data['devise'] not in ['USD', 'FC']:
                return JsonResponse({
                    'success': False,
                    'message': 'Devise invalide'
                })
            
            if data['methode_paiement'] not in ['cash', 'mobile_money', 'bank']:
                return JsonResponse({
                    'success': False,
                    'message': 'Méthode de paiement invalide'
                })
            
            # Update abonné balance (payment increases balance)
            abonne.update_solde_with_consumption(montant, data['devise'], 'paiement')
            
            # Create expense record (payment received is an income entry, not expense)
            # But we can track it as a special type of transaction
            Depense.objects.create(
                branche=request.user.branche,
                categorie=CategorieDepense.objects.get_or_create(
                    nom='Paiements Abonnés',
                    defaults={'description': 'Paiements reçus des abonnés', 'created_by': request.user}
                )[0],
                created_by=request.user,
                description=f'Paiement reçu de {abonne.nom_entreprise} ({abonne.code_client})',
                montant=-montant,  # Negative amount to indicate income
                devise=data['devise'],
                methode_paiement=data['methode_paiement'],
                beneficiaire=abonne.nom_entreprise,
                statut='approuvee',
                notes=data.get('notes', '')
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Paiement de {montant} {data["devise"]} reçu de {abonne.nom_entreprise}',
                'payment': {
                    'abonne': abonne.nom_entreprise,
                    'montant': str(montant),
                    'devise': data['devise'],
                    'nouveau_solde_usd': str(abonne.solde_usd),
                    'nouveau_solde_fc': str(abonne.solde_fc),
                    'methode_paiement': data.get('methode_paiement'),
                    'date_paiement': timezone.now().strftime('%d/%m/%Y %H:%M')
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


class DailyFinancialReportView(CaissierRequiredMixin, View):
    def get(self, request):
        branche = request.user.branche
        
        # Get target date (default: today)
        target_date = request.GET.get('date')
        if target_date:
            try:
                target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
            except ValueError:
                target_date = timezone.now().date()
        else:
            target_date = timezone.now().date()
        
        # Get validated sales for the day
        daily_sales = Vente.objects.filter(
            branche=branche,
            validated_at__date=target_date,
            caissier=request.user,
            statut__in=['validee', 'manquant']
        )
        
        # Get expenses for the day
        daily_expenses = Depense.objects.filter(
            branche=branche,
            created_at__date=target_date,
            created_by=request.user,
            statut='approuvee'
        )
        
        # Calculate totals
        sales_usd = daily_sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        sales_fc = daily_sales.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        
        expenses_usd = daily_expenses.filter(devise='USD', montant__gt=0).aggregate(Sum('montant'))['montant__sum'] or 0
        expenses_fc = daily_expenses.filter(devise='FC', montant__gt=0).aggregate(Sum('montant'))['montant__sum'] or 0
        
        # Calculate missing amounts
        missing_usd = daily_sales.aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or 0
        missing_fc = daily_sales.aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or 0
        
        # Calculate net (actual money handled)
        net_sales_usd = sales_usd - missing_usd
        net_sales_fc = sales_fc - missing_fc
        
        # Calculate balance
        balance_usd = net_sales_usd - expenses_usd
        balance_fc = net_sales_fc - expenses_fc
        
        # Get payment methods breakdown
        payment_methods_breakdown = {}
        for sale in daily_sales:
            method = sale.moyen_paiement.nom
            if method not in payment_methods_breakdown:
                payment_methods_breakdown[method] = {'usd': 0, 'fc': 0, 'count': 0}
            
            payment_methods_breakdown[method]['usd'] += float(sale.montant_usd - sale.manquant_usd)
            payment_methods_breakdown[method]['fc'] += float(sale.montant_fc - sale.manquant_fc)
            payment_methods_breakdown[method]['count'] += 1
        
        # Get expense categories breakdown
        expense_categories = {}
        for expense in daily_expenses.filter(montant__gt=0):
            category = expense.categorie.nom
            if category not in expense_categories:
                expense_categories[category] = {'usd': 0, 'fc': 0, 'count': 0}
            
            if expense.devise == 'USD':
                expense_categories[category]['usd'] += float(expense.montant)
            else:
                expense_categories[category]['fc'] += float(expense.montant)
            expense_categories[category]['count'] += 1
        
        financial_report = {
            'date': target_date.strftime('%Y-%m-%d'),
            'date_display': target_date.strftime('%d/%m/%Y'),
            'branche': {
                'nom': branche.nom,
                'code': branche.code
            },
            'sales': {
                'gross_usd': str(sales_usd),
                'gross_fc': str(sales_fc),
                'missing_usd': str(missing_usd),
                'missing_fc': str(missing_fc),
                'net_usd': str(net_sales_usd),
                'net_fc': str(net_sales_fc),
                'count': daily_sales.count(),
                'validated_count': daily_sales.filter(statut='validee').count(),
                'missing_count': daily_sales.filter(statut='manquant').count()
            },
            'expenses': {
                'total_usd': str(expenses_usd),
                'total_fc': str(expenses_fc),
                'count': daily_expenses.filter(montant__gt=0).count(),
                'categories': expense_categories
            },
            'balance': {
                'usd': str(balance_usd),
                'fc': str(balance_fc)
            },
            'payment_methods': payment_methods_breakdown,
            'summary': {
                'total_transactions': daily_sales.count() + daily_expenses.filter(montant__gt=0).count(),
                'cash_handling_status': 'balanced' if balance_usd >= 0 and balance_fc >= 0 else 'deficit'
            }
        }
        
        return JsonResponse(financial_report)


class CashReconciliationView(CaissierRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Get target date
            target_date = data.get('date')
            if target_date:
                try:
                    target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
                except ValueError:
                    target_date = timezone.now().date()
            else:
                target_date = timezone.now().date()
            
            # Get physical cash counts
            physical_cash_usd = Decimal(str(data.get('physical_cash_usd', 0)))
            physical_cash_fc = Decimal(str(data.get('physical_cash_fc', 0)))
            
            # Get expected cash from system
            branche = request.user.branche
            
            daily_sales = Vente.objects.filter(
                branche=branche,
                validated_at__date=target_date,
                caissier=request.user,
                statut__in=['validee', 'manquant']
            )
            
            daily_expenses = Depense.objects.filter(
                branche=branche,
                created_at__date=target_date,
                created_by=request.user,
                statut='approuvee',
                montant__gt=0
            )
            
            # Calculate expected cash
            expected_usd = (daily_sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0) - \
                          (daily_sales.aggregate(Sum('manquant_usd'))['manquant_usd__sum'] or 0) - \
                          (daily_expenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0)
            
            expected_fc = (daily_sales.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0) - \
                         (daily_sales.aggregate(Sum('manquant_fc'))['manquant_fc__sum'] or 0) - \
                         (daily_expenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0)
            
            # Calculate differences
            difference_usd = physical_cash_usd - expected_usd
            difference_fc = physical_cash_fc - expected_fc
            
            # Determine reconciliation status
            tolerance_usd = Decimal('5.00')  # 5 USD tolerance
            tolerance_fc = Decimal('5000.00')  # 5000 FC tolerance
            
            is_balanced = (abs(difference_usd) <= tolerance_usd and abs(difference_fc) <= tolerance_fc)
            
            reconciliation_result = {
                'date': target_date.strftime('%Y-%m-%d'),
                'branche': branche.nom,
                'expected_cash': {
                    'usd': str(expected_usd),
                    'fc': str(expected_fc)
                },
                'physical_cash': {
                    'usd': str(physical_cash_usd),
                    'fc': str(physical_cash_fc)
                },
                'differences': {
                    'usd': str(difference_usd),
                    'fc': str(difference_fc)
                },
                'status': 'balanced' if is_balanced else 'unbalanced',
                'tolerance': {
                    'usd': str(tolerance_usd),
                    'fc': str(tolerance_fc)
                },
                'notes': data.get('notes', ''),
                'reconciled_by': request.user.get_full_name(),
                'reconciled_at': timezone.now().strftime('%d/%m/%Y %H:%M')
            }
            
            # If there's a significant difference, create a notification for admin
            if not is_balanced:
                from apps.core.models import Notification
                admin_users = User.objects.filter(role='admin', is_active=True)
                
                for admin in admin_users:
                    Notification.objects.create(
                        destinataire=admin,
                        expediteur=request.user,
                        type_notification='system',
                        priorite='haute',
                        titre='Écart de caisse détecté',
                        message=f'Écart de caisse à {branche.nom} le {target_date.strftime("%d/%m/%Y")}: {difference_usd} USD, {difference_fc} FC'
                    )
            
            return JsonResponse({
                'success': True,
                'reconciliation': reconciliation_result
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de la réconciliation: {str(e)}'
            })