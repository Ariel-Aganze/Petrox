from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import FormView
from django.http import JsonResponse
from django.utils import timezone
from apps.core.models import User


class LoginView(DjangoLoginView):
    template_name = 'auth/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        """Redirect based on user role"""
        user = self.request.user
        
        if user.role == 'admin':
            return reverse_lazy('admin_module:dashboard')
        elif user.role == 'manager':
            return reverse_lazy('manager_module:dashboard')
        elif user.role == 'caissier':
            return reverse_lazy('caissier_module:dashboard')
        else:
            return reverse_lazy('admin_module:dashboard')  # Default fallback
    
    def form_valid(self, form):
        """Handle successful login"""
        user = form.get_user()
        
        # Check if user is active
        if not user.is_active:
            messages.error(self.request, 'Votre compte est désactivé. Contactez l\'administrateur.')
            return self.form_invalid(form)
        
        # Check role-specific requirements
        if user.role in ['manager', 'caissier'] and not user.branche:
            messages.error(self.request, 'Aucune branche assignée. Contactez l\'administrateur.')
            return self.form_invalid(form)
        
        # Log successful login
        login(self.request, user)
        
        # Success message
        messages.success(
            self.request, 
            f'Bienvenue {user.get_full_name()}! Connecté en tant que {user.get_role_display()}'
        )
        
        return super().form_valid(form)
    
    def form_invalid(self, form):
        """Handle failed login"""
        messages.error(self.request, 'Nom d\'utilisateur ou mot de passe incorrect.')
        return super().form_invalid(form)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Connexion - PETROX'
        return context


def logout_view(request):
    """Handle user logout"""
    if request.user.is_authenticated:
        user_name = request.user.get_full_name()
        logout(request)
        messages.success(request, f'Au revoir {user_name}! Vous êtes maintenant déconnecté.')
    
    return redirect('authentication:login')


def check_session(request):
    """API endpoint to check if user session is still valid"""
    if request.user.is_authenticated:
        return JsonResponse({
            'authenticated': True,
            'user': {
                'id': request.user.id,
                'name': request.user.get_full_name(),
                'role': request.user.role,
                'branche': request.user.branche.nom if request.user.branche else None
            }
        })
    else:
        return JsonResponse({'authenticated': False})