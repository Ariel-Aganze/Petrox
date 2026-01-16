from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import get_user_model

User = get_user_model()


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'block w-full pl-10 pr-3 py-2.5 border border-gray-300 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-petrox-red focus:border-petrox-red sm:text-sm transition duration-200',
            'placeholder': 'admin@petrox.com'
        }),
        label="Email ou nom d'utilisateur"
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'block w-full pl-10 pr-10 py-2.5 border border-gray-300 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-petrox-red focus:border-petrox-red sm:text-sm transition duration-200',
            'placeholder': '••••••••'
        }),
        label="Mot de passe"
    )