"""
Shared sale receipt ("facture") rendering.

Every role (admin, caissier, gestionnaire) prints receipts through this module,
so a single receipt and a multi-receipt print always have the same layout, and
reported shortfalls (manquants) always appear on the printed document.
"""
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape

from apps.core.models import Vente


RECEIPT_CSS = """
    * { box-sizing: border-box; }
    body { font-family: Arial, sans-serif; margin: 0; padding: 10px; color: #111; background: #fff; }
    .receipt { max-width: 80mm; margin: 0 auto 20px auto; padding: 10px; }
    .receipt + .receipt { page-break-before: always; break-before: page; }
    .header { text-align: center; border-bottom: 2px solid #DC2626; padding-bottom: 8px; margin-bottom: 12px; }
    .logo { font-size: 24px; font-weight: bold; color: #DC2626; }
    .branch { font-size: 14px; color: #444; }
    .address { font-size: 10px; color: #888; }
    .row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; padding: 3px 0; border-bottom: 1px dotted #ddd; }
    .row .label { color: #666; }
    .row .value { font-weight: bold; text-align: right; }
    .amount { text-align: center; border: 2px solid #DC2626; padding: 10px; margin: 12px 0; }
    .amount-label { font-size: 11px; color: #666; }
    .amount-value { font-size: 22px; font-weight: bold; color: #DC2626; }
    .amount-sub { font-size: 13px; color: #444; margin-top: 4px; }
    .amount-rate { font-size: 10px; color: #888; margin-top: 4px; }
    .missing { background: #FEE2E2; border: 1px solid #FCA5A5; border-radius: 4px; padding: 8px; margin: 10px 0; }
    .missing-title { color: #B91C1C; font-weight: bold; font-size: 12px; margin-bottom: 4px; }
    .missing .row { border-bottom-color: #FCA5A5; }
    .missing .value { color: #B91C1C; }
    .reason { font-size: 11px; color: #7F1D1D; margin-top: 4px; }
    .net { font-size: 12px; margin-top: 6px; font-weight: bold; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; color: #fff; }
    .badge-validee { background: #10B981; }
    .badge-en_attente { background: #F59E0B; }
    .badge-manquant { background: #EF4444; }
    .badge-rejetee { background: #6B7280; }
    .note { font-size: 11px; color: #065F46; background: #D1FAE5; padding: 4px 6px; border-radius: 4px; margin-top: 6px; }
    .footer { text-align: center; font-size: 10px; color: #999; border-top: 1px solid #ddd; padding-top: 8px; margin-top: 12px; }
    @media print {
        @page { margin: 0.5cm; }
        body { padding: 0; }
        .receipt { margin-bottom: 0; }
    }
"""


def _fmt_usd(value):
    return f"${Decimal(value or 0):,.2f}"


def _fmt_fc(value):
    return f"{Decimal(value or 0):,.0f} FC"


def _row(label, value):
    return f'<div class="row"><span class="label">{escape(label)}</span><span class="value">{value}</span></div>'


def _client_label(vente):
    if vente.abonne:
        return f"{escape(vente.abonne.nom_entreprise)} (Abonné {escape(vente.abonne.code_client)})"
    if getattr(vente, 'partenaire', None):
        return f"{escape(vente.partenaire.nom)} (Partenaire)"
    return "Client standard"


def _unit_price(vente):
    qty = Decimal(vente.quantite or 0)
    if qty <= 0:
        return '-'
    if vente.montant_usd and vente.montant_usd > 0:
        return f"{_fmt_usd(vente.montant_usd / qty)} / L"
    if vente.montant_fc and vente.montant_fc > 0:
        return f"{_fmt_fc(vente.montant_fc / qty)} / L"
    return '-'


def render_receipt_block(vente):
    """HTML for one receipt. Used identically for single and multiple prints."""
    branche = vente.branche
    address_parts = []
    if branche:
        if branche.adresse:
            address_parts.append(escape(branche.adresse))
        city = ', '.join(p for p in [branche.ville, branche.province] if p)
        if city:
            address_parts.append(escape(city))

    pompiste = f"{escape(vente.pompiste.prenom)} {escape(vente.pompiste.nom)}" if vente.pompiste else 'N/A'
    has_missing = (vente.manquant_usd or 0) > 0 or (vente.manquant_fc or 0) > 0

    missing_html = ''
    if has_missing:
        missing_rows = ''
        if (vente.manquant_usd or 0) > 0:
            missing_rows += _row('Manquant USD', _fmt_usd(vente.manquant_usd))
        if (vente.manquant_fc or 0) > 0:
            missing_rows += _row('Manquant FC', _fmt_fc(vente.manquant_fc))
        reason = f'<div class="reason">Raison : {escape(vente.raison_manquant)}</div>' if vente.raison_manquant else ''
        net = (
            f'<div class="net">Montant net encaissé : {_fmt_usd(vente.montant_total_usd)}'
            f' / {_fmt_fc(vente.montant_total_fc)}</div>'
        )
        missing_html = f'''
        <div class="missing">
            <div class="missing-title">⚠ MANQUANT SIGNALÉ</div>
            {missing_rows}
            {reason}
            {net}
        </div>'''

    cash_note = ''
    if getattr(vente, 'regle_comptant', False):
        cash_note = '<div class="note">Réglé comptant par le client (non débité du compte abonné)</div>'

    caissier = vente.caissier.get_full_name() if vente.caissier else None
    validated = timezone.localtime(vente.validated_at).strftime('%d/%m/%Y %H:%M') if vente.validated_at else None
    created = timezone.localtime(vente.created_at).strftime('%d/%m/%Y à %H:%M')

    return f'''
    <div class="receipt">
        <div class="header">
            <div class="logo">PETROX</div>
            <div class="branch">{escape(branche.nom) if branche else ''}</div>
            <div class="address">{'<br>'.join(address_parts)}</div>
        </div>

        {_row('N° Transaction', f'VTE-{vente.id:06d}')}
        {_row('Date', created)}
        {_row('Pompiste', pompiste)}
        {_row('Client', _client_label(vente))}
        {_row('Carburant', escape(vente.type_carburant.nom) if vente.type_carburant else 'N/A')}
        {_row('Quantité', f'{Decimal(vente.quantite or 0):,.2f} L')}
        {_row('Prix unitaire', _unit_price(vente))}
        {_row('Moyen de paiement', escape(vente.moyen_paiement.nom) if vente.moyen_paiement else 'N/A')}
        {cash_note}

        <div class="amount">
            <div class="amount-label">MONTANT TOTAL</div>
            <div class="amount-value">{_fmt_usd(vente.montant_usd)}</div>
            <div class="amount-sub">{_fmt_fc(vente.montant_fc)}</div>
            <div class="amount-rate">Taux : 1 USD = {Decimal(vente.taux_change or 0):,.2f} FC</div>
        </div>

        {missing_html}

        {_row('Statut', f'<span class="badge badge-{escape(vente.statut)}">{escape(vente.get_statut_display())}</span>')}
        {_row('Validé par', escape(caissier)) if caissier else ''}
        {_row('Validé le', validated) if validated else ''}

        <div class="footer">
            <div>Merci de votre visite !</div>
            <div>PETROX - Gestion de Stations</div>
            <div>Imprimé le {timezone.localtime().strftime('%d/%m/%Y à %H:%M')}</div>
        </div>
    </div>'''


def render_receipts_response(ventes, title='Reçu de vente'):
    """Full printable HTML page for one or many sales (same layout either way)."""
    ventes = list(ventes)
    if not ventes:
        return HttpResponse(
            '<html><body style="font-family: Arial; padding: 20px;"><h3>Aucune vente trouvée</h3></body></html>'
        )
    blocks = ''.join(render_receipt_block(v) for v in ventes)
    html = f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
    <style>{RECEIPT_CSS}</style>
</head>
<body>
    {blocks}
    <script>window.onload = function () {{ window.print(); }};</script>
</body>
</html>'''
    return HttpResponse(html, content_type='text/html')


def receipts_queryset(user, ids):
    """Sales the user may print. Non-admin users only see their own branch."""
    qs = Vente.objects.filter(id__in=ids).select_related(
        'branche', 'pompiste', 'manager', 'caissier', 'type_carburant',
        'moyen_paiement', 'abonne', 'partenaire'
    ).order_by('-created_at')
    if getattr(user, 'role', None) != 'admin':
        qs = qs.filter(branche=user.branche)
    return qs


def parse_ids(raw):
    ids = []
    for part in (raw or '').split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids
