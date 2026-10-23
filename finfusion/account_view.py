"""Additional read-only account presentation; no trading balance behavior changes."""
from decimal import Decimal, InvalidOperation
from finfusion_common.utils import response_json, response_ok
from .errors import ApiError

CASH_FIELDS = {'usdCashBalance': 'cash_balance', 'usdSettledCash': 'settled_cash', 'usdUnsettledCash': 'unsettled_cash'}

def usd_cash_fields(payload):
    result = {name: None for name in CASH_FIELDS}
    if not isinstance(payload, dict):
        return result
    assets = payload.get('account_currency_assets') or payload.get('accountCurrencyAssets') or []
    if isinstance(assets, dict):
        assets = [assets]
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict) or str(asset.get('currency') or '').upper() != 'USD':
            continue
        for public, broker in CASH_FIELDS.items():
            raw = asset.get(broker)
            if raw is None:
                parts = broker.split('_'); raw = asset.get(parts[0] + ''.join(p.title() for p in parts[1:]))
            try:
                number = Decimal(str(raw))
                result[public] = format(number, 'f') if number.is_finite() else None
            except (InvalidOperation, ValueError, TypeError):
                pass
        break
    return result

async def read_cash_fields(gateway, broker_account_id):
    client = getattr(gateway, 'trade_client', None)
    if client is None:
        return usd_cash_fields(None)
    try:
        response = await gateway._call(client.account_v2.get_account_balance, broker_account_id)
    except Exception:
        raise ApiError('ACCOUNT_DATA_UNAVAILABLE', 'Account cash data unavailable', 503) from None
    if not response_ok(response):
        raise ApiError('ACCOUNT_DATA_UNAVAILABLE', 'Account cash data unavailable', 503)
    return usd_cash_fields(response_json(response))
