from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Sum, Avg, Count, F, Q


def calculate_forex_impact(vente, current_rate):
    """
    Calculate forex impact for a single sale transaction.
    
    Args:
        vente: Vente object with montant_usd, montant_fc, taux_change
        current_rate: Current exchange rate (Decimal)
    
    Returns:
        dict with forex impact details
    """
    if not vente.taux_change or vente.taux_change == current_rate:
        return {
            'has_impact': False,
            'impact_usd': Decimal('0'),
            'impact_fc': Decimal('0'),
            'impact_type': 'neutral'
        }
    
    # Expected FC at current rate
    expected_fc = vente.montant_usd * current_rate
    actual_fc = vente.montant_fc
    
    # Forex impact in FC
    fc_difference = actual_fc - expected_fc
    
    # Convert to USD for reporting
    usd_impact = fc_difference / current_rate if current_rate > 0 else Decimal('0')
    
    return {
        'has_impact': True,
        'impact_usd': round_decimal(usd_impact),
        'impact_fc': round_decimal(fc_difference),
        'impact_type': 'gain' if usd_impact > 0 else 'loss' if usd_impact < 0 else 'neutral',
        'taux_applique': vente.taux_change,
        'taux_actuel': current_rate,
        'difference_taux': current_rate - vente.taux_change
    }


def calculate_bulk_forex_impact(ventes_queryset, current_rate):
    """
    Calculate total forex impact for a queryset of sales.
    
    Args:
        ventes_queryset: QuerySet of Vente objects
        current_rate: Current exchange rate (Decimal)
    
    Returns:
        dict with aggregated forex impact
    """
    total_impact_usd = Decimal('0')
    total_impact_fc = Decimal('0')
    transactions_with_impact = 0
    
    by_carburant = {}
    by_branche = {}
    
    for vente in ventes_queryset:
        impact = calculate_forex_impact(vente, current_rate)
        
        if impact['has_impact']:
            transactions_with_impact += 1
            total_impact_usd += impact['impact_usd']
            total_impact_fc += impact['impact_fc']
            
            # Group by fuel type
            if vente.type_carburant:
                fuel_name = vente.type_carburant.nom
                if fuel_name not in by_carburant:
                    by_carburant[fuel_name] = {
                        'impact_usd': Decimal('0'),
                        'impact_fc': Decimal('0'),
                        'count': 0
                    }
                by_carburant[fuel_name]['impact_usd'] += impact['impact_usd']
                by_carburant[fuel_name]['impact_fc'] += impact['impact_fc']
                by_carburant[fuel_name]['count'] += 1
            
            # Group by branch
            if vente.branche:
                branch_name = vente.branche.nom
                if branch_name not in by_branche:
                    by_branche[branch_name] = {
                        'impact_usd': Decimal('0'),
                        'impact_fc': Decimal('0'),
                        'count': 0
                    }
                by_branche[branch_name]['impact_usd'] += impact['impact_usd']
                by_branche[branch_name]['impact_fc'] += impact['impact_fc']
                by_branche[branch_name]['count'] += 1
    
    return {
        'total_impact_usd': round_decimal(total_impact_usd),
        'total_impact_fc': round_decimal(total_impact_fc),
        'impact_type': 'gain' if total_impact_usd > 0 else 'loss' if total_impact_usd < 0 else 'neutral',
        'transactions_analyzed': ventes_queryset.count(),
        'transactions_with_impact': transactions_with_impact,
        'by_carburant': {k: {
            'impact_usd': str(v['impact_usd']),
            'impact_fc': str(v['impact_fc']),
            'count': v['count']
        } for k, v in by_carburant.items()},
        'by_branche': {k: {
            'impact_usd': str(v['impact_usd']),
            'impact_fc': str(v['impact_fc']),
            'count': v['count']
        } for k, v in by_branche.items()}
    }


def round_decimal(value, places=2):
    """
    Round a Decimal value to specified decimal places.
    
    Args:
        value: Decimal value to round
        places: Number of decimal places (default: 2)
    
    Returns:
        Rounded Decimal
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    
    quantize_str = '0.' + '0' * places
    return value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def format_currency(amount, currency='USD'):
    """
    Format amount as currency string.
    
    Args:
        amount: Decimal or float amount
        currency: Currency code ('USD' or 'FC')
    
    Returns:
        Formatted currency string
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    
    amount = round_decimal(amount)
    
    if currency == 'USD':
        return f"${amount:,.2f}"
    else:  # FC
        return f"{amount:,.2f} FC"


def calculate_trend(current, previous):
    """
    Calculate percentage change between two values.
    
    Args:
        current: Current period value
        previous: Previous period value
    
    Returns:
        dict with trend information
    """
    if not isinstance(current, Decimal):
        current = Decimal(str(current))
    if not isinstance(previous, Decimal):
        previous = Decimal(str(previous))
    
    if previous == 0:
        if current > 0:
            return {'value': 100.0, 'direction': 'up', 'change': float(current)}
        return {'value': 0.0, 'direction': 'stable', 'change': 0.0}
    
    change = ((current - previous) / previous) * 100
    direction = 'up' if change > 0 else 'down' if change < 0 else 'stable'
    
    return {
        'value': round(abs(float(change)), 1),
        'direction': direction,
        'change': float(current - previous)
    }


def get_date_range(period, custom_start=None, custom_end=None):
    """
    Get start and end dates for a given period.
    
    Args:
        period: Period string ('today', 'week', 'month', 'year', 'custom')
        custom_start: Custom start date (for 'custom' period)
        custom_end: Custom end date (for 'custom' period)
    
    Returns:
        tuple (start_date, end_date)
    """
    today = timezone.now().date()
    
    if period == 'today':
        return today, today
    elif period == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif period == 'week':
        return today - timedelta(days=7), today
    elif period == 'month':
        return today - timedelta(days=30), today
    elif period == 'quarter':
        return today - timedelta(days=90), today
    elif period == 'year':
        return today - timedelta(days=365), today
    elif period == 'custom' and custom_start and custom_end:
        if isinstance(custom_start, str):
            custom_start = datetime.strptime(custom_start, '%Y-%m-%d').date()
        if isinstance(custom_end, str):
            custom_end = datetime.strptime(custom_end, '%Y-%m-%d').date()
        return custom_start, custom_end
    else:
        return today - timedelta(days=30), today


def get_previous_period(start_date, end_date):
    """
    Get the previous period dates for comparison.
    
    Args:
        start_date: Start date of current period
        end_date: End date of current period
    
    Returns:
        tuple (prev_start_date, prev_end_date)
    """
    period_days = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    return prev_start, prev_end


def convert_currency(amount, from_currency, to_currency, rate):
    """
    Convert amount between USD and FC.
    
    Args:
        amount: Amount to convert
        from_currency: Source currency ('USD' or 'FC')
        to_currency: Target currency ('USD' or 'FC')
        rate: Exchange rate (FC per USD)
    
    Returns:
        Converted Decimal amount
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    if not isinstance(rate, Decimal):
        rate = Decimal(str(rate))
    
    if from_currency == to_currency:
        return amount
    
    if from_currency == 'USD' and to_currency == 'FC':
        return round_decimal(amount * rate)
    elif from_currency == 'FC' and to_currency == 'USD':
        return round_decimal(amount / rate) if rate > 0 else Decimal('0')
    
    return amount


def calculate_stock_status(quantity, threshold, capacity):
    """
    Determine stock status based on current quantity.
    
    Args:
        quantity: Current stock quantity
        threshold: Alert threshold
        capacity: Maximum capacity
    
    Returns:
        dict with status information
    """
    if not isinstance(quantity, Decimal):
        quantity = Decimal(str(quantity))
    if not isinstance(threshold, Decimal):
        threshold = Decimal(str(threshold))
    if not isinstance(capacity, Decimal):
        capacity = Decimal(str(capacity))
    
    percentage = (quantity / capacity * 100) if capacity > 0 else Decimal('0')
    
    if quantity <= threshold * Decimal('0.5'):
        status = 'critical'
        status_label = 'Critique'
        status_class = 'danger'
    elif quantity <= threshold:
        status = 'low'
        status_label = 'Bas'
        status_class = 'warning'
    elif quantity <= threshold * Decimal('1.5'):
        status = 'moderate'
        status_label = 'Modéré'
        status_class = 'info'
    else:
        status = 'normal'
        status_label = 'Normal'
        status_class = 'success'
    
    return {
        'status': status,
        'status_label': status_label,
        'status_class': status_class,
        'percentage': round(float(percentage), 1),
        'is_alert': status in ['critical', 'low']
    }


def generate_report_filename(report_type, start_date=None, end_date=None, extension='pdf'):
    """
    Generate a standardized filename for reports.
    
    Args:
        report_type: Type of report (e.g., 'financial', 'sales', 'stock')
        start_date: Optional start date
        end_date: Optional end date
        extension: File extension (default: 'pdf')
    
    Returns:
        Formatted filename string
    """
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    
    if start_date and end_date:
        date_range = f"_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
    else:
        date_range = f"_{timestamp}"
    
    return f"petrox_{report_type}{date_range}.{extension}"


def sanitize_filename(filename):
    """
    Sanitize a filename to remove invalid characters.
    
    Args:
        filename: Original filename
    
    Returns:
        Sanitized filename
    """
    import re
    # Remove invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(' .')
    # Limit length
    if len(sanitized) > 200:
        name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
        name = name[:200 - len(ext) - 1]
        sanitized = f"{name}.{ext}" if ext else name
    
    return sanitized


def format_phone_number(phone):
    """
    Format phone number for display.
    
    Args:
        phone: Phone number string
    
    Returns:
        Formatted phone number
    """
    if not phone:
        return ''
    
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    
    # Format based on length (DRC format)
    if len(digits) == 9:
        # Format: 0XX XXX XXX
        return f"0{digits[:2]} {digits[2:5]} {digits[5:]}"
    elif len(digits) == 10:
        # Format: 0XX XXX XXXX
        return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
    elif len(digits) == 12 and digits.startswith('243'):
        # International format: +243 XX XXX XXXX
        return f"+{digits[:3]} {digits[3:5]} {digits[5:8]} {digits[8:]}"
    
    return phone


def calculate_abonne_balance_status(abonne):
    """
    Calculate the financial status of an abonné.
    
    Args:
        abonne: Abonne object
    
    Returns:
        dict with balance status information
    """
    from apps.core.models import TauxChange
    
    current_rate = TauxChange.get_current_rate()
    
    # Convert everything to USD for comparison
    total_usd = abonne.solde_usd + (abonne.solde_fc / current_rate)
    
    if abonne.type_abonnement == 'prepaye':
        if total_usd > 0:
            status = 'credit'
            status_label = 'Crédit disponible'
            status_class = 'success'
        else:
            status = 'zero'
            status_label = 'Solde épuisé'
            status_class = 'warning'
    elif abonne.type_abonnement == 'postpaye':
        if total_usd >= 0:
            status = 'ok'
            status_label = 'En règle'
            status_class = 'success'
        else:
            status = 'debt'
            status_label = 'Dette en cours'
            status_class = 'warning'
    else:  # credit
        debt_ratio = abs(total_usd) / abonne.limite_credit if abonne.limite_credit > 0 else 0
        
        if debt_ratio >= 1:
            status = 'limit_reached'
            status_label = 'Limite atteinte'
            status_class = 'danger'
        elif debt_ratio >= 0.8:
            status = 'near_limit'
            status_label = 'Proche de la limite'
            status_class = 'warning'
        else:
            status = 'ok'
            status_label = 'En règle'
            status_class = 'success'
    
    return {
        'status': status,
        'status_label': status_label,
        'status_class': status_class,
        'total_usd': round_decimal(total_usd),
        'can_consume': abonne.type_abonnement != 'prepaye' or total_usd > 0
    }


def create_notification(destinataire, titre, message, type_notification='system', 
                       priorite='normale', expediteur=None, objet_id=None, lien_url=''):
    """
    Create a notification for a user.
    
    Args:
        destinataire: User to notify
        titre: Notification title
        message: Notification message
        type_notification: Type of notification
        priorite: Priority level
        expediteur: Sender user (optional)
        objet_id: Related object ID (optional)
        lien_url: Related URL (optional)
    
    Returns:
        Created Notification object
    """
    from apps.core.models import Notification
    
    return Notification.objects.create(
        destinataire=destinataire,
        expediteur=expediteur,
        type_notification=type_notification,
        priorite=priorite,
        titre=titre,
        message=message,
        objet_id=objet_id,
        lien_url=lien_url
    )


def notify_admins(titre, message, type_notification='system', priorite='normale', 
                 expediteur=None, objet_id=None):
    """
    Send a notification to all admin users.
    
    Args:
        titre: Notification title
        message: Notification message
        type_notification: Type of notification
        priorite: Priority level
        expediteur: Sender user (optional)
        objet_id: Related object ID (optional)
    
    Returns:
        List of created Notification objects
    """
    from apps.core.models import User
    
    admins = User.objects.filter(role='admin', is_active=True)
    notifications = []
    
    for admin in admins:
        notification = create_notification(
            destinataire=admin,
            titre=titre,
            message=message,
            type_notification=type_notification,
            priorite=priorite,
            expediteur=expediteur,
            objet_id=objet_id
        )
        notifications.append(notification)
    
    return notifications


def notify_branch_users(branche, titre, message, roles=None, type_notification='system', 
                       priorite='normale', expediteur=None, objet_id=None):
    """
    Send a notification to all users of a specific branch.
    
    Args:
        branche: Branche object
        titre: Notification title
        message: Notification message
        roles: List of roles to notify (default: all)
        type_notification: Type of notification
        priorite: Priority level
        expediteur: Sender user (optional)
        objet_id: Related object ID (optional)
    
    Returns:
        List of created Notification objects
    """
    from apps.core.models import User
    
    users = User.objects.filter(branche=branche, is_active=True)
    
    if roles:
        users = users.filter(role__in=roles)
    
    notifications = []
    
    for user in users:
        notification = create_notification(
            destinataire=user,
            titre=titre,
            message=message,
            type_notification=type_notification,
            priorite=priorite,
            expediteur=expediteur,
            objet_id=objet_id
        )
        notifications.append(notification)
    
    return notifications