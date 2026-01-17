# apps/core/admin.py - FINAL CORRECTED VERSION
# This matches your ACTUAL current model structure

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, Branche, TypeCarburant, TauxChange, Pompiste, CategorieDepense, 
    MoyenPaiement, Abonne, Stock, Vente, Depense, Livraison, 
    ConsommationAbonne, PaiementSalaire
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('username', 'email', 'prenom', 'nom', 'role', 'branche', 'is_active')
    list_filter = ('role', 'branche', 'is_active', 'date_joined')
    search_fields = ('username', 'email', 'prenom', 'nom')
    ordering = ('prenom', 'nom')
    
    fieldsets = UserAdmin.fieldsets + (
        ('Informations Personnelles', {
            'fields': ('prenom', 'nom', 'telephone', 'date_naissance', 'photo', 'adresse')
        }),
        ('Informations Professionnelles', {
            'fields': ('role', 'branche', 'salaire', 'devise_salaire', 'contrat')
        }),
    )


@admin.register(Branche)
class BrancheAdmin(admin.ModelAdmin):
    list_display = ('nom', 'code', 'ville', 'province', 'responsable', 'is_active', 'created_at')
    list_filter = ('ville', 'province', 'is_active', 'created_at')
    search_fields = ('nom', 'code', 'ville')
    ordering = ('nom',)
    date_hierarchy = 'created_at'


@admin.register(TypeCarburant)
class TypeCarburantAdmin(admin.ModelAdmin):
    list_display = ('nom', 'code', 'couleur_hex', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('nom', 'code')
    ordering = ('nom',)


@admin.register(TauxChange)
class TauxChangeAdmin(admin.ModelAdmin):
    list_display = ('taux_usd_fc', 'date_effective', 'created_by', 'is_active', 'created_at')
    list_filter = ('is_active', 'date_effective', 'created_by')
    readonly_fields = ('created_at',)
    ordering = ('-date_effective',)
    date_hierarchy = 'date_effective'


@admin.register(Pompiste)
class PompisteAdmin(admin.ModelAdmin):
    list_display = ('prenom', 'nom', 'branche', 'quart', 'salaire', 'devise_salaire', 'is_active')
    list_filter = ('branche', 'quart', 'devise_salaire', 'is_active')
    search_fields = ('prenom', 'nom', 'telephone')
    ordering = ('branche', 'nom', 'prenom')


@admin.register(CategorieDepense)
class CategorieDepenseAdmin(admin.ModelAdmin):
    # FINAL FIX: Use only the fields that ACTUALLY exist in your current model
    list_display = ('nom', 'description', 'is_active')  # Removed created_at
    list_filter = ('is_active',)  # Removed created_at and created_by
    search_fields = ('nom', 'description')
    ordering = ('nom',)


@admin.register(MoyenPaiement)
class MoyenPaiementAdmin(admin.ModelAdmin):
    list_display = ('nom', 'code', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('nom', 'code')
    ordering = ('nom',)


@admin.register(Abonne)
class AbonneAdmin(admin.ModelAdmin):
    list_display = ('nom_entreprise', 'code_client', 'type_abonnement', 'solde_usd', 'solde_fc', 'is_active')
    list_filter = ('type_abonnement', 'is_active', 'created_at')
    search_fields = ('nom_entreprise', 'code_client', 'contact_nom')
    ordering = ('nom_entreprise',)
    
    fieldsets = (
        ('Informations Entreprise', {
            'fields': ('nom_entreprise', 'code_client', 'adresse')
        }),
        ('Contact', {
            'fields': ('contact_nom', 'contact_telephone', 'contact_email')
        }),
        ('Abonnement', {
            'fields': ('type_abonnement', 'solde_usd', 'solde_fc', 'limite_credit', 'is_active')
        }),
    )


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('branche', 'type_carburant', 'quantite_actuelle', 'capacite_max', 'seuil_alerte', 'niveau_alerte_display', 'pourcentage_rempli_display')
    list_filter = ('branche', 'type_carburant', 'updated_at')
    search_fields = ('branche__nom', 'type_carburant__nom')
    ordering = ('branche', 'type_carburant')
    
    def niveau_alerte_display(self, obj):
        niveau = obj.niveau_alerte
        colors = {
            'critique': 'red',
            'bas': 'orange', 
            'normal': 'green'
        }
        return f'<span style="color: {colors.get(niveau, "black")};">{niveau.title()}</span>'
    niveau_alerte_display.allow_tags = True
    niveau_alerte_display.short_description = 'Niveau'
    
    def pourcentage_rempli_display(self, obj):
        return f"{obj.pourcentage_rempli:.1f}%"
    pourcentage_rempli_display.short_description = 'Remplissage'


@admin.register(Vente)
class VenteAdmin(admin.ModelAdmin):
    list_display = ('id', 'branche', 'pompiste', 'type_carburant', 'quantite', 'montant_usd', 'montant_fc', 'statut', 'created_at')
    list_filter = ('branche', 'type_carburant', 'statut', 'moyen_paiement', 'created_at', 'validated_at')
    search_fields = ('pompiste__prenom', 'pompiste__nom', 'abonne__nom_entreprise')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Informations de base', {
            'fields': ('branche', 'pompiste', 'manager', 'caissier', 'abonne')
        }),
        ('Détails de la vente', {
            'fields': ('type_carburant', 'quantite', 'moyen_paiement', 'observations')
        }),
        ('Montants et taux', {
            'fields': ('montant_usd', 'montant_fc', 'taux_change')
        }),
        ('Validation', {
            'fields': ('statut', 'manquant_usd', 'manquant_fc', 'raison_manquant')
        }),
    )
    
    readonly_fields = ('created_at', 'validated_at')


@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'branche', 'categorie', 'description', 'montant', 'devise', 'statut', 'created_by', 'created_at')
    list_filter = ('branche', 'categorie', 'devise', 'statut', 'methode_paiement', 'created_at')
    search_fields = ('description', 'beneficiaire', 'created_by__username')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Informations de base', {
            'fields': ('branche', 'categorie', 'created_by')
        }),
        ('Détails de la dépense', {
            'fields': ('description', 'montant', 'devise', 'methode_paiement', 'beneficiaire')
        }),
        ('Validation et documents', {
            'fields': ('statut', 'justificatif', 'notes')
        }),
    )


@admin.register(Livraison)
class LivraisonAdmin(admin.ModelAdmin):
    list_display = ('id', 'branche', 'type_carburant', 'quantite', 'fournisseur', 'statut', 'date_livraison', 'manager')
    list_filter = ('branche', 'type_carburant', 'statut', 'fournisseur', 'date_livraison')
    search_fields = ('fournisseur', 'reference_document', 'manager__username')
    ordering = ('-date_livraison',)
    date_hierarchy = 'date_livraison'


@admin.register(ConsommationAbonne)
class ConsommationAbonneAdmin(admin.ModelAdmin):
    list_display = ('abonne', 'branche', 'type_carburant', 'quantite', 'montant', 'devise', 'created_at')
    list_filter = ('branche', 'type_carburant', 'devise', 'created_at')
    search_fields = ('abonne__nom_entreprise', 'abonne__code_client')
    ordering = ('-created_at',)


@admin.register(PaiementSalaire)
class PaiementSalaireAdmin(admin.ModelAdmin):
    list_display = ('get_pompiste', 'branche', 'montant_paye', 'devise_paiement', 'get_mois_paiement', 'caissier', 'date_paiement')
    list_filter = ('branche', 'devise_paiement', 'statut', 'date_paiement')
    search_fields = ('pompiste__nom', 'pompiste__prenom', 'notes')
    ordering = ('-date_paiement',)
    date_hierarchy = 'date_paiement'
    
    def get_pompiste(self, obj):
        return obj.pompiste.get_full_name()
    get_pompiste.short_description = 'Pompiste'
    
    def get_mois_paiement(self, obj):
        return obj.mois_paiement.strftime('%m/%Y')
    get_mois_paiement.short_description = 'Mois'