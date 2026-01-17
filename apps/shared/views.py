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