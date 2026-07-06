"""
FRED — /api/fred

Real macro indicators from the St. Louis Fed's public FRED API (CPI,
unemployment, Fed funds rate, treasury yields, GDP, etc.) via FredProvider
in data_providers.py.

Paid + free-preview, same shape as /api/scan + /api/preview/<symbol>:
  GET /api/fred/preview/<series_id>  — FREE, but limited: only the small
      whitelisted set of well-known series in _PREVIEW_SERIES, latest
      value + date only, no metadata. Lets a caller confirm this endpoint
      is live and real before paying for the full version.
  GET /api/fred/series/<series_id>   — PAID (0.01 RLUSD/USDC): any FRED
      series_id, latest observation plus full series metadata (title,
      units, frequency, seasonal adjustment, last updated).

No hardcoded series values and no fallback numbers in either route: if
FRED_API_KEY isn't configured or the upstream call fails, both return a
real error, never a placeholder.
"""
from flask import Blueprint, jsonify

from core.legacy import get_service
from proof402_integration import dual_payment

fred_bp = Blueprint('fred_bp', __name__)

# Path param route (/api/fred/series/<series_id>) so this can't be a static
# key in proof402_integration.ENDPOINTS — same reason truth_bp.py and
# iam_bp.py pass their own rlusd_endpoint_id explicitly to dual_payment().
FRED_ENDPOINT_ID = "57e061f2-04ca-4e2c-943f-41afae56e316"  # 0.01 RLUSD

# Small, well-known set for the free preview — keeps the free tier real and
# useful without giving away the paid tier's "any series + full metadata"
# value for free.
_PREVIEW_SERIES = {
    'CPIAUCSL', 'UNRATE', 'FEDFUNDS', 'DGS10', 'GDP',
}


def _get_fred():
    dm = get_service('dm')
    if dm is None or not getattr(dm, 'fred', None):
        return None, (jsonify({'error': 'ERR_SERVICE_UNAVAILABLE', 'message': 'DataManager/FredProvider not initialized'}), 503)
    if not dm.fred.available:
        return None, (jsonify({'error': 'ERR_FRED_NOT_CONFIGURED', 'message': 'FRED_API_KEY is not set on this server'}), 503)
    return dm.fred, None


@fred_bp.route('/preview/<series_id>', methods=['GET'])
def preview(series_id: str):
    series_id = series_id.strip().upper()
    if series_id not in _PREVIEW_SERIES:
        return jsonify({
            'error': 'ERR_NOT_IN_PREVIEW_SET',
            'message': f'Free preview only covers {sorted(_PREVIEW_SERIES)}. Use paid /api/fred/series/<series_id> for any series.',
            'preview_series': sorted(_PREVIEW_SERIES),
        }), 400

    fred, err = _get_fred()
    if err:
        return err

    observation = fred.get_latest_observation(series_id)
    if not observation:
        return jsonify({
            'error': 'ERR_NO_LIVE_DATA',
            'message': f'FRED returned no usable observation for series_id={series_id}. Not returning a fabricated value.',
        }), 503

    return jsonify({'series_id': observation['series_id'], 'value': observation['value'], 'date': observation['date']})


@fred_bp.route('/series/<series_id>', methods=['GET'])
@dual_payment(
    price_usdc="0.01",
    description=(
        "FRED — any Federal Reserve Economic Data series, latest real "
        "observation plus full series metadata (title, units, frequency, "
        "seasonal adjustment, last updated). Free preview at "
        "/api/fred/preview/<series_id> covers a small whitelisted set only."
    ),
    rlusd_endpoint_id=FRED_ENDPOINT_ID,
)
def series(series_id: str):
    series_id = series_id.strip().upper()
    if not series_id.replace('_', '').isalnum():
        return jsonify({'error': 'ERR_INVALID_SERIES_ID', 'message': 'series_id must be alphanumeric'}), 400

    fred, err = _get_fred()
    if err:
        return err

    observation = fred.get_latest_observation(series_id)
    if not observation:
        return jsonify({
            'error': 'ERR_NO_LIVE_DATA',
            'message': f'FRED returned no usable observation for series_id={series_id}. Not returning a fabricated value.',
        }), 503

    info = fred.get_series_info(series_id)

    return jsonify({**observation, 'info': info or None})
