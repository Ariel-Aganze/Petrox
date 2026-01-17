from django import forms
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from apps.core.models import (
    Branche, TypeCarburant, Pompiste, CategorieDepense,
    MoyenPaiement, User, Abonne
)


# COMMON FILTER FORMS
class DateRangeForm(forms.Form):
    """Base form for date range filtering"""
    
    date_start = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        label="Date de début"
    )
    date_end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        }),
        label="Date de fin"
    )

    def clean(self):
        cleaned_data = super().clean()
        date_start = cleaned_data.get('date_start')
        date_end = cleaned_data.get('date_end')

        if date_start and date_end:
            if date_start > date_end:
                raise ValidationError(
                    "La date de début ne peut pas être postérieure à la date de fin."
                )
            
            # Check if date range is not too large (max 1 year)
            if (date_end - date_start).days > 365:
                raise ValidationError(
                    "La plage de dates ne peut pas dépasser 365 jours."
                )

        return cleaned_data


class BranchFilterForm(DateRangeForm):
    """Form with branch filtering capability"""
    
    branche = forms.ModelChoiceField(
        queryset=Branche.objects.filter(is_active=True),
        required=False,
        empty_label="Toutes les branches",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Branche"
    )

    def __init__(self, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # If user is manager or caissier, filter to their branch only
        if user and hasattr(user, 'role') and user.role in ['manager', 'caissier']:
            if user.branche:
                self.fields['branche'].queryset = Branche.objects.filter(id=user.branche.id)
                self.fields['branche'].initial = user.branche
                self.fields['branche'].widget.attrs['disabled'] = True


# REPORTING FORMS
class SalesReportForm(BranchFilterForm):
    """Comprehensive sales report form"""
    
    pompiste = forms.ModelChoiceField(
        queryset=Pompiste.objects.filter(is_active=True),
        required=False,
        empty_label="Tous les pompistes",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Pompiste"
    )
    type_carburant = forms.ModelChoiceField(
        queryset=TypeCarburant.objects.filter(is_active=True),
        required=False,
        empty_label="Tous les carburants",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Type de carburant"
    )
    statut = forms.ChoiceField(
        choices=[('', 'Tous les statuts')] + [
            ('validee', 'Validée'),
            ('en_attente', 'En attente'),
            ('manquant', 'Manquant'),
            ('rejetee', 'Rejetée')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Statut"
    )
    devise = forms.ChoiceField(
        choices=[('', 'Toutes les devises'), ('USD', 'USD'), ('FC', 'FC')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Devise principale"
    )

    def __init__(self, user=None, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        
        # Filter pompistes by user's branch if applicable
        if user and hasattr(user, 'role') and user.role in ['manager', 'caissier']:
            if user.branche:
                self.fields['pompiste'].queryset = Pompiste.objects.filter(
                    branche=user.branche,
                    is_active=True
                )


class ExpenseReportForm(BranchFilterForm):
    """Expense report form"""
    
    categorie = forms.ModelChoiceField(
        queryset=CategorieDepense.objects.filter(is_active=True),
        required=False,
        empty_label="Toutes les catégories",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Catégorie"
    )
    devise = forms.ChoiceField(
        choices=[('', 'Toutes les devises'), ('USD', 'USD'), ('FC', 'FC')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Devise"
    )
    created_by = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        empty_label="Tous les utilisateurs",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Créé par"
    )

    def __init__(self, user=None, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        
        # Filter users by branch if applicable
        if user and hasattr(user, 'role') and user.role in ['manager', 'caissier']:
            if user.branche:
                self.fields['created_by'].queryset = User.objects.filter(
                    branche=user.branche,
                    is_active=True
                )


class StockReportForm(BranchFilterForm):
    """Stock report form"""
    
    type_carburant = forms.ModelChoiceField(
        queryset=TypeCarburant.objects.filter(is_active=True),
        required=False,
        empty_label="Tous les carburants",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Type de carburant"
    )
    alert_level = forms.ChoiceField(
        choices=[
            ('', 'Tous les niveaux'),
            ('critique', 'Critique'),
            ('bas', 'Bas'),
            ('normal', 'Normal')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Niveau d'alerte"
    )


# SEARCH FORMS
class UniversalSearchForm(forms.Form):
    """Universal search form for finding entities"""
    
    query = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rechercher...',
            'autocomplete': 'off'
        }),
        label="Recherche"
    )
    search_type = forms.ChoiceField(
        choices=[
            ('users', 'Utilisateurs'),
            ('pompistes', 'Pompistes'),
            ('abonnes', 'Abonnés'),
            ('ventes', 'Ventes'),
            ('depenses', 'Dépenses'),
            ('documents', 'Documents')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Type de recherche"
    )

    def clean_query(self):
        query = self.cleaned_data['query']
        if len(query.strip()) < 2:
            raise ValidationError("La recherche doit contenir au moins 2 caractères.")
        return query.strip()


# EXPORT FORMS
class ExportForm(BranchFilterForm):
    """Form for data export options"""
    
    export_format = forms.ChoiceField(
        choices=[
            ('csv', 'CSV'),
            ('excel', 'Excel'),
            ('pdf', 'PDF')
        ],
        initial='csv',
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Format d'export"
    )
    include_details = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Inclure les détails"
    )
    include_summary = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Inclure le résumé"
    )


# NOTIFICATION FORMS
class NotificationForm(forms.Form):
    """Form for creating notifications"""
    
    destinataire = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Destinataire"
    )
    titre = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Titre de la notification'
        }),
        label="Titre"
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Message de la notification'
        }),
        label="Message"
    )
    priorite = forms.ChoiceField(
        choices=[
            ('basse', 'Basse'),
            ('normale', 'Normale'),
            ('haute', 'Haute'),
            ('critique', 'Critique')
        ],
        initial='normale',
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Priorité"
    )
    lien_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'http://...'
        }),
        label="Lien (optionnel)"
    )


# BULK OPERATION FORMS
class BulkActionForm(forms.Form):
    """Form for bulk operations"""
    
    action = forms.ChoiceField(
        choices=[
            ('', 'Sélectionner une action'),
            ('activate', 'Activer'),
            ('deactivate', 'Désactiver'),
            ('delete', 'Supprimer'),
            ('export', 'Exporter')
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Action"
    )
    selected_items = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    confirm = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Confirmer l'action"
    )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        confirm = cleaned_data.get('confirm')
        selected_items = cleaned_data.get('selected_items')

        if action and action in ['deactivate', 'delete']:
            if not confirm:
                raise ValidationError("Vous devez confirmer cette action.")

        if action and not selected_items:
            raise ValidationError("Aucun élément sélectionné.")

        return cleaned_data


# QUICK FORMS FOR MODALS
class QuickAbonneForm(forms.Form):
    """Quick form for adding abonne consumption"""
    
    abonne = forms.ModelChoiceField(
        queryset=Abonne.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Abonné"
    )
    type_carburant = forms.ModelChoiceField(
        queryset=TypeCarburant.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Carburant"
    )
    quantite = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Quantité en litres',
            'step': '0.01'
        }),
        label="Quantité (L)"
    )
    montant = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Montant',
            'step': '0.01'
        }),
        label="Montant"
    )
    devise = forms.ChoiceField(
        choices=[('USD', 'USD'), ('FC', 'FC')],
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Devise"
    )

    def clean(self):
        cleaned_data = super().clean()
        quantite = cleaned_data.get('quantite')
        montant = cleaned_data.get('montant')

        if quantite and quantite <= 0:
            raise ValidationError({'quantite': "La quantité doit être supérieure à 0."})

        if montant and montant <= 0:
            raise ValidationError({'montant': "Le montant doit être supérieur à 0."})

        return cleaned_data


class QuickExpenseForm(forms.Form):
    """Quick form for adding expenses"""
    
    categorie = forms.ModelChoiceField(
        queryset=CategorieDepense.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Catégorie"
    )
    description = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Description de la dépense'
        }),
        label="Description"
    )
    montant = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Montant',
            'step': '0.01'
        }),
        label="Montant"
    )
    devise = forms.ChoiceField(
        choices=[('USD', 'USD'), ('FC', 'FC')],
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Devise"
    )
    methode_paiement = forms.ChoiceField(
        choices=[
            ('cash', 'Espèces'),
            ('mobile_money', 'Mobile Money'),
            ('bank', 'Banque'),
            ('check', 'Chèque')
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Méthode de paiement"
    )

    def clean_montant(self):
        montant = self.cleaned_data.get('montant')
        if montant and montant <= 0:
            raise ValidationError("Le montant doit être supérieur à 0.")
        return montant