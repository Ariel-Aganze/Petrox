from django.utils import timezone  # FIXED: Correct import
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal


class User(AbstractUser):
    """Modèle utilisateur personnalisé pour le système PETROX"""
    
    ROLE_CHOICES = [
        ('admin', 'Administrateur'),
        ('manager', 'Gestionnaire'),
        ('caissier', 'Caissier'),
    ]
    
    DEVISE_CHOICES = [
        ('USD', 'Dollar Américain'),
        ('FC', 'Franc Congolais'),
    ]
    
    # Informations personnelles - FIXED: Added defaults
    prenom = models.CharField(max_length=50, default='', verbose_name="Prénom")
    nom = models.CharField(max_length=50, default='', verbose_name="Nom")
    telephone = models.CharField(max_length=20, default='', blank=True, verbose_name="Téléphone")
    date_naissance = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    photo = models.ImageField(upload_to='users/photos/', null=True, blank=True, verbose_name="Photo de profil")
    adresse = models.TextField(blank=True, default='', verbose_name="Adresse de résidence")
    
    # Informations professionnelles - FIXED: Added defaults
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='caissier', verbose_name="Rôle")
    salaire = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Salaire")
    devise_salaire = models.CharField(max_length=3, choices=DEVISE_CHOICES, default='USD', verbose_name="Devise du salaire")
    contrat = models.FileField(upload_to='users/contrats/', null=True, blank=True, verbose_name="Contrat de travail")
    
    # Relation avec la branche (sauf pour admin)
    branche = models.ForeignKey('Branche', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Branche assignée")
    
    # Timestamps - FIXED: Use default instead of auto_now_add for existing fields
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ['prenom', 'nom']
    
    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.get_role_display()})"
    
    def get_full_name(self):
        return f"{self.prenom} {self.nom}".strip()
    
    @property
    def can_access_multiple_branches(self):
        return self.role == 'admin'


class Branche(models.Model):
    """Modèle représentant une station-service (branche)"""
    
    # FIXED: Added defaults
    nom = models.CharField(max_length=100, default='Station', verbose_name="Nom de la station")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code de la station")
    adresse = models.TextField(default='', blank=True, verbose_name="Adresse physique")
    ville = models.CharField(max_length=50, default='', blank=True, verbose_name="Ville")
    province = models.CharField(max_length=50, default='', blank=True, verbose_name="Province")
    responsable = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                  related_name='branches_gerees', verbose_name="Responsable")
    date_mise_en_service = models.DateField(null=True, blank=True, verbose_name="Date de mise en service")
    is_active = models.BooleanField(default=True, verbose_name="Station active")
    
    # Timestamps - FIXED: Use default instead of auto_now_add for existing fields
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créée le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifiée le")
    
    class Meta:
        verbose_name = "Branche"
        verbose_name_plural = "Branches"
        ordering = ['nom']
    
    def __str__(self):
        return f"{self.nom} ({self.code})"


class TypeCarburant(models.Model):
    """Types de carburant disponibles"""
    
    nom = models.CharField(max_length=50, unique=True, verbose_name="Nom du carburant")
    code = models.CharField(max_length=10, unique=True, verbose_name="Code")
    couleur_hex = models.CharField(max_length=7, default='#000000', verbose_name="Couleur d'affichage")
    prix_vente_usd = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name="Prix de vente USD/L")
    prix_vente_fc = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Prix de vente FC/L")
    is_active = models.BooleanField(default=True, verbose_name="Carburant actif")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Type de carburant"
        verbose_name_plural = "Types de carburant"
        ordering = ['nom']
    
    def __str__(self):
        return self.nom


class TauxChange(models.Model):
    """Historique des taux de change USD/FC"""
    
    taux_usd_fc = models.DecimalField(max_digits=10, decimal_places=2, 
                                    validators=[MinValueValidator(Decimal('0.01'))],
                                    default=Decimal('2800.00'),  # FIXED: Added default
                                    verbose_name="Taux USD vers FC")
    date_effective = models.DateTimeField(default=timezone.now, verbose_name="Date d'entrée en vigueur")  # FIXED: Added default
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Créé par")  # FIXED: Made nullable
    is_active = models.BooleanField(default=True, verbose_name="Taux actif")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Taux de change"
        verbose_name_plural = "Taux de change"
        ordering = ['-date_effective']
    
    def __str__(self):
        return f"1 USD = {self.taux_usd_fc} FC (du {self.date_effective.strftime('%d/%m/%Y')})"
    
    @classmethod
    def get_current_rate(cls):
        """Récupère le taux de change actuel"""
        current = cls.objects.filter(is_active=True).first()
        return current.taux_usd_fc if current else Decimal('2800.00')


class CategorieDepense(models.Model):
    """Catégories de dépenses"""
    
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom de la catégorie")
    description = models.TextField(blank=True, default='', verbose_name="Description")  # FIXED: Added default
    is_active = models.BooleanField(default=True, verbose_name="Catégorie active")
    # ADDED: Missing fields with safe defaults
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Créé par")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Catégorie de dépense"
        verbose_name_plural = "Catégories de dépense"
        ordering = ['nom']
    
    def __str__(self):
        return self.nom


class MoyenPaiement(models.Model):
    """Moyens de paiement disponibles"""
    
    nom = models.CharField(max_length=50, unique=True, verbose_name="Nom du moyen de paiement")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code")
    is_active = models.BooleanField(default=True, verbose_name="Moyen actif")
    
    class Meta:
        verbose_name = "Moyen de paiement"
        verbose_name_plural = "Moyens de paiement"
        ordering = ['nom']
    
    def __str__(self):
        return self.nom


class Pompiste(models.Model):
    """Pompistes travaillant dans les branches"""
    
    QUART_CHOICES = [
        ('jour', 'Service de jour'),
        ('nuit', 'Service de nuit'),
        ('mixte', 'Service mixte'),
    ]
    
    DEVISE_CHOICES = [
        ('USD', 'Dollar Américain'),
        ('FC', 'Franc Congolais'),
    ]
    
    # Informations personnelles - FIXED: Added defaults
    prenom = models.CharField(max_length=50, default='', verbose_name="Prénom")
    nom = models.CharField(max_length=50, default='', verbose_name="Nom")
    telephone = models.CharField(max_length=20, default='', blank=True, verbose_name="Téléphone")
    adresse = models.TextField(blank=True, default='', verbose_name="Adresse")
    date_naissance = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    
    # Informations professionnelles - FIXED: Made nullable and added defaults
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Branche")
    quart = models.CharField(max_length=20, choices=QUART_CHOICES, default='jour', verbose_name="Quart de travail")
    salaire = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Salaire")
    devise_salaire = models.CharField(max_length=3, choices=DEVISE_CHOICES, default='USD', verbose_name="Devise du salaire")
    is_active = models.BooleanField(default=True, verbose_name="Pompiste actif")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Pompiste"
        verbose_name_plural = "Pompistes"
        ordering = ['prenom', 'nom']
        # REMOVED unique_together to avoid constraint issues during migration
    
    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.branche.code if self.branche else 'N/A'})"
    
    def get_full_name(self):
        return f"{self.prenom} {self.nom}".strip()


class Abonne(models.Model):
    """Clients abonnés (entreprises)"""
    
    TYPE_ABONNEMENT_CHOICES = [
        ('prepaye', 'Prépayé'),
        ('postpaye', 'Postpayé'),
        ('credit', 'Crédit'),
    ]
    
    # Informations entreprise - FIXED: Added defaults
    nom_entreprise = models.CharField(max_length=100, default='Entreprise', verbose_name="Nom de l'entreprise")
    code_client = models.CharField(max_length=20, unique=True, verbose_name="Code client")
    
    # Contact - FIXED: Added defaults
    contact_nom = models.CharField(max_length=100, default='Contact', verbose_name="Nom du contact")
    contact_telephone = models.CharField(max_length=20, default='', blank=True, verbose_name="Téléphone")
    contact_email = models.EmailField(blank=True, default='', verbose_name="Email")
    adresse = models.TextField(default='', blank=True, verbose_name="Adresse")
    
    # Paramètres abonnement - FIXED: Added defaults
    type_abonnement = models.CharField(max_length=20, choices=TYPE_ABONNEMENT_CHOICES, default='prepaye', verbose_name="Type d'abonnement")
    solde_usd = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), verbose_name="Solde USD")
    solde_fc = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), verbose_name="Solde FC")
    limite_credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), verbose_name="Limite de crédit")
    is_active = models.BooleanField(default=True, verbose_name="Abonné actif")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Abonné"
        verbose_name_plural = "Abonnés"
        ordering = ['nom_entreprise']
    
    def __str__(self):
        return f"{self.nom_entreprise} ({self.code_client})"
    
    def update_solde_with_consumption(self, montant, devise, type_operation='consommation'):
        """Met à jour le solde de l'abonné après une consommation ou un paiement"""
        if devise == 'USD':
            if type_operation == 'consommation':
                if self.type_abonnement == 'prepaye':
                    self.solde_usd -= montant
                else:  # postpaye ou credit
                    self.solde_usd -= montant  # Dette négative
            elif type_operation == 'paiement':
                self.solde_usd += montant
        else:  # FC
            if type_operation == 'consommation':
                if self.type_abonnement == 'prepaye':
                    self.solde_fc -= montant
                else:
                    self.solde_fc -= montant
            elif type_operation == 'paiement':
                self.solde_fc += montant
        
        self.save()

    def get_solde_total_usd(self, taux_change=None):
        """Calcule le solde total en USD"""
        if not taux_change:
            current_rate = TauxChange.objects.filter(is_active=True).first()
            taux_change = current_rate.taux_usd_fc if current_rate else Decimal('2800.00')
        
        return self.solde_usd + (self.solde_fc / taux_change)

    def peut_consommer(self, montant, devise):
        """Vérifie si l'abonné peut consommer le montant demandé"""
        if self.type_abonnement == 'prepaye':
            if devise == 'USD':
                return self.solde_usd >= montant
            else:
                return self.solde_fc >= montant
        elif self.type_abonnement == 'postpaye':
            return True  # Pas de limite pour postpayé
        elif self.type_abonnement == 'credit':
            solde_total = self.get_solde_total_usd()
            limite_usd = self.limite_credit
            if devise == 'FC':
                current_rate = TauxChange.get_current_rate()
                montant_usd = montant / current_rate
            else:
                montant_usd = montant
            
            return (solde_total - montant_usd) >= -limite_usd
        
        return False


class Stock(models.Model):
    """Stock de carburant par branche"""
    
    # FIXED: Made nullable and added defaults
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Branche")
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Type de carburant")
    quantite_actuelle = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Quantité actuelle (L)")
    capacite_max = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1000.00'), verbose_name="Capacité maximale (L)")
    seuil_alerte = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('100.00'), verbose_name="Seuil d'alerte (L)")
    prix_achat = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Prix d'achat (USD/L)")
    
    # Timestamps
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"
        # REMOVED unique_together to avoid constraint issues during migration
        ordering = ['branche', 'type_carburant']
    
    def __str__(self):
        return f"{self.type_carburant.nom if self.type_carburant else 'N/A'} - {self.branche.code if self.branche else 'N/A'} ({self.quantite_actuelle}L)"
    
    @property
    def pourcentage_rempli(self):
        if self.capacite_max > 0:
            return (self.quantite_actuelle / self.capacite_max) * 100
        return 0
    
    @property
    def niveau_alerte(self):
        if self.quantite_actuelle <= self.seuil_alerte:
            return 'critique'
        elif self.quantite_actuelle <= (self.seuil_alerte * 2):
            return 'bas'
        return 'normal'


class Vente(models.Model):
    """Transactions de vente de carburant"""
    
    STATUT_CHOICES = [
        ('en_attente', 'En attente de validation'),
        ('validee', 'Validée'),
        ('manquant', 'Manquant signalé'),
        ('rejetee', 'Rejetée'),
    ]
    
    # Informations de base - FIXED: Made nullable and added defaults
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Branche")
    pompiste = models.ForeignKey(Pompiste, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Pompiste")
    manager = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='ventes_enregistrees', verbose_name="Manager")
    caissier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ventes_validees', verbose_name="Caissier")
    abonne = models.ForeignKey(Abonne, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Abonné")
    
    # Détails de la vente - FIXED: Made nullable and added defaults
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Type de carburant")
    quantite = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'), verbose_name="Quantité (L)")
    moyen_paiement = models.ForeignKey(MoyenPaiement, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Moyen de paiement")
    
    # Montants - FIXED: Already have defaults
    montant_usd = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Montant USD")
    montant_fc = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), verbose_name="Montant FC")
    
    # Taux de change au moment de la transaction - FIXED: Added default
    taux_change = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('2800.00'), verbose_name="Taux de change appliqué")
    
    # Statut et validation
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente', verbose_name="Statut")
    
    # Manquants - FIXED: Already have defaults
    manquant_usd = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Manquant USD")
    manquant_fc = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'), verbose_name="Manquant FC")
    raison_manquant = models.TextField(blank=True, default='', verbose_name="Raison du manquant")
    
    # Observations - FIXED: Added default
    observations = models.TextField(blank=True, default='', verbose_name="Observations")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="Validé le")
    
    class Meta:
        verbose_name = "Vente"
        verbose_name_plural = "Ventes"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Vente #{self.id} - {self.branche.code if self.branche else 'N/A'} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"
    
    @property
    def montant_total_usd(self):
        return self.montant_usd - self.manquant_usd
    
    @property
    def montant_total_fc(self):
        return self.montant_fc - self.manquant_fc


class Depense(models.Model):
    """Dépenses par branche"""
    
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('approuvee', 'Approuvée'),
        ('rejetee', 'Rejetée'),
    ]
    
    METHODE_PAIEMENT_CHOICES = [
        ('cash', 'Espèces'),
        ('mobile_money', 'Mobile Money'),
        ('bank', 'Virement Bancaire'),
        ('check', 'Chèque'),
    ]
    
    # FIXED: Made nullable and added defaults
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Branche")
    categorie = models.ForeignKey(CategorieDepense, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Catégorie")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Créé par")
    
    description = models.CharField(max_length=200, default='Dépense', verbose_name="Description")
    montant = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Montant")
    devise = models.CharField(max_length=3, choices=[('USD', 'USD'), ('FC', 'FC')], default='USD', verbose_name="Devise")
    methode_paiement = models.CharField(max_length=20, choices=METHODE_PAIEMENT_CHOICES, default='cash', verbose_name="Méthode de paiement")
    beneficiaire = models.CharField(max_length=100, blank=True, default='', verbose_name="Bénéficiaire")
    
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='approuvee', verbose_name="Statut")
    justificatif = models.FileField(upload_to='depenses/justificatifs/', null=True, blank=True, verbose_name="Justificatif")
    notes = models.TextField(blank=True, default='', verbose_name="Notes")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="Approuvé le")
    
    class Meta:
        verbose_name = "Dépense"
        verbose_name_plural = "Dépenses"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Dépense #{self.id} - {self.description} ({self.montant} {self.devise})"


class Livraison(models.Model):
    """Livraisons de carburant"""
    
    STATUT_CHOICES = [
        ('en_cours', 'En cours'),
        ('livree', 'Livrée'),
        ('confirmee', 'Confirmée'),
    ]
    
    # FIXED: Made nullable and added defaults
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Branche")
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Type de carburant")
    manager = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Manager")
    
    quantite = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Quantité livrée (L)")
    fournisseur = models.CharField(max_length=100, default='Fournisseur', verbose_name="Fournisseur")
    reference_document = models.CharField(max_length=50, blank=True, default='', verbose_name="Référence document")
    
    date_livraison = models.DateTimeField(default=timezone.now, verbose_name="Date de livraison")
    date_confirmation = models.DateTimeField(null=True, blank=True, verbose_name="Date de confirmation")
    
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_cours', verbose_name="Statut")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Livraison"
        verbose_name_plural = "Livraisons"
        ordering = ['-date_livraison']
    
    def __str__(self):
        return f"Livraison #{self.id} - {self.type_carburant.nom if self.type_carburant else 'N/A'} ({self.quantite}L)"


class ConsommationAbonne(models.Model):
    """Consommation des abonnés"""
    
    # FIXED: Made nullable and added defaults
    abonne = models.ForeignKey(Abonne, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Abonné")
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Branche")
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Type de carburant")
    
    quantite = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'), verbose_name="Quantité (L)")
    # FIXED: Added defaults to avoid migration prompts
    montant = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name="Montant")
    devise = models.CharField(max_length=3, choices=[('USD', 'USD'), ('FC', 'FC')], default='USD', verbose_name="Devise")
    
    # FIXED: Use default instead of auto_now_add for existing table
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Consommation abonné"
        verbose_name_plural = "Consommations abonnés"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.abonne.nom_entreprise if self.abonne else 'N/A'} - {self.quantite}L ({self.created_at.strftime('%d/%m/%Y')})"


class PaiementSalaire(models.Model):
    """
    Payment of salaries to employees (pompistes and system users)
    Supports full salary payments and advances
    """
    TYPE_PAIEMENT_CHOICES = [
        ('salaire_complet', 'Salaire Complet'),
        ('avance', 'Avance sur Salaire'),
    ]
    
    METHODE_PAIEMENT_CHOICES = [
        ('cash', 'Cash'),
        ('mobile_money', 'Mobile Money'),
        ('bank_transfer', 'Virement Bancaire'),
    ]
    
    STATUT_CHOICES = [
        ('paye', 'Payé'),
        ('annule', 'Annulé'),
    ]
    
    # Employee (either pompiste or system user)
    pompiste = models.ForeignKey(
        'Pompiste',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='paiements_salaire',
        help_text='Pompiste (employé de station)'
    )
    employe_user = models.ForeignKey(
        'User',  # or settings.AUTH_USER_MODEL
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='paiements_recus',
        help_text='Utilisateur système (Admin, Manager, Caissier)'
    )
    
    # Payment details
    branche = models.ForeignKey(
        'Branche',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    caissier = models.ForeignKey(
        'User',  # or settings.AUTH_USER_MODEL
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paiements_effectues',
        help_text='Caissier qui a effectué le paiement'
    )
    
    # Period and amounts
    mois_paiement = models.DateField(
        null=True,
        blank=True,
        help_text='Premier jour du mois de paiement'
    )
    type_paiement = models.CharField(
        max_length=20,
        choices=TYPE_PAIEMENT_CHOICES,
        default='salaire_complet',
        help_text='Type de paiement effectué'
    )
    
    # Salary breakdown
    montant_total_salaire = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Montant total du salaire mensuel'
    )
    montant_avances_precedentes = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Total des avances déjà versées ce mois'
    )
    montant_paye = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Montant payé lors de cette transaction'
    )
    montant_restant = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Montant restant à payer après ce paiement'
    )
    
    # Payment method and currency
    devise_paiement = models.CharField(
        max_length=3,
        choices=[('USD', 'USD'), ('FC', 'FC')]
    )
    taux_change = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    methode_paiement = models.CharField(
        max_length=20,
        choices=METHODE_PAIEMENT_CHOICES
    )
    
    # Status and notes
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='paye'
    )
    notes = models.TextField(
        blank=True
    )
    
    # Timestamps
    date_paiement = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Paiement de Salaire'
        verbose_name_plural = 'Paiements de Salaires'
        ordering = ['-date_paiement']
        indexes = [
            models.Index(fields=['mois_paiement', 'statut']),
            models.Index(fields=['branche', 'date_paiement']),
        ]
    
    def __str__(self):
        employee = self.pompiste if self.pompiste else self.employe_user
        employee_name = employee.get_full_name() if employee else 'N/A'
        return f"{employee_name} - {self.mois_paiement.strftime('%m/%Y')} - {self.montant_paye} {self.devise_paiement}"
    
    def get_employee_name(self):
        """Get the name of the employee being paid"""
        if self.pompiste:
            return self.pompiste.get_full_name()
        elif self.employe_user:
            return self.employe_user.get_full_name()
        return 'N/A'
    
    def get_employee_type(self):
        """Get the type of employee"""
        if self.pompiste:
            return 'pompiste'
        elif self.employe_user:
            return 'user'
        return 'unknown'
    
    def clean(self):
        """Validate that only one employee type is set"""
        from django.core.exceptions import ValidationError
        if self.pompiste and self.employe_user:
            raise ValidationError(
                "Un paiement ne peut être lié qu'à un pompiste OU un utilisateur, pas les deux"
            )
        if not self.pompiste and not self.employe_user:
            raise ValidationError(
                "Un paiement doit être lié à un pompiste ou un utilisateur"
            )
    
    def save(self, *args, **kwargs):
        # Run clean validation
        self.clean()
        super().save(*args, **kwargs)


class DocumentCategory(models.Model):
    """Catégories de documents"""
    
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom de la catégorie")
    description = models.TextField(blank=True, default='', verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Catégorie active")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Créé par")
    
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Catégorie de document"
        verbose_name_plural = "Catégories de documents"
        ordering = ['nom']
    
    def __str__(self):
        return self.nom


class Document(models.Model):
    """Documents du système"""
    
    VISIBILITE_CHOICES = [
        ('public', 'Public'),
        ('prive', 'Privé'),
        ('confidentiel', 'Confidentiel'),
    ]
    
    # FIXED: Added defaults
    titre = models.CharField(max_length=200, default='Document', verbose_name="Titre du document")
    description = models.TextField(blank=True, default='', verbose_name="Description")
    fichier = models.FileField(upload_to='documents/', null=True, blank=True, verbose_name="Fichier")
    categorie = models.ForeignKey(DocumentCategory, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Catégorie")
    
    # Visibilité et accès
    visibilite = models.CharField(max_length=20, choices=VISIBILITE_CHOICES, default='public', verbose_name="Visibilité")
    branches_autorisees = models.ManyToManyField(Branche, blank=True, verbose_name="Branches autorisées")
    
    # Métadonnées - FIXED: Made nullable and added defaults
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Uploadé par")
    taille_fichier = models.BigIntegerField(default=0, verbose_name="Taille du fichier (bytes)")
    type_fichier = models.CharField(max_length=50, default='', blank=True, verbose_name="Type de fichier")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.titre
    
    def get_taille_lisible(self):
        """Retourne la taille du fichier dans un format lisible"""
        if self.taille_fichier < 1024:
            return f"{self.taille_fichier} B"
        elif self.taille_fichier < 1024*1024:
            return f"{self.taille_fichier/1024:.1f} KB"
        else:
            return f"{self.taille_fichier/(1024*1024):.1f} MB"


class PlanningShift(models.Model):
    """Planning des shifts des pompistes"""
    
    SHIFT_CHOICES = [
        ('jour', 'Service de jour (6h-18h)'),
        ('nuit', 'Service de nuit (18h-6h)'),
    ]
    
    STATUT_CHOICES = [
        ('planifie', 'Planifié'),
        ('confirme', 'Confirmé'),
        ('annule', 'Annulé'),
        ('complete', 'Complété'),
    ]
    
    # FIXED: Made nullable and added defaults
    pompiste = models.ForeignKey(Pompiste, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Pompiste")
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Branche")
    manager = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Manager")
    
    date_shift = models.DateField(null=True, blank=True, verbose_name="Date du shift")
    type_shift = models.CharField(max_length=10, choices=SHIFT_CHOICES, default='jour', verbose_name="Type de shift")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='planifie', verbose_name="Statut")
    
    heure_debut = models.TimeField(null=True, blank=True, verbose_name="Heure de début")
    heure_fin = models.TimeField(null=True, blank=True, verbose_name="Heure de fin")
    
    notes = models.TextField(blank=True, default='', verbose_name="Notes")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Planning Shift"
        verbose_name_plural = "Planning Shifts"
        # REMOVED unique_together to avoid constraint issues during migration
        ordering = ['-date_shift', 'type_shift']
    
    def __str__(self):
        return f"{self.pompiste.get_full_name() if self.pompiste else 'N/A'} - {self.date_shift or 'N/A'} ({self.get_type_shift_display()})"
    
class Attendance(models.Model):
    """Attendance tracking for pompiste shifts"""
    
    STATUT_CHOICES = [
        ('present', 'Présent'),
        ('late', 'Retard'),
        ('absent', 'Absent'),
    ]
    
    shift = models.OneToOneField(PlanningShift, on_delete=models.CASCADE, verbose_name="Shift")
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, verbose_name="Statut")
    raison = models.TextField(blank=True, default='', verbose_name="Raison (retard/absence)")
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Marqué par")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Présence"
        verbose_name_plural = "Présences"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.shift} - {self.get_statut_display()}"


class Notification(models.Model):
    """Système de notifications"""
    
    TYPE_CHOICES = [
        ('vente_pending', 'Vente en attente'),
        ('manquant', 'Manquant signalé'),
        ('stock_bas', 'Stock bas'),
        ('livraison', 'Livraison'),
        ('system', 'Notification système'),
        ('user', 'Notification utilisateur'),
    ]
    
    PRIORITE_CHOICES = [
        ('basse', 'Basse'),
        ('normale', 'Normale'),
        ('haute', 'Haute'),
        ('critique', 'Critique'),
    ]
    
    # FIXED: Made nullable and added defaults
    destinataire = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Destinataire")
    expediteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications_envoyees', verbose_name="Expéditeur")
    
    type_notification = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system', verbose_name="Type")
    priorite = models.CharField(max_length=10, choices=PRIORITE_CHOICES, default='normale', verbose_name="Priorité")
    
    titre = models.CharField(max_length=200, default='Notification', verbose_name="Titre")
    message = models.TextField(default='', blank=True, verbose_name="Message")
    
    # Liens - FIXED: Added defaults
    lien_url = models.URLField(blank=True, default='', verbose_name="Lien URL")
    objet_id = models.IntegerField(null=True, blank=True, verbose_name="ID de l'objet lié")
    
    # Statut
    lu = models.BooleanField(default=False, verbose_name="Lu")
    date_lecture = models.DateTimeField(null=True, blank=True, verbose_name="Date de lecture")
    
    # Timestamps - FIXED: Use default instead of auto_now_add
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.titre} -> {self.destinataire.get_full_name() if self.destinataire else 'N/A'}"
    
    def marquer_comme_lu(self):
        """Marque la notification comme lue"""
        if not self.lu:
            self.lu = True
            self.date_lecture = timezone.now()
            self.save()

class Partenaire(models.Model):
    """Fuel partners - companies we trade fuel with"""
    
    nom = models.CharField(max_length=200, verbose_name="Nom du partenaire")
    code = models.CharField(max_length=50, unique=True, verbose_name="Code partenaire")
    contact = models.CharField(max_length=100, blank=True, verbose_name="Personne de contact")
    telephone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    email = models.EmailField(blank=True, verbose_name="Email")
    adresse = models.TextField(blank=True, verbose_name="Adresse")
    
    # Financial tracking
    solde_usd = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        verbose_name="Solde USD",
        help_text="Positif = ils nous doivent, Négatif = nous leur devons"
    )
    solde_fc = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        default=0,
        verbose_name="Solde FC",
        help_text="Positif = ils nous doivent, Négatif = nous leur devons"
    )
    
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    notes = models.TextField(blank=True, verbose_name="Notes")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'User',  # Reference to your User model
        on_delete=models.SET_NULL,
        null=True,
        related_name='partenaires_created'
    )
    
    class Meta:
        verbose_name = "Partenaire"
        verbose_name_plural = "Partenaires"
        ordering = ['nom']
    
    def __str__(self):
        return f"{self.nom} ({self.code})"
    
    @property
    def has_outstanding_debt(self):
        """Check if partner owes us money"""
        return self.solde_usd > 0 or self.solde_fc > 0
    
    @property
    def we_owe_them(self):
        """Check if we owe partner money"""
        return self.solde_usd < 0 or self.solde_fc < 0


class LivraisonCarburant(models.Model):
    """Fuel delivery records"""
    
    TYPE_CHOICES = [
        ('propre', 'Notre carburant'),
        ('partenaire_donne', 'Donné par partenaire'),
        ('partenaire_prend', 'Pris par partenaire'),
    ]
    
    STATUT_CHOICES = [
        ('planifiee', 'Planifiée'),
        ('en_transit', 'En transit'),
        ('livree', 'Livrée'),
        ('confirmee', 'Confirmée'),
        ('annulee', 'Annulée'),
    ]
    
    DEVISE_CHOICES = [
        ('USD', 'USD'),
        ('FC', 'FC'),
    ]
    
    # Basic info
    numero = models.CharField(max_length=50, unique=True, verbose_name="Numéro de livraison")
    type_livraison = models.CharField(
        max_length=20, 
        choices=TYPE_CHOICES,
        verbose_name="Type de livraison"
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='planifiee',
        verbose_name="Statut"
    )
    
    # Fuel details
    type_carburant = models.ForeignKey(
        'TypeCarburant',  # Reference to your TypeCarburant model
        on_delete=models.PROTECT,
        verbose_name="Type de carburant"
    )
    branche = models.ForeignKey(
        'Branche',  # Reference to your Branche model
        on_delete=models.PROTECT,
        verbose_name="Branche destinataire/source"
    )
    
    # Quantities
    quantite_prevue = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        verbose_name="Quantité prévue (L)"
    )
    quantite_recue = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Quantité réellement reçue (L)"
    )
    ecart_quantite = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Écart (L)"
    )
    
    # Partner info
    partenaire = models.ForeignKey(
        'Partenaire',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Partenaire"
    )
    
    # Financial info
    prix_unitaire = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Prix unitaire"
    )
    devise = models.CharField(
        max_length=3,
        choices=DEVISE_CHOICES,
        default='USD'
    )
    montant_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )
    statut_paiement = models.CharField(
        max_length=20,
        choices=[
            ('non_requis', 'Non requis'),
            ('en_attente', 'En attente'),
            ('paye', 'Payé'),
        ],
        default='non_requis'
    )
    
    # Dates
    date_prevue = models.DateField(verbose_name="Date prévue")
    date_livraison = models.DateTimeField(null=True, blank=True)
    date_confirmation = models.DateTimeField(null=True, blank=True)
    
    # Documents
    bon_livraison = models.CharField(max_length=100, blank=True)
    transporteur = models.CharField(max_length=200, blank=True)
    immatriculation = models.CharField(max_length=50, blank=True)
    observations_admin = models.TextField(blank=True)
    observations_manager = models.TextField(blank=True)
    
    # Users
    planifiee_par = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='livraisons_planifiees'
    )
    confirmee_par = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='livraisons_confirmees'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Livraison de carburant"
        verbose_name_plural = "Livraisons de carburant"
        ordering = ['-date_prevue', '-created_at']
    
    def __str__(self):
        return f"{self.numero} - {self.type_carburant.nom}"
    
    def save(self, *args, **kwargs):
        if not self.numero:
            from django.utils import timezone
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            self.numero = f"LIV-{timestamp}"
        
        if self.quantite_recue is not None:
            self.ecart_quantite = self.quantite_recue - self.quantite_prevue
        
        if self.prix_unitaire:
            qty = self.quantite_recue if self.quantite_recue else self.quantite_prevue
            # self.montant_total = self.prix_unitaire * qty
            if self.prix_unitaire not in (None, ''):
                self.prix_unitaire = Decimal(self.prix_unitaire)
        
        super().save(*args, **kwargs)
    
    @property
    def has_ecart(self):
        return abs(self.ecart_quantite) > 0.01
    
    @property
    def ecart_percentage(self):
        if self.quantite_prevue > 0:
            return (self.ecart_quantite / self.quantite_prevue) * 100
        return 0


class PaiementPartenaire(models.Model):
    """Partner payment records"""
    
    TYPE_CHOICES = [
        ('paiement', 'Paiement (nous payons)'),
        ('reception', 'Réception (nous recevons)'),
    ]
    
    numero = models.CharField(max_length=50, unique=True)
    partenaire = models.ForeignKey('Partenaire', on_delete=models.PROTECT)
    type_transaction = models.CharField(max_length=20, choices=TYPE_CHOICES)
    
    montant = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    devise = models.CharField(max_length=3, choices=[('USD', 'USD'), ('FC', 'FC')])
    
    livraison = models.ForeignKey(
        'LivraisonCarburant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    date_paiement = models.DateField()
    mode_paiement = models.CharField(
        max_length=50,
        choices=[
            ('espece', 'Espèces'),
            ('virement', 'Virement bancaire'),
            ('cheque', 'Chèque'),
            ('mobile_money', 'Mobile Money'),
        ]
    )
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    
    enregistre_par = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Paiement partenaire"
        verbose_name_plural = "Paiements partenaires"
        ordering = ['-date_paiement']
    
    def __str__(self):
        return f"{self.numero} - {self.partenaire.nom}"
    
    def save(self, *args, **kwargs):
        if not self.numero:
            from django.utils import timezone
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            self.numero = f"PAY-{timestamp}"
        
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new:
            self.update_partner_balance()
    
    def update_partner_balance(self):
        """Update partner's balance"""
        if self.type_transaction == 'paiement':
            if self.devise == 'USD':
                self.partenaire.solde_usd -= self.montant
            else:
                self.partenaire.solde_fc -= self.montant
        else:  # reception
            if self.devise == 'USD':
                self.partenaire.solde_usd -= self.montant
            else:
                self.partenaire.solde_fc -= self.montant
        
        self.partenaire.save()