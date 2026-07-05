"""
FRED — /api/fred

Real macro indicators from the St. Louis Fed's public FRED API (CPI,
unemployment, Fed funds rate, treasury yields, GDP, etc.) via FredProvider
in data_providers.py. FRED series are public-domain government data, so
this is a free endpoint — the value SqueezeOS adds is combining macro
context with the paid signal engines (741 Macro Matrix, Oracle, IAM), not
gatekeeping numbers the Fed already publishes for free.

No hardcoded series values and no fallback numbers: if FRED_API_KEY isn't
configured or the upstream call fails, this returns a real error, never a
placeholder.
"""
from flask import Blueprint, jsonify

from core.legacy import get_service

fred_bp = Blueprint('fred_bp', __name__)


@fred_bp.route('/series/<series_id>', methods=['GET'])
def series(series_id: str):
    series_id = series_id.strip().upper()
    if not series_id.replace('_', '').isalnum():
        return jsonify({'error': 'ERR_INVALID_SERIES_ID', 'message': 'series_id must be alphanumeric'}), 400

    dm = get_service('dm')
    if dm is None or not getattr(dm, 'fred', None):
        return jsonify({'error': 'ERR_SERVICE_UNAVAILABLE', 'message': 'DataManager/FredProvider not initialized'}), 503

    if not dm.fred.available:
        return jsonify({'error': 'ERR_FRED_NOT_CONFIGURED', 'message': 'FRED_API_KEY is not set on this server'}), 503

    observation = dm.fred.get_latest_observation(series_id)
    if not observation:
        return jsonify({
            'error': 'ERR_NO_LIVE_DATA',
            'message': f'FRED returned no usable observation for series_id={series_id}. Not returning a fabricated value.',
        }), 503

    info = dm.fred.get_series_info(series_id)

    return jsonify({**observation, 'info': info or None})
