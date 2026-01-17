from time import timezone
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
        """Récupère le taux de change actuel"""
        current = cls.objects.filter(is_active=True).first()
        return current.taux_usd_fc if current else Decimal('2800.00')


class CategorieDepense(models.Model):
    """Catégories de dépenses"""
    
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom de la catégorie")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Catégorie active")
    
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
    
    # Informations personnelles
    prenom = models.CharField(max_length=50, verbose_name="Prénom")
    nom = models.CharField(max_length=50, verbose_name="Nom")
    telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    adresse = models.TextField(blank=True, verbose_name="Adresse")
    
    # Informations professionnelles
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    quart = models.CharField(max_length=20, choices=QUART_CHOICES, verbose_name="Quart de travail")
    salaire = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Salaire")
    devise_salaire = models.CharField(max_length=3, choices=DEVISE_CHOICES, default='USD', verbose_name="Devise du salaire")
    is_active = models.BooleanField(default=True, verbose_name="Pompiste actif")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Pompiste"
        verbose_name_plural = "Pompistes"
        ordering = ['prenom', 'nom']
        unique_together = ['branche', 'prenom', 'nom']
    
    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.branche.code})"
    
    def get_full_name(self):
        return f"{self.prenom} {self.nom}".strip()


class Abonne(models.Model):
    """Clients abonnés (entreprises)"""
    
    TYPE_ABONNEMENT_CHOICES = [
        ('prepaye', 'Prépayé'),
        ('postpaye', 'Postpayé'),
        ('credit', 'Crédit'),
    ]
    
    # Informations entreprise
    nom_entreprise = models.CharField(max_length=100, verbose_name="Nom de l'entreprise")
    code_client = models.CharField(max_length=20, unique=True, verbose_name="Code client")
    
    # Contact
    contact_nom = models.CharField(max_length=100, verbose_name="Nom du contact")
    contact_telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    contact_email = models.EmailField(blank=True, verbose_name="Email")
    adresse = models.TextField(verbose_name="Adresse")
    
    # Paramètres abonnement
    type_abonnement = models.CharField(max_length=20, choices=TYPE_ABONNEMENT_CHOICES, verbose_name="Type d'abonnement")
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
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Livraison"
        verbose_name_plural = "Livraisons"
        ordering = ['-date_livraison']
    
    def __str__(self):
        return f"Livraison #{self.id} - {self.type_carburant.nom} ({self.quantite}L)"


class ConsommationAbonne(models.Model):
    """Consommation des abonnés"""
    
    abonne = models.ForeignKey(Abonne, on_delete=models.CASCADE, verbose_name="Abonné")
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    type_carburant = models.ForeignKey(TypeCarburant, on_delete=models.CASCADE, verbose_name="Type de carburant")
    
    quantite = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Quantité (L)")
    montant = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Montant")
    devise = models.CharField(max_length=3, choices=[('USD', 'USD'), ('FC', 'FC')], verbose_name="Devise")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Consommation abonné"
        verbose_name_plural = "Consommations abonnés"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.abonne.nom_entreprise} - {self.quantite}L ({self.created_at.strftime('%d/%m/%Y')})"


class PaiementSalaire(models.Model):
    """Paiements de salaires aux pompistes"""
    
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('paye', 'Payé'),
        ('annule', 'Annulé'),
    ]
    
    METHODE_PAIEMENT_CHOICES = [
        ('cash', 'Espèces'),
        ('mobile_money', 'Mobile Money'),
        ('bank', 'Virement Bancaire'),
    ]
    
    pompiste = models.ForeignKey(Pompiste, on_delete=models.CASCADE, verbose_name="Pompiste")
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    caissier = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Caissier")
    
    mois_paiement = models.DateField(verbose_name="Mois de paiement")
    montant_paye = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Montant payé")
    devise_paiement = models.CharField(max_length=3, choices=[('USD', 'USD'), ('FC', 'FC')], verbose_name="Devise")
    taux_change = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Taux de change")
    
    methode_paiement = models.CharField(max_length=20, choices=METHODE_PAIEMENT_CHOICES, verbose_name="Méthode de paiement")
    notes = models.TextField(blank=True, verbose_name="Notes")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='paye', verbose_name="Statut")
    
    date_paiement = models.DateTimeField(verbose_name="Date de paiement")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Paiement salaire"
        verbose_name_plural = "Paiements salaires"
        ordering = ['-date_paiement']
        unique_together = ['pompiste', 'mois_paiement']
    
    def __str__(self):
        return f"Paiement {self.pompiste.get_full_name()} - {self.mois_paiement.strftime('%m/%Y')}"


class DocumentCategory(models.Model):
    """Catégories de documents"""
    
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom de la catégorie")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Catégorie active")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Créé par")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
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
    
    titre = models.CharField(max_length=200, verbose_name="Titre du document")
    description = models.TextField(blank=True, verbose_name="Description")
    fichier = models.FileField(upload_to='documents/', verbose_name="Fichier")
    categorie = models.ForeignKey(DocumentCategory, on_delete=models.CASCADE, verbose_name="Catégorie")
    
    # Visibilité et accès
    visibilite = models.CharField(max_length=20, choices=VISIBILITE_CHOICES, default='public', verbose_name="Visibilité")
    branches_autorisees = models.ManyToManyField(Branche, blank=True, verbose_name="Branches autorisées")
    
    # Métadonnées
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Uploadé par")
    taille_fichier = models.BigIntegerField(default=0, verbose_name="Taille du fichier (bytes)")
    type_fichier = models.CharField(max_length=50, verbose_name="Type de fichier")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
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
    
    pompiste = models.ForeignKey(Pompiste, on_delete=models.CASCADE, verbose_name="Pompiste")
    branche = models.ForeignKey(Branche, on_delete=models.CASCADE, verbose_name="Branche")
    manager = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Manager")
    
    date_shift = models.DateField(verbose_name="Date du shift")
    type_shift = models.CharField(max_length=10, choices=SHIFT_CHOICES, verbose_name="Type de shift")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='planifie', verbose_name="Statut")
    
    heure_debut = models.TimeField(verbose_name="Heure de début")
    heure_fin = models.TimeField(verbose_name="Heure de fin")
    
    notes = models.TextField(blank=True, verbose_name="Notes")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")
    
    class Meta:
        verbose_name = "Planning Shift"
        verbose_name_plural = "Planning Shifts"
        unique_together = ['pompiste', 'date_shift', 'type_shift']
        ordering = ['-date_shift', 'type_shift']
    
    def __str__(self):
        return f"{self.pompiste.get_full_name()} - {self.date_shift} ({self.get_type_shift_display()})"


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
    
    destinataire = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Destinataire")
    expediteur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications_envoyees', verbose_name="Expéditeur")
    
    type_notification = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    priorite = models.CharField(max_length=10, choices=PRIORITE_CHOICES, default='normale', verbose_name="Priorité")
    
    titre = models.CharField(max_length=200, verbose_name="Titre")
    message = models.TextField(verbose_name="Message")
    
    # Liens
    lien_url = models.URLField(blank=True, verbose_name="Lien URL")
    objet_id = models.IntegerField(null=True, blank=True, verbose_name="ID de l'objet lié")
    
    # Statut
    lu = models.BooleanField(default=False, verbose_name="Lu")
    date_lecture = models.DateTimeField(null=True, blank=True, verbose_name="Date de lecture")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    
    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.titre} -> {self.destinataire.get_full_name()}"
    
    def marquer_comme_lu(self):
        """Marque la notification comme lue"""
        if not self.lu:
            self.lu = True
            self.date_lecture = timezone.now()
            self.save()


# Add these methods to existing Abonne model
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

# Add to Abonne model
Abonne.add_to_class('update_solde_with_consumption', update_solde_with_consumption)
Abonne.add_to_class('get_solde_total_usd', get_solde_total_usd)
Abonne.add_to_class('peut_consommer', peut_consommer)