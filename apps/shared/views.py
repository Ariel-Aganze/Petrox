from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View
from apps.core.models import (
    TauxChange, Branche, Pompiste, TypeCarburant, 
    MoyenPaiement, CategorieDepense
)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponse, Http404
from django.views import View
from django.core.files.storage import default_storage
from django.db.models import Q
from apps.core.models import (
    Document, DocumentCategory, PlanningShift, Notification, 
    Abonne, ConsommationAbonne
)
from datetime import datetime, timedelta
import json
from django.db.models import Sum, Q, Count, F
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponse, Http404
from django.views import View
from django.core.files.storage import default_storage
from django.db.models import Q, Sum, Count, F
from django.utils import timezone
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.paginator import Paginator
from django.conf import settings
from apps.core.models import (
    TauxChange, Branche, Pompiste, TypeCarburant, 
    MoyenPaiement, CategorieDepense, Document, DocumentCategory, 
    PlanningShift, Notification, Abonne, ConsommationAbonne, 
    Vente, Depense, Stock, User
)
from datetime import datetime, timedelta
from decimal import Decimal
import json
import csv
import os
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

class CurrentExchangeRateView(LoginRequiredMixin, View):
    def get(self, request):
        """Get current exchange rate"""
        current_rate = TauxChange.objects.filter(is_active=True).first()
        
        if current_rate:
            return JsonResponse({
                'success': True,
                'rate': str(current_rate.taux_usd_fc),
                'date_effective': current_rate.date_effective.strftime('%d/%m/%Y %H:%M'),
                'created_by': current_rate.created_by.get_full_name()
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Aucun taux de change défini',
                'rate': '2800.00'  # Default fallback
            })


class BranchesSelectView(LoginRequiredMixin, View):
    def get(self, request):
        """Get branches for select options"""
        branches = Branche.objects.filter(is_active=True).order_by('nom')
        
        branches_data = []
        for branche in branches:
            branches_data.append({
                'id': branche.id,
                'code': branche.code,
                'nom': branche.nom,
                'ville': branche.ville
            })
        
        return JsonResponse({'branches': branches_data})


class PompistesSelectView(LoginRequiredMixin, View):
    def get(self, request):
        """Get pompistes for select options, filtered by branch if specified"""
        branche_id = request.GET.get('branche_id')
        
        pompistes = Pompiste.objects.filter(is_active=True)
        
        if branche_id:
            pompistes = pompistes.filter(branche_id=branche_id)
        elif hasattr(request.user, 'branche') and request.user.branche:
            # If user has a branch assigned, filter by it
            pompistes = pompistes.filter(branche=request.user.branche)
        
        pompistes = pompistes.order_by('prenom', 'nom')
        
        pompistes_data = []
        for pompiste in pompistes:
            pompistes_data.append({
                'id': pompiste.id,
                'nom': pompiste.get_full_name(),
                'quart': pompiste.get_quart_display(),
                'branche': pompiste.branche.nom
            })
        
        return JsonResponse({'pompistes': pompistes_data})


class TypeCarburantSelectView(LoginRequiredMixin, View):
    def get(self, request):
        """Get fuel types for select options"""
        carburants = TypeCarburant.objects.filter(is_active=True).order_by('nom')
        
        carburants_data = []
        for carburant in carburants:
            carburants_data.append({
                'id': carburant.id,
                'nom': carburant.nom,
                'code': carburant.code,
                'couleur': carburant.couleur_hex
            })
        
        return JsonResponse({'carburants': carburants_data})


class MoyensPaiementSelectView(LoginRequiredMixin, View):
    def get(self, request):
        """Get payment methods for select options"""
        moyens = MoyenPaiement.objects.filter(is_active=True).order_by('nom')
        
        moyens_data = []
        for moyen in moyens:
            moyens_data.append({
                'id': moyen.id,
                'nom': moyen.nom,
                'code': moyen.code
            })
        
        return JsonResponse({'moyens_paiement': moyens_data})


class CategoriesDepenseSelectView(LoginRequiredMixin, View):
    def get(self, request):
        """Get expense categories for select options"""
        categories = CategorieDepense.objects.filter(is_active=True).order_by('nom')
        
        categories_data = []
        for categorie in categories:
            categories_data.append({
                'id': categorie.id,
                'nom': categorie.nom,
                'description': categorie.description
            })
        
        return JsonResponse({'categories': categories_data})


# DOCUMENT MANAGEMENT VIEWS
class DocumentListView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        
        # Base query
        documents = Document.objects.select_related('categorie', 'uploaded_by')
        
        # Filter by visibility and user role
        if user.role == 'admin':
            # Admin sees all documents
            pass
        else:
            # Other users see public documents and their branch documents
            documents = documents.filter(
                Q(visibilite='public') | 
                Q(branches_autorisees=user.branche) |
                Q(uploaded_by=user)
            )
        
        # Apply filters
        categorie_id = request.GET.get('categorie_id')
        if categorie_id:
            documents = documents.filter(categorie_id=categorie_id)
        
        search = request.GET.get('search')
        if search:
            documents = documents.filter(
                Q(titre__icontains=search) | 
                Q(description__icontains=search)
            )
        
        # Order and limit
        documents = documents.order_by('-created_at')[:100]
        
        documents_data = []
        for doc in documents:
            documents_data.append({
                'id': doc.id,
                'titre': doc.titre,
                'description': doc.description,
                'categorie': doc.categorie.nom,
                'visibilite': doc.get_visibilite_display(),
                'taille': doc.get_taille_lisible(),
                'type_fichier': doc.type_fichier,
                'uploaded_by': doc.uploaded_by.get_full_name(),
                'created_at': doc.created_at.strftime('%d/%m/%Y %H:%M'),
                'can_download': True  # Could add more complex logic
            })
        
        return JsonResponse({'documents': documents_data})


class UploadDocumentView(LoginRequiredMixin, View):
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
                })
            
            # Get category
            try:
                categorie = DocumentCategory.objects.get(id=categorie_id, is_active=True)
            except DocumentCategory.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Catégorie introuvable'
                })
            
            # File size limit (10MB)
            if fichier.size > 10 * 1024 * 1024:
                return JsonResponse({
                    'success': False,
                    'message': 'Fichier trop volumineux (max 10MB)'
                })
            
            # Create document
            document = Document.objects.create(
                titre=titre,
                description=description,
                fichier=fichier,
                categorie=categorie,
                visibilite=visibilite,
                uploaded_by=request.user,
                taille_fichier=fichier.size,
                type_fichier=fichier.content_type or 'unknown'
            )
            
            # Handle branch permissions for private documents
            if visibilite == 'prive' and request.user.branche:
                document.branches_autorisees.add(request.user.branche)
            
            return JsonResponse({
                'success': True,
                'message': 'Document uploadé avec succès',
                'document': {
                    'id': document.id,
                    'titre': document.titre,
                    'taille': document.get_taille_lisible()
                }
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de l\'upload: {str(e)}'
            })


class DownloadDocumentView(LoginRequiredMixin, View):
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
                    response['Content-Disposition'] = f'attachment; filename="{document.titre}"'
                    return response
            else:
                raise Http404("Fichier introuvable")
                
        except Document.DoesNotExist:
            raise Http404("Document introuvable")


# PLANNING/SHIFTS MANAGEMENT VIEWS
class PlanningShiftListView(LoginRequiredMixin, View):
    def get(self, request):
        if request.user.role != 'manager' or not request.user.branche:
            return JsonResponse({'success': False, 'message': 'Accès non autorisé'})
        
        branche = request.user.branche
        
        # Get date range (default: current week)
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        
        if not date_start or not date_end:
            today = datetime.now().date()
            # Get current week (Monday to Sunday)
            start_of_week = today - timedelta(days=today.weekday())
            date_start = start_of_week
            date_end = start_of_week + timedelta(days=6)
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        shifts = PlanningShift.objects.filter(
            branche=branche,
            date_shift__gte=date_start,
            date_shift__lte=date_end
        ).select_related('pompiste').order_by('date_shift', 'type_shift')
        
        shifts_data = []
        for shift in shifts:
            shifts_data.append({
                'id': shift.id,
                'pompiste_id': shift.pompiste.id,
                'pompiste_nom': shift.pompiste.get_full_name(),
                'date_shift': shift.date_shift.strftime('%Y-%m-%d'),
                'type_shift': shift.type_shift,
                'type_shift_display': shift.get_type_shift_display(),
                'statut': shift.statut,
                'statut_display': shift.get_statut_display(),
                'heure_debut': shift.heure_debut.strftime('%H:%M'),
                'heure_fin': shift.heure_fin.strftime('%H:%M'),
                'notes': shift.notes
            })
        
        return JsonResponse({
            'shifts': shifts_data,
            'date_start': date_start.strftime('%Y-%m-%d'),
            'date_end': date_end.strftime('%Y-%m-%d')
        })


class CreatePlanningShiftView(LoginRequiredMixin, View):
    def post(self, request):
        if request.user.role != 'manager' or not request.user.branche:
            return JsonResponse({'success': False, 'message': 'Accès non autorisé'})
        
        try:
            data = json.loads(request.body)
            
            pompiste_id = data.get('pompiste_id')
            date_shift = data.get('date_shift')
            type_shift = data.get('type_shift')
            
            if not all([pompiste_id, date_shift, type_shift]):
                return JsonResponse({
                    'success': False,
                    'message': 'Pompiste, date et type de shift requis'
                })
            
            # Get pompiste
            try:
                from apps.core.models import Pompiste
                pompiste = Pompiste.objects.get(
                    id=pompiste_id,
                    branche=request.user.branche,
                    is_active=True
                )
            except Pompiste.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Pompiste introuvable'
                })
            
            # Parse date
            try:
                date_shift_obj = datetime.strptime(date_shift, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': 'Format de date invalide'
                })
            
            # Check if shift already exists
            if PlanningShift.objects.filter(
                pompiste=pompiste,
                date_shift=date_shift_obj,
                type_shift=type_shift
            ).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'Ce shift existe déjà pour ce pompiste'
                })
            
            # Set default hours based on shift type
            if type_shift == 'jour':
                heure_debut = '06:00'
                heure_fin = '18:00'
            else:  # nuit
                heure_debut = '18:00'
                heure_fin = '06:00'
            
            # Create shift
            shift = PlanningShift.objects.create(
                pompiste=pompiste,
                branche=request.user.branche,
                manager=request.user,
                date_shift=date_shift_obj,
                type_shift=type_shift,
                heure_debut=datetime.strptime(heure_debut, '%H:%M').time(),
                heure_fin=datetime.strptime(heure_fin, '%H:%M').time(),
                notes=data.get('notes', ''),
                statut='planifie'
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Shift planifié avec succès',
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
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de la création: {str(e)}'
            })


# ABONNÉS MANAGEMENT VIEWS
class AbonnesListView(LoginRequiredMixin, View):
    def get(self, request):
        # Get filters
        type_abonnement = request.GET.get('type_abonnement')
        search = request.GET.get('search')
        branche_id = request.GET.get('branche_id')
        
        # Base query
        abonnes = Abonne.objects.filter(is_active=True)
        
        # Apply filters
        if type_abonnement:
            abonnes = abonnes.filter(type_abonnement=type_abonnement)
        
        if search:
            abonnes = abonnes.filter(
                Q(nom_entreprise__icontains=search) |
                Q(code_client__icontains=search) |
                Q(contact_nom__icontains=search)
            )
        
        # Role-based filtering
        if request.user.role in ['manager', 'caissier'] and request.user.branche:
            # Show all abonnés but with branch-specific consumption data
            pass  # Abonnés are global, filtering happens in consumption data
        
        abonnes = abonnes.order_by('nom_entreprise')[:100]
        
        abonnes_data = []
        for abonne in abonnes:
            # Calculate branch-specific consumption if user has a branch
            consumption_this_month = 0
            if request.user.branche:
                current_month_start = datetime.now().replace(day=1).date()
                consumption_this_month = ConsommationAbonne.objects.filter(
                    abonne=abonne,
                    branche=request.user.branche,
                    created_at__date__gte=current_month_start
                ).aggregate(Sum('montant'))['montant__sum'] or 0
            
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
                'consumption_this_month': str(consumption_this_month),
                'created_at': abonne.created_at.strftime('%d/%m/%Y')
            })
        
        return JsonResponse({'abonnes': abonnes_data})


class RegisterAbonneConsumptionView(LoginRequiredMixin, View):
    def post(self, request):
        if not request.user.branche:
            return JsonResponse({'success': False, 'message': 'Accès non autorisé'})
        
        try:
            data = json.loads(request.body)
            
            abonne_id = data.get('abonne_id')
            type_carburant_id = data.get('type_carburant_id')
            quantite = data.get('quantite')
            montant = data.get('montant')
            devise = data.get('devise')
            
            if not all([abonne_id, type_carburant_id, quantite, montant, devise]):
                return JsonResponse({
                    'success': False,
                    'message': 'Tous les champs sont requis'
                })
            
            # Get abonne
            try:
                abonne = Abonne.objects.get(id=abonne_id, is_active=True)
            except Abonne.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Abonné introuvable'
                })
            
            # Get type carburant
            try:
                from apps.core.models import TypeCarburant
                type_carburant = TypeCarburant.objects.get(
                    id=type_carburant_id,
                    is_active=True
                )
            except TypeCarburant.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Type de carburant introuvable'
                })
            
            # Convert to decimals
            try:
                quantite = Decimal(str(quantite))
                montant = Decimal(str(montant))
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'message': 'Quantité et montant invalides'
                })
            
            # Check if abonné can consume this amount
            if not abonne.peut_consommer(montant, devise):
                return JsonResponse({
                    'success': False,
                    'message': 'Solde insuffisant ou limite de crédit dépassée'
                })
            
            # Create consumption record
            consumption = ConsommationAbonne.objects.create(
                abonne=abonne,
                branche=request.user.branche,
                type_carburant=type_carburant,
                quantite=quantite,
                montant=montant,
                devise=devise
            )
            
            # Update abonné balance
            abonne.update_solde_with_consumption(montant, devise, 'consommation')
            
            return JsonResponse({
                'success': True,
                'message': f'Consommation enregistrée pour {abonne.nom_entreprise}',
                'consumption': {
                    'id': consumption.id,
                    'quantite': str(quantite),
                    'montant': str(montant),
                    'devise': devise,
                    'nouveau_solde_usd': str(abonne.solde_usd),
                    'nouveau_solde_fc': str(abonne.solde_fc)
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


# NOTIFICATIONS MANAGEMENT
class NotificationListView(LoginRequiredMixin, View):
    def get(self, request):
        notifications = Notification.objects.filter(
            destinataire=request.user
        ).order_by('-created_at')[:50]
        
        notifications_data = []
        for notif in notifications:
            notifications_data.append({
                'id': notif.id,
                'titre': notif.titre,
                'message': notif.message,
                'type': notif.type_notification,
                'priorite': notif.priorite,
                'lu': notif.lu,
                'created_at': notif.created_at.strftime('%d/%m/%Y %H:%M'),
                'lien_url': notif.lien_url
            })
        
        # Count unread notifications
        unread_count = Notification.objects.filter(
            destinataire=request.user,
            lu=False
        ).count()
        
        return JsonResponse({
            'notifications': notifications_data,
            'unread_count': unread_count
        })


class MarkNotificationReadView(LoginRequiredMixin, View):
    def post(self, request, notification_id):
        try:
            notification = Notification.objects.get(
                id=notification_id,
                destinataire=request.user
            )
            notification.marquer_comme_lu()
            
            return JsonResponse({'success': True})
            
        except Notification.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Notification introuvable'})
        


# DOCUMENT MANAGEMENT VIEWS (add to existing ones)
class DocumentCategoriesListView(LoginRequiredMixin, View):
    def get(self, request):
        categories = DocumentCategory.objects.filter(is_active=True).order_by('nom')
        
        categories_data = []
        for category in categories:
            # Count documents in this category
            doc_count = Document.objects.filter(categorie=category).count()
            
            categories_data.append({
                'id': category.id,
                'nom': category.nom,
                'description': category.description,
                'document_count': doc_count,
                'created_by': category.created_by.get_full_name(),
                'created_at': category.created_at.strftime('%d/%m/%Y')
            })
        
        return JsonResponse({'categories': categories_data})


class UpdatePlanningShiftView(LoginRequiredMixin, View):
    def post(self, request, shift_id):
        if request.user.role != 'manager' or not request.user.branche:
            return JsonResponse({'success': False, 'message': 'Accès non autorisé'})
        
        try:
            data = json.loads(request.body)
            
            try:
                shift = PlanningShift.objects.get(
                    id=shift_id,
                    branche=request.user.branche
                )
            except PlanningShift.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Shift introuvable'
                })
            
            # Update shift details
            if data.get('statut'):
                shift.statut = data['statut']
            
            if data.get('notes') is not None:
                shift.notes = data['notes']
            
            if data.get('heure_debut'):
                try:
                    shift.heure_debut = datetime.strptime(data['heure_debut'], '%H:%M').time()
                except ValueError:
                    pass
            
            if data.get('heure_fin'):
                try:
                    shift.heure_fin = datetime.strptime(data['heure_fin'], '%H:%M').time()
                except ValueError:
                    pass
            
            shift.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Shift mis à jour avec succès',
                'shift': {
                    'id': shift.id,
                    'statut': shift.get_statut_display(),
                    'heure_debut': shift.heure_debut.strftime('%H:%M'),
                    'heure_fin': shift.heure_fin.strftime('%H:%M')
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


class DeletePlanningShiftView(LoginRequiredMixin, View):
    def delete(self, request, shift_id):
        if request.user.role != 'manager' or not request.user.branche:
            return JsonResponse({'success': False, 'message': 'Accès non autorisé'})
        
        try:
            shift = PlanningShift.objects.get(
                id=shift_id,
                branche=request.user.branche
            )
            
            pompiste_name = shift.pompiste.get_full_name()
            date_shift = shift.date_shift.strftime('%d/%m/%Y')
            type_shift = shift.get_type_shift_display()
            
            shift.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Shift {type_shift} du {date_shift} pour {pompiste_name} supprimé'
            })
            
        except PlanningShift.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Shift introuvable'
            })


class AbonneConsumptionHistoryView(LoginRequiredMixin, View):
    def get(self, request, abonne_id):
        try:
            abonne = Abonne.objects.get(id=abonne_id)
        except Abonne.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Abonné introuvable'})
        
        # Get filters
        branche_id = request.GET.get('branche_id')
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        
        # Base query
        consumptions = ConsommationAbonne.objects.filter(
            abonne=abonne
        ).select_related('branche', 'type_carburant').order_by('-created_at')
        
        # Apply filters
        if branche_id and branche_id != 'all':
            consumptions = consumptions.filter(branche_id=branche_id)
        elif request.user.branche and request.user.role in ['manager', 'caissier']:
            # Non-admin users see only their branch
            consumptions = consumptions.filter(branche=request.user.branche)
        
        if date_start:
            try:
                start_date = datetime.strptime(date_start, '%Y-%m-%d').date()
                consumptions = consumptions.filter(created_at__date__gte=start_date)
            except ValueError:
                pass
        
        if date_end:
            try:
                end_date = datetime.strptime(date_end, '%Y-%m-%d').date()
                consumptions = consumptions.filter(created_at__date__lte=end_date)
            except ValueError:
                pass
        
        # Paginate
        paginator = Paginator(consumptions, 50)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        history_data = []
        for consumption in page_obj:
            history_data.append({
                'id': consumption.id,
                'branche': consumption.branche.nom,
                'branche_code': consumption.branche.code,
                'type_carburant': consumption.type_carburant.nom,
                'quantite': str(consumption.quantite),
                'montant': str(consumption.montant),
                'devise': consumption.devise,
                'created_at': consumption.created_at.strftime('%d/%m/%Y %H:%M')
            })
        
        # Calculate summary
        total_usd = consumptions.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        total_fc = consumptions.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        return JsonResponse({
            'abonne': {
                'id': abonne.id,
                'nom_entreprise': abonne.nom_entreprise,
                'code_client': abonne.code_client,
                'type_abonnement': abonne.get_type_abonnement_display()
            },
            'summary': {
                'total_transactions': consumptions.count(),
                'total_usd': str(total_usd),
                'total_fc': str(total_fc)
            },
            'history': history_data,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'total_count': paginator.count
            }
        })


class RegisterAbonnePaymentView(LoginRequiredMixin, View):
    def post(self, request, abonne_id):
        if request.user.role not in ['caissier', 'admin']:
            return JsonResponse({'success': False, 'message': 'Accès non autorisé'})
        
        try:
            data = json.loads(request.body)
            
            # Get abonne
            try:
                abonne = Abonne.objects.get(id=abonne_id, is_active=True)
            except Abonne.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'Abonné introuvable'
                })
            
            # Validate required fields
            required_fields = ['montant', 'devise', 'methode_paiement']
            for field in required_fields:
                if not data.get(field):
                    return JsonResponse({
                        'success': False,
                        'message': f'Le champ {field} est requis'
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
            
            # Update abonné balance
            abonne.update_solde_with_consumption(montant, data['devise'], 'paiement')
            
            # Create a positive expense record (income)
            if request.user.branche:
                Depense.objects.create(
                    branche=request.user.branche,
                    categorie=CategorieDepense.objects.get_or_create(
                        nom='Paiements Abonnés',
                        defaults={
                            'description': 'Paiements reçus des abonnés',
                            'created_by': request.user
                        }
                    )[0],
                    created_by=request.user,
                    description=f'Paiement reçu de {abonne.nom_entreprise}',
                    montant=-montant,  # Negative to indicate income
                    devise=data['devise'],
                    methode_paiement=data['methode_paiement'],
                    beneficiaire=abonne.nom_entreprise,
                    notes=data.get('notes', ''),
                    statut='approuvee'
                )
            
            return JsonResponse({
                'success': True,
                'message': f'Paiement de {montant} {data["devise"]} reçu',
                'payment': {
                    'abonne': abonne.nom_entreprise,
                    'montant': str(montant),
                    'devise': data['devise'],
                    'nouveau_solde_usd': str(abonne.solde_usd),
                    'nouveau_solde_fc': str(abonne.solde_fc)
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


class MarkAllNotificationsReadView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            updated_count = Notification.objects.filter(
                destinataire=request.user,
                lu=False
            ).update(
                lu=True,
                date_lecture=timezone.now()
            )
            
            return JsonResponse({
                'success': True,
                'message': f'{updated_count} notifications marquées comme lues'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            })


# USER PROFILE MANAGEMENT
class UserProfileView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        
        profile_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'prenom': user.prenom,
            'nom': user.nom,
            'telephone': user.telephone,
            'date_naissance': user.date_naissance.strftime('%Y-%m-%d') if user.date_naissance else None,
            'adresse': user.adresse,
            'role': user.role,
            'role_display': user.get_role_display(),
            'branche': {
                'id': user.branche.id,
                'nom': user.branche.nom,
                'code': user.branche.code
            } if user.branche else None,
            'salaire': str(user.salaire) if user.salaire else None,
            'devise_salaire': user.devise_salaire,
            'last_login': user.last_login.strftime('%d/%m/%Y %H:%M') if user.last_login else None,
            'date_joined': user.date_joined.strftime('%d/%m/%Y'),
            'is_active': user.is_active
        }
        
        return JsonResponse({'profile': profile_data})


class UpdateProfileView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            user = request.user
            
            # Update allowed fields
            if data.get('prenom'):
                user.prenom = data['prenom']
            
            if data.get('nom'):
                user.nom = data['nom']
            
            if data.get('email'):
                # Check if email already exists
                if User.objects.filter(email=data['email']).exclude(id=user.id).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'Cette adresse email est déjà utilisée'
                    })
                user.email = data['email']
            
            if data.get('telephone'):
                user.telephone = data['telephone']
            
            if data.get('date_naissance'):
                try:
                    user.date_naissance = datetime.strptime(data['date_naissance'], '%Y-%m-%d').date()
                except ValueError:
                    pass
            
            if data.get('adresse') is not None:
                user.adresse = data['adresse']
            
            user.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Profil mis à jour avec succès',
                'profile': {
                    'name': user.get_full_name(),
                    'email': user.email,
                    'telephone': user.telephone
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


class ChangePasswordView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            old_password = data.get('old_password')
            new_password = data.get('new_password')
            confirm_password = data.get('confirm_password')
            
            if not all([old_password, new_password, confirm_password]):
                return JsonResponse({
                    'success': False,
                    'message': 'Tous les champs sont requis'
                })
            
            # Check old password
            if not request.user.check_password(old_password):
                return JsonResponse({
                    'success': False,
                    'message': 'Ancien mot de passe incorrect'
                })
            
            # Check new password confirmation
            if new_password != confirm_password:
                return JsonResponse({
                    'success': False,
                    'message': 'Les nouveaux mots de passe ne correspondent pas'
                })
            
            # Check password length
            if len(new_password) < 8:
                return JsonResponse({
                    'success': False,
                    'message': 'Le mot de passe doit contenir au moins 8 caractères'
                })
            
            # Update password
            request.user.set_password(new_password)
            request.user.save()
            
            # Keep user logged in
            update_session_auth_hash(request, request.user)
            
            return JsonResponse({
                'success': True,
                'message': 'Mot de passe modifié avec succès'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Données JSON invalides'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur lors de la modification: {str(e)}'
            })


# REPORTS AND ANALYTICS
class SalesReportView(LoginRequiredMixin, View):
    def get(self, request):
        # Get filters
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        branche_id = request.GET.get('branche_id')
        type_carburant_id = request.GET.get('type_carburant_id')
        pompiste_id = request.GET.get('pompiste_id')
        
        # Default date range (last 30 days)
        if not date_start or not date_end:
            today = timezone.now().date()
            date_start = today - timedelta(days=30)
            date_end = today
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Base query
        sales = Vente.objects.filter(
            created_at__date__gte=date_start,
            created_at__date__lte=date_end,
            statut='validee'
        ).select_related('branche', 'pompiste', 'type_carburant')
        
        # Apply role-based filtering
        if request.user.role in ['manager', 'caissier'] and request.user.branche:
            sales = sales.filter(branche=request.user.branche)
        elif branche_id and branche_id != 'all':
            sales = sales.filter(branche_id=branche_id)
        
        # Apply other filters
        if type_carburant_id:
            sales = sales.filter(type_carburant_id=type_carburant_id)
        
        if pompiste_id:
            sales = sales.filter(pompiste_id=pompiste_id)
        
        # Calculate summary
        total_sales_usd = sales.aggregate(Sum('montant_usd'))['montant_usd__sum'] or 0
        total_sales_fc = sales.aggregate(Sum('montant_fc'))['montant_fc__sum'] or 0
        total_quantity = sales.aggregate(Sum('quantite'))['quantite__sum'] or 0
        
        # Group by branch
        branch_summary = {}
        branch_sales = sales.values('branche__nom', 'branche__code').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            total_qty=Sum('quantite'),
            count=Count('id')
        )
        
        for branch in branch_sales:
            branch_summary[branch['branche__code']] = {
                'nom': branch['branche__nom'],
                'total_usd': str(branch['total_usd']),
                'total_fc': str(branch['total_fc']),
                'total_quantity': str(branch['total_qty']),
                'transactions': branch['count']
            }
        
        # Group by fuel type
        fuel_summary = {}
        fuel_sales = sales.values('type_carburant__nom').annotate(
            total_usd=Sum('montant_usd'),
            total_fc=Sum('montant_fc'),
            total_qty=Sum('quantite'),
            count=Count('id')
        )
        
        for fuel in fuel_sales:
            fuel_summary[fuel['type_carburant__nom']] = {
                'total_usd': str(fuel['total_usd']),
                'total_fc': str(fuel['total_fc']),
                'total_quantity': str(fuel['total_qty']),
                'transactions': fuel['count']
            }
        
        return JsonResponse({
            'period': {
                'start': date_start.strftime('%Y-%m-%d'),
                'end': date_end.strftime('%Y-%m-%d')
            },
            'summary': {
                'total_sales_usd': str(total_sales_usd),
                'total_sales_fc': str(total_sales_fc),
                'total_quantity': str(total_quantity),
                'total_transactions': sales.count()
            },
            'branch_breakdown': branch_summary,
            'fuel_breakdown': fuel_summary
        })


class ExpensesReportView(LoginRequiredMixin, View):
    def get(self, request):
        # Get filters
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        branche_id = request.GET.get('branche_id')
        categorie_id = request.GET.get('categorie_id')
        devise = request.GET.get('devise')
        
        # Default date range (last 30 days)
        if not date_start or not date_end:
            today = timezone.now().date()
            date_start = today - timedelta(days=30)
            date_end = today
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Base query
        expenses = Depense.objects.filter(
            created_at__date__gte=date_start,
            created_at__date__lte=date_end,
            statut='approuvee'
        ).select_related('branche', 'categorie', 'created_by')
        
        # Apply role-based filtering
        if request.user.role in ['manager', 'caissier'] and request.user.branche:
            expenses = expenses.filter(branche=request.user.branche)
        elif branche_id and branche_id != 'all':
            expenses = expenses.filter(branche_id=branche_id)
        
        # Apply other filters
        if categorie_id:
            expenses = expenses.filter(categorie_id=categorie_id)
        
        if devise:
            expenses = expenses.filter(devise=devise)
        
        # Calculate summary
        total_expenses_usd = expenses.filter(devise='USD').aggregate(Sum('montant'))['montant__sum'] or 0
        total_expenses_fc = expenses.filter(devise='FC').aggregate(Sum('montant'))['montant__sum'] or 0
        
        # Group by category
        category_summary = {}
        category_expenses = expenses.values('categorie__nom').annotate(
            total_usd=Sum('montant', filter=Q(devise='USD')),
            total_fc=Sum('montant', filter=Q(devise='FC')),
            count=Count('id')
        )
        
        for category in category_expenses:
            category_summary[category['categorie__nom']] = {
                'total_usd': str(category['total_usd'] or 0),
                'total_fc': str(category['total_fc'] or 0),
                'transactions': category['count']
            }
        
        # Group by branch
        branch_summary = {}
        if request.user.role == 'admin':
            branch_expenses = expenses.values('branche__nom', 'branche__code').annotate(
                total_usd=Sum('montant', filter=Q(devise='USD')),
                total_fc=Sum('montant', filter=Q(devise='FC')),
                count=Count('id')
            )
            
            for branch in branch_expenses:
                branch_summary[branch['branche__code']] = {
                    'nom': branch['branche__nom'],
                    'total_usd': str(branch['total_usd'] or 0),
                    'total_fc': str(branch['total_fc'] or 0),
                    'transactions': branch['count']
                }
        
        return JsonResponse({
            'period': {
                'start': date_start.strftime('%Y-%m-%d'),
                'end': date_end.strftime('%Y-%m-%d')
            },
            'summary': {
                'total_expenses_usd': str(total_expenses_usd),
                'total_expenses_fc': str(total_expenses_fc),
                'total_transactions': expenses.count()
            },
            'category_breakdown': category_summary,
            'branch_breakdown': branch_summary
        })


class StockReportView(LoginRequiredMixin, View):
    def get(self, request):
        branche_id = request.GET.get('branche_id')
        
        # Base query
        stock_items = Stock.objects.select_related('branche', 'type_carburant')
        
        # Apply role-based filtering
        if request.user.role in ['manager', 'caissier'] and request.user.branche:
            stock_items = stock_items.filter(branche=request.user.branche)
        elif branche_id and branche_id != 'all':
            stock_items = stock_items.filter(branche_id=branche_id)
        
        # Calculate summary
        total_current_stock = stock_items.aggregate(Sum('quantite_actuelle'))['quantite_actuelle__sum'] or 0
        total_capacity = stock_items.aggregate(Sum('capacite_max'))['capacite_max__sum'] or 0
        
        # Count alerts
        low_stock_count = stock_items.filter(quantite_actuelle__lte=F('seuil_alerte')).count()
        critical_stock_count = stock_items.filter(
            quantite_actuelle__lte=F('seuil_alerte') * 0.5
        ).count()
        
        # Group by fuel type
        fuel_summary = {}
        fuel_stock = stock_items.values('type_carburant__nom').annotate(
            total_stock=Sum('quantite_actuelle'),
            total_capacity=Sum('capacite_max'),
            branch_count=Count('branche', distinct=True)
        )
        
        for fuel in fuel_stock:
            fuel_summary[fuel['type_carburant__nom']] = {
                'total_stock': str(fuel['total_stock']),
                'total_capacity': str(fuel['total_capacity']),
                'branch_count': fuel['branch_count'],
                'fill_percentage': round((fuel['total_stock'] / fuel['total_capacity'] * 100), 1) if fuel['total_capacity'] > 0 else 0
            }
        
        # Group by branch
        branch_summary = {}
        if request.user.role == 'admin':
            branch_stock = stock_items.values('branche__nom', 'branche__code').annotate(
                total_stock=Sum('quantite_actuelle'),
                total_capacity=Sum('capacite_max'),
                fuel_types=Count('type_carburant', distinct=True),
                alerts=Count('id', filter=Q(quantite_actuelle__lte=F('seuil_alerte')))
            )
            
            for branch in branch_stock:
                branch_summary[branch['branche__code']] = {
                    'nom': branch['branche__nom'],
                    'total_stock': str(branch['total_stock']),
                    'total_capacity': str(branch['total_capacity']),
                    'fuel_types': branch['fuel_types'],
                    'alerts': branch['alerts'],
                    'fill_percentage': round((branch['total_stock'] / branch['total_capacity'] * 100), 1) if branch['total_capacity'] > 0 else 0
                }
        
        return JsonResponse({
            'summary': {
                'total_current_stock': str(total_current_stock),
                'total_capacity': str(total_capacity),
                'overall_fill_percentage': round((total_current_stock / total_capacity * 100), 1) if total_capacity > 0 else 0,
                'low_stock_alerts': low_stock_count,
                'critical_stock_alerts': critical_stock_count,
                'total_locations': stock_items.count()
            },
            'fuel_breakdown': fuel_summary,
            'branch_breakdown': branch_summary
        })


class ExportReportView(LoginRequiredMixin, View):
    def get(self, request, report_type):
        # Get the same filters used in regular reports
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        branche_id = request.GET.get('branche_id')
        
        # Default date range
        if not date_start or not date_end:
            today = timezone.now().date()
            date_start = today - timedelta(days=30)
            date_end = today
        else:
            date_start = datetime.strptime(date_start, '%Y-%m-%d').date()
            date_end = datetime.strptime(date_end, '%Y-%m-%d').date()
        
        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{report_type}_{date_start}_to_{date_end}.csv"'
        
        writer = csv.writer(response)
        
        if report_type == 'sales':
            # Export sales report
            sales = Vente.objects.filter(
                created_at__date__gte=date_start,
                created_at__date__lte=date_end,
                statut='validee'
            ).select_related('branche', 'pompiste', 'type_carburant', 'manager', 'caissier')
            
            # Apply role-based filtering
            if request.user.role in ['manager', 'caissier'] and request.user.branche:
                sales = sales.filter(branche=request.user.branche)
            elif branche_id and branche_id != 'all':
                sales = sales.filter(branche_id=branche_id)
            
            # Write header
            writer.writerow([
                'ID', 'Date', 'Heure', 'Branche', 'Pompiste', 'Manager', 'Caissier',
                'Carburant', 'Quantité (L)', 'Montant USD', 'Montant FC', 'Taux Change'
            ])
            
            # Write data
            for sale in sales:
                writer.writerow([
                    sale.id,
                    sale.created_at.strftime('%d/%m/%Y'),
                    sale.created_at.strftime('%H:%M'),
                    sale.branche.nom,
                    sale.pompiste.get_full_name(),
                    sale.manager.get_full_name(),
                    sale.caissier.get_full_name() if sale.caissier else '',
                    sale.type_carburant.nom,
                    str(sale.quantite),
                    str(sale.montant_usd),
                    str(sale.montant_fc),
                    str(sale.taux_change)
                ])
        
        elif report_type == 'expenses':
            # Export expenses report
            expenses = Depense.objects.filter(
                created_at__date__gte=date_start,
                created_at__date__lte=date_end,
                statut='approuvee'
            ).select_related('branche', 'categorie', 'created_by')
            
            # Apply role-based filtering
            if request.user.role in ['manager', 'caissier'] and request.user.branche:
                expenses = expenses.filter(branche=request.user.branche)
            elif branche_id and branche_id != 'all':
                expenses = expenses.filter(branche_id=branche_id)
            
            # Write header
            writer.writerow([
                'ID', 'Date', 'Heure', 'Branche', 'Catégorie', 'Description',
                'Montant', 'Devise', 'Méthode', 'Bénéficiaire', 'Créé par'
            ])
            
            # Write data
            for expense in expenses:
                writer.writerow([
                    expense.id,
                    expense.created_at.strftime('%d/%m/%Y'),
                    expense.created_at.strftime('%H:%M'),
                    expense.branche.nom,
                    expense.categorie.nom,
                    expense.description,
                    str(expense.montant),
                    expense.devise,
                    expense.get_methode_paiement_display(),
                    expense.beneficiaire,
                    expense.created_by.get_full_name()
                ])
        
        elif report_type == 'stock':
            # Export stock report
            stock_items = Stock.objects.select_related('branche', 'type_carburant')
            
            # Apply role-based filtering
            if request.user.role in ['manager', 'caissier'] and request.user.branche:
                stock_items = stock_items.filter(branche=request.user.branche)
            elif branche_id and branche_id != 'all':
                stock_items = stock_items.filter(branche_id=branche_id)
            
            # Write header
            writer.writerow([
                'Branche', 'Code Branche', 'Carburant', 'Quantité Actuelle (L)',
                'Capacité Max (L)', 'Seuil Alerte (L)', '% Remplissage',
                'Niveau Alerte', 'Prix Achat (USD/L)', 'Dernière MAJ'
            ])
            
            # Write data
            for stock in stock_items:
                writer.writerow([
                    stock.branche.nom,
                    stock.branche.code,
                    stock.type_carburant.nom,
                    str(stock.quantite_actuelle),
                    str(stock.capacite_max),
                    str(stock.seuil_alerte),
                    f"{stock.pourcentage_rempli:.1f}%",
                    stock.niveau_alerte,
                    str(stock.prix_achat) if stock.prix_achat else '',
                    stock.updated_at.strftime('%d/%m/%Y %H:%M')
                ])
        
        else:
            # Invalid report type
            return JsonResponse({
                'success': False,
                'message': 'Type de rapport invalide'
            })
        
        return response
    
class UserProfilePageView(LoginRequiredMixin, TemplateView):
    """User profile page"""
    template_name = 'shared/profil.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # User is already in context from base template
        return context


class UploadProfilePhotoView(LoginRequiredMixin, View):
    """Upload profile photo"""
    
    def post(self, request):
        try:
            photo = request.FILES.get('photo')
            
            if not photo:
                return JsonResponse({
                    'success': False,
                    'message': 'Aucune photo fournie'
                }, status=400)
            
            # Validate file type
            if not photo.content_type.startswith('image/'):
                return JsonResponse({
                    'success': False,
                    'message': 'Le fichier doit être une image'
                }, status=400)
            
            # Validate file size (5MB max)
            if photo.size > 5 * 1024 * 1024:
                return JsonResponse({
                    'success': False,
                    'message': 'La taille de l\'image ne doit pas dépasser 5MB'
                }, status=400)
            
            # Delete old photo if exists
            if request.user.photo:
                old_photo_path = request.user.photo.path
                if default_storage.exists(old_photo_path):
                    default_storage.delete(old_photo_path)
            
            # Save new photo
            request.user.photo = photo
            request.user.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Photo mise à jour avec succès',
                'photo_url': request.user.photo.url
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erreur: {str(e)}'
            }, status=500)