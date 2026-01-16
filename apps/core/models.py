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
    
    # Informations personnelles
    prenom = models.CharField(max_length=50, verbose_name="Prénom")
    nom = models.CharField(max_length=50, verbose_name="Nom")
    telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    date_naissance = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    photo = models.ImageField(upload_to='users/photos/', null=True, blank=True, verbose_name="Photo de profil")
    adresse = models.TextField(blank=True, verbose_name="Adresse de résidence")
    
    # Informations professionnelles
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, verbose_name="Rôle")
    salaire = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Salaire")
    devise_salaire = models.CharField(max_length=3, choices=DEVISE_CHOICES, default='USD', verbose_name="Devise du salaire")
    contrat = models.FileField(upload_to='users/contrats/', null=True, blank=True, verbose_name="Contrat de travail")
    
    # Relation avec la branche (sauf pour admin)
    branche = models.ForeignKey('Branche', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Branche assignée")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
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
    
    nom = models.CharField(max_length=100, verbose_name="Nom de la station")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code de la station")
    adresse = models.TextField(verbose_name="Adresse physique")
    ville = models.CharField(max_length=50, verbose_name="Ville")
    province = models.CharField(max_length=50, verbose_name="Province")
    responsable = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                  related_name='branches_gerees', verbose_name="Responsable")
    date_mise_en_service = models.DateField(verbose_name="Date de mise en service")
    is_active = models.BooleanField(default=True, verbose_name="Station active")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créée le")
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
    is_active = models.BooleanField(default=True, verbose_name="Carburant actif")
    
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
                                    verbose_name="Taux USD vers FC")
    date_effective = models.DateTimeField(verbose_name="Date d'entrée en vigueur")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="Créé par")
    is_active = models.BooleanField(default=True, verbose_name="Taux actif")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Taux de change"
        verbose_name_plural = "Taux de change"
        ordering = ['-date_effective']
    
    def __str__(self):
        return f"1 USD = {self.taux_usd_fc} FC (du {self.date_effective.strftime('%d/%m/%Y')})"
    
    @classmethod
    def get_current_rate(cls):
        """Retourne le taux de change actuel"""
        try:
            return cls.objects.filter(is_active=True).first().taux_usd_fc
        except AttributeError:
            return Decimal('2800.00')  # Taux par défaut


class Pompiste(models.Model):
    """Employés pompistes (non-utilisateurs du système)"""
    
    QUART_CHOICES = [
        ('jour', 'Jour'),
        ('nuit', 'Nuit'),
    ]
    
    DEVISE_CHOICES = [
        ('USD', 'Dollar Américain'),
        ('FC', 'Franc Congolais'),
    ]
    
    # Informations personnelles
    prenom = models.CharField(max_length=50, verbose_name="Prénom")
    nom = models.CharField(max_length=50, verbose_name="Nom")
    telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    date_naissance = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    photo = models.ImageField(upload_to='pompistes/photos/', null=True, blank=True, verbose_name="Photo")
    adresse = models.TextField(blank=True, verbose_name="Adresse de résidence")
    
    # Informations professionnelles
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    quart = models.CharField(max_length=10, choices=QUART_CHOICES, default='jour', verbose_name="Quart de travail")
    salaire = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Salaire")
    devise_salaire = models.CharField(max_length=3, choices=DEVISE_CHOICES, default='USD', verbose_name="Devise du salaire")
    contrat = models.FileField(upload_to='pompistes/contrats/', null=True, blank=True, verbose_name="Contrat de travail")
    is_active = models.BooleanField(default=True, verbose_name="Pompiste actif")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Pompiste"
        verbose_name_plural = "Pompistes"
        ordering = ['branche', 'nom', 'prenom']
    
    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.branche.code})"
    
    def get_full_name(self):
        return f"{self.prenom} {self.nom}".strip()


class CategorieDepense(models.Model):
    """Catégories de dépenses"""
    
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom de la catégorie")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Catégorie active")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="Créée par")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créée le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifiée le")
    
    class Meta:
        verbose_name = "Catégorie de dépense"
        verbose_name_plural = "Catégories de dépenses"
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


class Abonne(models.Model):
    """Clients abonnés (entreprises)"""
    
    TYPE_CHOICES = [
        ('prepaye', 'Prépayé'),
        ('postpaye', 'Postpayé'),
        ('credit', 'Crédit'),
    ]
    
    nom_entreprise = models.CharField(max_length=100, verbose_name="Nom de l'entreprise")
    code_client = models.CharField(max_length=20, unique=True, verbose_name="Code client")
    contact_nom = models.CharField(max_length=100, verbose_name="Nom du contact")
    contact_telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    contact_email = models.EmailField(blank=True, verbose_name="Email")
    adresse = models.TextField(verbose_name="Adresse")
    
    type_abonnement = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type d'abonnement")
    solde_usd = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Solde USD")
    solde_fc = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Solde FC")
    limite_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Limite de crédit")
    is_active = models.BooleanField(default=True, verbose_name="Abonné actif")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Abonné"
        verbose_name_plural = "Abonnés"
        ordering = ['nom_entreprise']
    
    def __str__(self):
        return f"{self.nom_entreprise} ({self.code_client})"


class Stock(models.Model):
    """Stock de carburant par branche"""
    
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, verbose_name="Type de carburant")
    quantite_actuelle = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Quantité actuelle (L)")
    capacite_max = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Capacité maximale (L)")
    seuil_alerte = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Seuil d'alerte (L)")
    prix_achat = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Prix d'achat (USD/L)")
    
    # Timestamps
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"
        unique_together = ['branche', 'type_carburant']
        ordering = ['branche', 'type_carburant']
    
    def __str__(self):
        return f"{self.type_carburant.nom} - {self.branche.code} ({self.quantite_actuelle}L)"
    
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
    
    # Informations de base
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    pompiste = models.ForeignKey(Pompiste, on_delete=models.CASCADE, verbose_name="Pompiste")
    manager = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ventes_enregistrees', verbose_name="Manager")
    caissier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ventes_validees', verbose_name="Caissier")
    abonne = models.ForeignKey(Abonne, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Abonné")
    
    # Détails de la vente
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, verbose_name="Type de carburant")
    quantite = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Quantité (L)")
    moyen_paiement = models.ForeignKey(MoyenPaiement, on_delete=models.CASCADE, verbose_name="Moyen de paiement")
    
    # Montants
    montant_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Montant USD")
    montant_fc = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Montant FC")
    
    # Taux de change au moment de la transaction
    taux_change = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Taux de change appliqué")
    
    # Statut et validation
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente', verbose_name="Statut")
    
    # Manquants
    manquant_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Manquant USD")
    manquant_fc = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name="Manquant FC")
    raison_manquant = models.TextField(blank=True, verbose_name="Raison du manquant")
    
    # Observations
    observations = models.TextField(blank=True, verbose_name="Observations")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="Validé le")
    
    class Meta:
        verbose_name = "Vente"
        verbose_name_plural = "Ventes"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Vente #{self.id} - {self.branche.code} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"
    
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
    ]
    
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    categorie = models.ForeignKey(CategorieDepense, on_delete=models.CASCADE, verbose_name="Catégorie")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Créé par")
    
    description = models.CharField(max_length=200, verbose_name="Description")
    montant = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Montant")
    devise = models.CharField(max_length=3, choices=[('USD', 'USD'), ('FC', 'FC')], verbose_name="Devise")
    methode_paiement = models.CharField(max_length=20, choices=METHODE_PAIEMENT_CHOICES, verbose_name="Méthode de paiement")
    beneficiaire = models.CharField(max_length=100, blank=True, verbose_name="Bénéficiaire")
    
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='approuvee', verbose_name="Statut")
    justificatif = models.FileField(upload_to='depenses/justificatifs/', null=True, blank=True, verbose_name="Justificatif")
    notes = models.TextField(blank=True, verbose_name="Notes")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
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
    
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, verbose_name="Type de carburant")
    manager = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Manager")
    
    quantite = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Quantité livrée (L)")
    fournisseur = models.CharField(max_length=100, verbose_name="Fournisseur")
    reference_document = models.CharField(max_length=50, blank=True, verbose_name="Référence document")
    
    date_livraison = models.DateTimeField(verbose_name="Date de livraison")
    date_confirmation = models.DateTimeField(null=True, blank=True, verbose_name="Date de confirmation")
    
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_cours', verbose_name="Statut")
    notes = models.TextField(blank=True, verbose_name="Notes")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Livraison"
        verbose_name_plural = "Livraisons"
        ordering = ['-date_livraison']
    
    def __str__(self):
        return f"Livraison #{self.id} - {self.type_carburant.nom} ({self.quantite}L)"


class ConsommationAbonne(models.Model):
    """Consommations des abonnés"""
    
    abonne = models.ForeignKey(Abonne, on_delete=models.CASCADE, verbose_name="Abonné")
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    vente = models.OneToOneField(Vente, on_delete=models.CASCADE, verbose_name="Vente associée")
    
    # La consommation est liée à une vente, donc les détails sont dans la vente
    
    class Meta:
        verbose_name = "Consommation abonné"
        verbose_name_plural = "Consommations abonnés"
        ordering = ['-vente__created_at']
    
    def __str__(self):
        return f"Consommation {self.abonne.code_client} - {self.branche.code}"


class PaiementSalaire(models.Model):
    """Paiements de salaires"""
    
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    employe_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Employé utilisateur")
    employe_pompiste = models.ForeignKey(Pompiste, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Pompiste")
    caissier = models.ForeignKey(User, on_delete=models.CASCADE, related_name='paiements_effectues', verbose_name="Caissier")
    
    montant = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Montant")
    devise = models.CharField(max_length=3, choices=[('USD', 'USD'), ('FC', 'FC')], verbose_name="Devise")
    periode = models.CharField(max_length=50, verbose_name="Période (ex: Janvier 2024)")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Payé le")
    
    class Meta:
        verbose_name = "Paiement de salaire"
        verbose_name_plural = "Paiements de salaires"
        ordering = ['-created_at']
    
    def __str__(self):
        employe_nom = self.employe_user.get_full_name() if self.employe_user else self.employe_pompiste.get_full_name()
        return f"Salaire {employe_nom} - {self.periode} ({self.montant} {self.devise})"