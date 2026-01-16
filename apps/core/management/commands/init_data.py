from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.core.models import (
    TypeCarburant, MoyenPaiement, CategorieDepense, TauxChange
)
from decimal import Decimal
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = 'Initialize basic data for PETROX system'

    def handle(self, *args, **options):
        self.stdout.write('Initializing PETROX basic data...')
        
        # Create fuel types
        fuel_types = [
            {'nom': 'Essence', 'code': 'ESS', 'couleur_hex': '#FFD700'},
            {'nom': 'Gasoil', 'code': 'GAZ', 'couleur_hex': '#2C3E50'},
            {'nom': 'Jet A1', 'code': 'JET', 'couleur_hex': '#3498DB'},
        ]
        
        for fuel_data in fuel_types:
            fuel, created = TypeCarburant.objects.get_or_create(
                code=fuel_data['code'],
                defaults=fuel_data
            )
            if created:
                self.stdout.write(f'✓ Carburant créé: {fuel.nom}')
        
        # Create payment methods
        payment_methods = [
            {'nom': 'Espèces', 'code': 'CASH'},
            {'nom': 'Orange Money', 'code': 'OM'},
            {'nom': 'Airtel Money', 'code': 'AM'},
            {'nom': 'M-Pesa', 'code': 'MPESA'},
        ]
        
        for payment_data in payment_methods:
            payment, created = MoyenPaiement.objects.get_or_create(
                code=payment_data['code'],
                defaults=payment_data
            )
            if created:
                self.stdout.write(f'✓ Moyen de paiement créé: {payment.nom}')
        
        # Create admin user if not exists
        if not User.objects.filter(is_superuser=True).exists():
            admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@petrox.com',
                password='petrox2024',
                prenom='Admin',
                nom='System',
                role='admin'
            )
            
            # Create expense categories
            categories = [
                {'nom': 'Salaires', 'description': 'Paiement des salaires des employés'},
                {'nom': 'Fournitures', 'description': 'Achat de fournitures et matériel'},
                {'nom': 'Maintenance', 'description': 'Frais de maintenance et réparations'},
                {'nom': 'Utilities', 'description': 'Électricité, eau, internet'},
                {'nom': 'Transport', 'description': 'Frais de transport et carburant'},
                {'nom': 'Divers', 'description': 'Autres dépenses diverses'},
            ]
            
            for cat_data in categories:
                category, created = CategorieDepense.objects.get_or_create(
                    nom=cat_data['nom'],
                    defaults={
                        'description': cat_data['description'],
                        'created_by': admin_user
                    }
                )
                if created:
                    self.stdout.write(f'✓ Catégorie créée: {category.nom}')
            
            # Create default exchange rate
            rate, created = TauxChange.objects.get_or_create(
                is_active=True,
                defaults={
                    'taux_usd_fc': Decimal('2800.00'),
                    'date_effective': timezone.now(),
                    'created_by': admin_user
                }
            )
            if created:
                self.stdout.write(f'✓ Taux de change créé: 1 USD = {rate.taux_usd_fc} FC')
            
            self.stdout.write('\n✅ Données initiales créées avec succès!')
            self.stdout.write('   - Compte admin: admin@petrox.com / petrox2024')
            self.stdout.write('   - Types de carburant: Essence, Gasoil, Jet A1')
            self.stdout.write('   - Moyens de paiement: Cash, Orange Money, Airtel Money, M-Pesa')
            self.stdout.write('   - Catégories de dépenses par défaut')
            self.stdout.write('   - Taux de change: 1 USD = 2800 FC')
        else:
            self.stdout.write('Admin user already exists. Skipping initial data creation.')
        
        self.stdout.write('\n🚀 PETROX system ready!')