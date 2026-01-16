from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import LoginView as BaseLoginView
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import HttpResponseRedirect
from .forms import CustomAuthenticationForm


class LoginView(BaseLoginView):
    template_name = 'authentication/login.html'
    form_class = CustomAuthenticationForm
    
    def get_success_url(self):
        user = self.request.user
        if hasattr(user, 'role') and user.role:
            if user.role == 'admin':
                return '/dashboard/'
            elif user.role == 'manager':
                return '/manager/'
            elif user.role == 'caissier':
                return '/caissier/'
        
        # Fallback for users without proper roles
        messages.warning(self.request, 'Votre compte n\'a pas de rôle assigné. Contactez l\'administrateur.')
        logout(self.request)
        return '/auth/login/'
    
    def form_invalid(self, form):
        messages.error(self.request, 'Email ou mot de passe incorrect.')
        return super().form_invalid(form)
    
    def form_valid(self, form):
        user = form.get_user()
        
        # Check if user has a role
        if not hasattr(user, 'role') or not user.role:
            messages.error(self.request, 'Votre compte n\'a pas de rôle assigné. Contactez l\'administrateur.')
            return self.form_invalid(form)
        
        # Check if manager/caissier has a branch assigned
        if user.role in ['manager', 'caissier'] and not user.branche:
            messages.error(self.request, 'Votre compte n\'a pas de branche assignée. Contactez l\'administrateur.')
            return self.form_invalid(form)
        
        return super().form_valid(form)
    
    def dispatch(self, request, *args, **kwargs):
        # If user is already authenticated, redirect them to their dashboard
        if request.user.is_authenticated:
            if hasattr(request.user, 'role') and request.user.role:
                if request.user.role == 'admin':
                    return HttpResponseRedirect('/dashboard/')
                elif request.user.role == 'manager':
                    return HttpResponseRedirect('/manager/')
                elif request.user.role == 'caissier':
                    return HttpResponseRedirect('/caissier/')
            # If no role, log them out and redirect to login
            logout(request)
            messages.warning(request, 'Votre compte n\'a pas de rôle assigné.')
        
        return super().dispatch(request, *args, **kwargs)


def logout_view(request):
    logout(request)
    messages.success(request, 'Vous avez été déconnecté avec succès.')
    return redirect('authentication:login')