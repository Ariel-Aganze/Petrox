from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import (
    User, Branche, TypeCarburant, Pompiste, Abonne, 
    Document, DocumentCategory, CategorieDepense,
    Vente, Depense, Stock, TauxChange
)


# USER MANAGEMENT FORMS
class CustomUserCreationForm(UserCreationForm):
    """Form for creating new users with additional fields"""
    
    prenom = forms.CharField(max_length=50, label="Prénom", required=True)
    nom = forms.CharField(max_length=50, label="Nom", required=True)
    email = forms.EmailField(label="Email", required=True)
    telephone = forms.CharField(max_length=20, label="Téléphone", required=False)
    role = forms.ChoiceField(
        choices=User.ROLE_CHOICES,
        label="Rôle",
        required=True
    )
    branche = forms.ModelChoiceField(
        queryset=Branche.objects.filter(is_active=True),
        label="Branche",
        required=False,
        empty_label="Sélectionner une branche"
    )
    salaire = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label="Salaire",
        required=False
    )
    devise_salaire = forms.ChoiceField(
        choices=[('USD', 'USD'), ('FC', 'FC')],
        label="Devise du salaire",
        initial='USD'
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'prenom', 'nom', 'telephone',
            'role', 'branche', 'salaire', 'devise_salaire'
        ]

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise ValidationError("Cette adresse email est déjà utilisée.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        branche = cleaned_data.get('branche')

        # Manager and Caissier must have a branch
        if role in ['manager', 'caissier'] and not branche:
            raise ValidationError("Un manager ou caissier doit être assigné à une branche.")

        # Admin should not have a branch
        if role == 'admin' and branche:
            cleaned_data['branche'] = None

        return cleaned_data


class CustomUserChangeForm(UserChangeForm):
    """Form for editing user information"""
    
    prenom = forms.CharField(max_length=50, label="Prénom", required=True)
    nom = forms.CharField(max_length=50, label="Nom", required=True)
    telephone = forms.CharField(max_length=20, label="Téléphone", required=False)
    branche = forms.ModelChoiceField(
        queryset=Branche.objects.filter(is_active=True),
        label="Branche",
        required=False,
        empty_label="Sélectionner une branche"
    )
    salaire = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label="Salaire",
        required=False
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'prenom', 'nom', 'telephone',
            'role', 'branche', 'salaire', 'devise_salaire', 'is_active'
        ]


# BRANCH MANAGEMENT FORMS
class BrancheForm(forms.ModelForm):
    """Form for creating/editing branches"""
    
    class Meta:
        model = Branche
        fields = [
            'nom', 'code', 'adresse', 'ville', 'province',
            'responsable', 'date_ouverture'
        ]
        widgets = {
            'date_ouverture': forms.DateInput(attrs={'type': 'date'}),
            'adresse': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show managers as potential responsables
        self.fields['responsable'].queryset = User.objects.filter(
            role='manager',
            is_active=True,
            branche__isnull=True  # Only unassigned managers
        )

    def clean_code(self):
        code = self.cleaned_data['code']
        # Check for duplicate code (excluding current instance if editing)
        queryset = Branche.objects.filter(code=code)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise ValidationError("Ce code de branche existe déjà.")
        return code


# FUEL TYPE FORMS
class TypeCarburantForm(forms.ModelForm):
    """Form for fuel type management"""
    
    class Meta:
        model = TypeCarburant
        fields = ['nom', 'couleur_hex']
        widgets = {
            'couleur_hex': forms.TextInput(attrs={'type': 'color'}),
        }

    def clean_nom(self):
        nom = self.cleaned_data['nom']
        queryset = TypeCarburant.objects.filter(nom=nom)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise ValidationError("Ce type de carburant existe déjà.")
        return nom


# POMPISTE FORMS
class PompisteForm(forms.ModelForm):
    """Form for pompiste management"""
    
    date_naissance = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
        label="Date de naissance"
    )
    
    class Meta:
        model = Pompiste
        fields = [
            'prenom', 'nom', 'telephone', 'date_naissance',
            'adresse', 'quart', 'salaire', 'devise_salaire'
        ]
        widgets = {
            'adresse': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_salaire(self):
        salaire = self.cleaned_data.get('salaire')
        if salaire and salaire <= 0:
            raise ValidationError("Le salaire doit être supérieur à 0.")
        return salaire


# SUBSCRIBER FORMS
class AbonneForm(forms.ModelForm):
    """Form for subscriber management"""
    
    class Meta:
        model = Abonne
        fields = [
            'nom_entreprise', 'code_client', 'contact_nom',
            'contact_telephone', 'contact_email', 'adresse',
            'type_abonnement', 'solde_usd', 'solde_fc', 'limite_credit'
        ]
        widgets = {
            'adresse': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_code_client(self):
        code_client = self.cleaned_data['code_client']
        queryset = Abonne.objects.filter(code_client=code_client)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise ValidationError("Ce code client existe déjà.")
        return code_client

    def clean(self):
        cleaned_data = super().clean()
        type_abonnement = cleaned_data.get('type_abonnement')
        limite_credit = cleaned_data.get('limite_credit')

        # Credit type must have a credit limit
        if type_abonnement == 'credit' and (not limite_credit or limite_credit <= 0):
            raise ValidationError({
                'limite_credit': "Un abonné à crédit doit avoir une limite de crédit supérieure à 0."
            })

        return cleaned_data


# DOCUMENT MANAGEMENT FORMS
class DocumentForm(forms.ModelForm):
    """Form for document upload and management"""
    
    class Meta:
        model = Document
        fields = [
            'titre', 'description', 'fichier', 'categorie', 'visibilite'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_fichier(self):
        fichier = self.cleaned_data.get('fichier')
        if fichier:
            # Check file size (10MB limit)
            if fichier.size > 10 * 1024 * 1024:
                raise ValidationError("La taille du fichier ne doit pas dépasser 10 MB.")
            
            # Check file extension
            allowed_extensions = [
                '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                '.jpg', '.jpeg', '.png', '.gif', '.txt'
            ]
            
            file_extension = fichier.name.lower()
            if not any(file_extension.endswith(ext) for ext in allowed_extensions):
                raise ValidationError(
                    f"Type de fichier non autorisé. Extensions autorisées: {', '.join(allowed_extensions)}"
                )
        
        return fichier


class DocumentCategoryForm(forms.ModelForm):
    """Form for document category management"""
    
    class Meta:
        model = DocumentCategory
        fields = ['nom', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }


# EXPENSE FORMS
class DepenseForm(forms.ModelForm):
    """Form for expense registration"""
    
    class Meta:
        model = Depense
        fields = [
            'categorie', 'description', 'montant', 'devise',
            'methode_paiement', 'beneficiaire', 'justificatif', 'notes'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def clean_montant(self):
        montant = self.cleaned_data.get('montant')
        if montant and montant <= 0:
            raise ValidationError("Le montant doit être supérieur à 0.")
        return montant


class CategorieDepenseForm(forms.ModelForm):
    """Form for expense category management"""
    
    class Meta:
        model = CategorieDepense
        fields = ['nom', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }


# SALES FORMS
class VenteForm(forms.ModelForm):
    """Form for sales registration"""
    
    class Meta:
        model = Vente
        fields = [
            'pompiste', 'type_carburant', 'quantite',
            'montant_usd', 'montant_fc', 'moyen_paiement',
            'abonne', 'observations'
        ]
        widgets = {
            'observations': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, branche=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if branche:
            # Filter pompistes by branch
            self.fields['pompiste'].queryset = Pompiste.objects.filter(
                branche=branche,
                is_active=True
            )

    def clean(self):
        cleaned_data = super().clean()
        quantite = cleaned_data.get('quantite')
        montant_usd = cleaned_data.get('montant_usd')
        montant_fc = cleaned_data.get('montant_fc')

        if quantite and quantite <= 0:
            raise ValidationError({'quantite': "La quantité doit être supérieure à 0."})

        if not montant_usd and not montant_fc:
            raise ValidationError("Au moins un montant (USD ou FC) doit être spécifié.")

        if montant_usd and montant_usd < 0:
            raise ValidationError({'montant_usd': "Le montant ne peut pas être négatif."})

        if montant_fc and montant_fc < 0:
            raise ValidationError({'montant_fc': "Le montant ne peut pas être négatif."})

        return cleaned_data


# STOCK FORMS
class StockForm(forms.ModelForm):
    """Form for stock management"""
    
    class Meta:
        model = Stock
        fields = [
            'branche', 'type_carburant', 'quantite_actuelle',
            'capacite_max', 'seuil_alerte', 'prix_achat'
        ]

    def clean(self):
        cleaned_data = super().clean()
        quantite_actuelle = cleaned_data.get('quantite_actuelle')
        capacite_max = cleaned_data.get('capacite_max')
        seuil_alerte = cleaned_data.get('seuil_alerte')

        if quantite_actuelle and quantite_actuelle < 0:
            raise ValidationError({
                'quantite_actuelle': "La quantité ne peut pas être négative."
            })

        if capacite_max and capacite_max <= 0:
            raise ValidationError({
                'capacite_max': "La capacité maximale doit être supérieure à 0."
            })

        if quantite_actuelle and capacite_max and quantite_actuelle > capacite_max:
            raise ValidationError({
                'quantite_actuelle': "La quantité actuelle ne peut pas dépasser la capacité maximale."
            })

        if seuil_alerte and capacite_max and seuil_alerte > capacite_max:
            raise ValidationError({
                'seuil_alerte': "Le seuil d'alerte ne peut pas dépasser la capacité maximale."
            })

        return cleaned_data


# EXCHANGE RATE FORMS
class TauxChangeForm(forms.ModelForm):
    """Form for exchange rate management"""
    
    class Meta:
        model = TauxChange
        fields = ['taux_usd_fc']

    def clean_taux_usd_fc(self):
        taux = self.cleaned_data.get('taux_usd_fc')
        if taux and taux <= 0:
            raise ValidationError("Le taux de change doit être supérieur à 0.")
        
        # Reasonable range check (example: between 1000 and 10000 FC per USD)
        if taux and (taux < 1000 or taux > 10000):
            raise ValidationError(
                "Le taux de change semble incorrect (doit être entre 1000 et 10000 FC par USD)."
            )
        
        return taux


# SEARCH AND FILTER FORMS
class SalesFilterForm(forms.Form):
    """Form for filtering sales reports"""
    
    date_start = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Date de début"
    )
    date_end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Date de fin"
    )
    branche = forms.ModelChoiceField(
        queryset=Branche.objects.filter(is_active=True),
        required=False,
        empty_label="Toutes les branches",
        label="Branche"
    )
    pompiste = forms.ModelChoiceField(
        queryset=Pompiste.objects.filter(is_active=True),
        required=False,
        empty_label="Tous les pompistes",
        label="Pompiste"
    )
    statut = forms.ChoiceField(
        choices=[('', 'Tous les statuts')] + Vente.STATUT_CHOICES,
        required=False,
        label="Statut"
    )
    devise = forms.ChoiceField(
        choices=[('', 'Toutes les devises'), ('USD', 'USD'), ('FC', 'FC')],
        required=False,
        label="Devise"
    )


class ExpenseFilterForm(forms.Form):
    """Form for filtering expense reports"""
    
    date_start = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    date_end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    categorie = forms.ModelChoiceField(
        queryset=CategorieDepense.objects.filter(is_active=True),
        required=False,
        empty_label="Toutes les catégories"
    )
    devise = forms.ChoiceField(
        choices=[('', 'Toutes les devises'), ('USD', 'USD'), ('FC', 'FC')],
        required=False
    )


# USER PROFILE FORMS
class ProfileUpdateForm(forms.ModelForm):
    """Form for users to update their own profile"""
    
    class Meta:
        model = User
        fields = ['prenom', 'nom', 'email', 'telephone', 'adresse']
        widgets = {
            'adresse': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email']
        if self.user:
            if User.objects.filter(email=email).exclude(pk=self.user.pk).exists():
                raise ValidationError("Cette adresse email est déjà utilisée.")
        return email


class PasswordChangeCustomForm(forms.Form):
    """Custom password change form with validation"""
    
    old_password = forms.CharField(
        widget=forms.PasswordInput(),
        label="Ancien mot de passe"
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(),
        label="Nouveau mot de passe",
        min_length=8
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(),
        label="Confirmer le nouveau mot de passe"
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data['old_password']
        if not self.user.check_password(old_password):
            raise ValidationError("L'ancien mot de passe est incorrect.")
        return old_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password and new_password != confirm_password:
            raise ValidationError({
                'confirm_password': "Les mots de passe ne correspondent pas."
            })

        return cleaned_data