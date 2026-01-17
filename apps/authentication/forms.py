# apps/authentication/forms.py - Authentication specific forms

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from apps.core.models import User


class CustomAuthenticationForm(AuthenticationForm):
    """Custom login form with additional validation"""
    
    username = forms.CharField(
        max_length=254,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nom d\'utilisateur ou email',
            'autofocus': True
        }),
        label="Nom d'utilisateur"
    )
    
    password = forms.CharField(
        label="Mot de passe",
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mot de passe',
            'autocomplete': 'current-password'
        })
    )
    
    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label="Se souvenir de moi"
    )

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        # Remove the default help text
        if 'username' in self.fields:
            self.fields['username'].help_text = ''

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username is not None and password:
            # Try to authenticate with username first
            self.user_cache = authenticate(
                self.request, 
                username=username, 
                password=password
            )
            
            # If username authentication fails, try with email
            if self.user_cache is None:
                try:
                    user = User.objects.get(email=username)
                    self.user_cache = authenticate(
                        self.request,
                        username=user.username,
                        password=password
                    )
                except User.DoesNotExist:
                    pass

            if self.user_cache is None:
                raise ValidationError(
                    "Nom d'utilisateur/email ou mot de passe incorrect.",
                    code='invalid_login'
                )
            else:
                # Additional validation
                if not self.user_cache.is_active:
                    raise ValidationError(
                        "Ce compte a été désactivé.",
                        code='inactive'
                    )
                
                # Check if user has a valid role
                if not hasattr(self.user_cache, 'role') or not self.user_cache.role:
                    raise ValidationError(
                        "Votre compte n'a pas de rôle assigné. Contactez l'administrateur.",
                        code='no_role'
                    )
                
                # Check if manager/caissier has a branch assigned
                if (self.user_cache.role in ['manager', 'caissier'] and 
                    not self.user_cache.branche):
                    raise ValidationError(
                        "Votre compte n'a pas de branche assignée. Contactez l'administrateur.",
                        code='no_branch'
                    )

        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class LoginForm(forms.Form):
    """Simple login form for API endpoints"""
    
    username = forms.CharField(
        max_length=254,
        label="Nom d'utilisateur ou email"
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput()
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            # Try authentication with username
            self.user_cache = authenticate(
                self.request,
                username=username,
                password=password
            )
            
            # If failed, try with email
            if self.user_cache is None:
                try:
                    user = User.objects.get(email=username)
                    self.user_cache = authenticate(
                        self.request,
                        username=user.username,
                        password=password
                    )
                except User.DoesNotExist:
                    pass

            if self.user_cache is None:
                raise ValidationError("Identifiants incorrects.")
            
            if not self.user_cache.is_active:
                raise ValidationError("Ce compte est désactivé.")

        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class PasswordResetForm(forms.Form):
    """Password reset form"""
    
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Votre adresse email'
        }),
        label="Adresse email"
    )

    def clean_email(self):
        email = self.cleaned_data['email']
        if not User.objects.filter(email=email, is_active=True).exists():
            raise ValidationError(
                "Aucun compte actif n'est associé à cette adresse email."
            )
        return email


class SetPasswordForm(forms.Form):
    """Form for setting a new password"""
    
    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nouveau mot de passe'
        }),
        min_length=8,
        help_text="Votre mot de passe doit contenir au moins 8 caractères."
    )
    
    new_password2 = forms.CharField(
        label="Confirmation du mot de passe",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirmez le mot de passe'
        })
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        if password1 and password2:
            if password1 != password2:
                raise ValidationError("Les mots de passe ne correspondent pas.")
        return password2

    def save(self, commit=True):
        password = self.cleaned_data["new_password1"]
        self.user.set_password(password)
        if commit:
            self.user.save()
        return self.user


class AdminUserCreationForm(forms.Form):
    """Form for admin to create users quickly"""
    
    username = forms.CharField(
        max_length=150,
        label="Nom d'utilisateur"
    )
    email = forms.EmailField(label="Email")
    prenom = forms.CharField(max_length=50, label="Prénom")
    nom = forms.CharField(max_length=50, label="Nom")
    role = forms.ChoiceField(
        choices=User.ROLE_CHOICES,
        label="Rôle"
    )
    password1 = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(),
        min_length=8
    )
    password2 = forms.CharField(
        label="Confirmation du mot de passe",
        widget=forms.PasswordInput()
    )

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise ValidationError("Ce nom d'utilisateur existe déjà.")
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise ValidationError("Cette adresse email est déjà utilisée.")
        return email

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise ValidationError("Les mots de passe ne correspondent pas.")
        return password2

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password1'],
            prenom=self.cleaned_data['prenom'],
            nom=self.cleaned_data['nom'],
            role=self.cleaned_data['role']
        )
        if commit:
            user.save()
        return user