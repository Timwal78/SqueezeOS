"""
CREDIT REPAIR BEAST — AI-Powered Dispute Engine
Registered as a Flask Blueprint into server_v5.py.
"""
import os
import json
import uuid
import time
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

credit_bp = Blueprint('credit', __name__)

DATA_FILE = 'credit_disputes.json'
BUREAUS = ['equifax', 'experian', 'transunion']

LETTER_TYPES = {
    '611':        'Initial Dispute (Section 611 FCRA)',
    '609':        'Document Request (Section 609 FCRA)',
    'mov':        'Method of Verification Demand',
    '623':        'Direct Furnisher Dispute (Section 623 FCRA)',
    'fdcpa':      'Debt Validation (FDCPA Section 809b)',
    'goodwill':   'Goodwill Deletion Request',
    'pay_delete': 'Pay for Delete Offer',
    'cfpb':       'CFPB Nuclear — Bureau Complaint',
    'attorney':   'Attorney Threat Letter (FCRA Lawsuit)',
}

LETTER_PROMPTS = {
    '611': (
        "Write a formal FCRA Section 611 credit dispute letter. "
        "Demand the bureau investigate and delete the item within 30 days. "
        "Cite 15 U.S.C. § 1681i. Be firm and professional."
    ),
    '609': (
        "Write a Section 609 FCRA letter demanding the bureau provide original "
        "signed documentation proving this account belongs to the consumer. "
        "Cite 15 U.S.C. § 1681g. Demand response within 30 days."
    ),
    'mov': (
        "Write a Method of Verification demand letter. The bureau previously claimed "
        "to have verified this item. Demand they explain exactly HOW they verified it — "
        "who they contacted, what documents they reviewed. Cite 15 U.S.C. § 1681i(a)(6)(B)(iii)."
    ),
    '623': (
        "Write a direct furnisher dispute letter under FCRA Section 623. "
        "This goes to the original creditor/furnisher, not the bureau. "
        "Demand they investigate and correct or delete the inaccurate information. "
        "Cite 15 U.S.C. § 1681s-2(b)."
    ),
    'fdcpa': (
        "Write an FDCPA Section 809(b) debt validation letter. "
        "Demand the collector provide: original creditor name, amount owed with breakdown, "
        "proof they have right to collect, copy of original signed agreement. "
        "Cite 15 U.S.C. § 1692g(b). All collection activity must cease until validated."
    ),
    'goodwill': (
        "Write a goodwill deletion letter. This account has been paid/resolved. "
        "Appeal to the creditor's goodwill to remove the negative mark as a courtesy. "
        "Be humble, explain the circumstances, mention long relationship if applicable. "
        "No legal threats — this is a polite request."
    ),
    'pay_delete': (
        "Write a pay-for-delete negotiation letter. Offer to pay the balance in full "
        "or settle for a percentage in exchange for complete deletion from all credit bureaus. "
        "Make clear this is contingent on deletion BEFORE payment. Request written agreement."
    ),
    'cfpb': (
        "Write a letter notifying the bureau that the consumer is filing a formal complaint "
        "with the CFPB (Consumer Financial Protection Bureau), their state Attorney General, "
        "and the FTC for failure to properly investigate. Include that this constitutes "
        "a willful violation under 15 U.S.C. § 1681n. This is the nuclear option."
    ),
    'attorney': (
        "Write a final demand letter threatening FCRA litigation. State the consumer has "
        "consulted with an FCRA attorney and is prepared to file suit for willful non-compliance. "
        "Under 15 U.S.C. § 1681n, the consumer can recover actual damages, punitive damages up to "
        "$1,000 per violation, plus attorney fees. Give 15 days to resolve before filing. "
        "Make this sound like it came from a law office."
    ),
}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": [], "profile": {}, "score_log": []}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_deadline(sent_ts):
    return datetime.fromtimestamp(sent_ts) + timedelta(days=30)

def escalation_needed(dispute):
    if dispute.get('status') not in ('PENDING', 'VERIFIED'):
        return False
    sent = dispute.get('sent_date')
    if not sent:
        return False
    deadline = get_deadline(sent)
    return datetime.now() > deadline

# ── Routes (API only — static files served by server_v5.py) ─────────────────

@credit_bp.route('/api/credit/profile', methods=['GET', 'POST'])
def profile():
    data = load_data()
    if request.method == 'POST':
        data['profile'] = request.json
        save_data(data)
        return jsonify({"status": "saved"})
    return jsonify(data.get('profile', {}))

@credit_bp.route('/api/credit/items', methods=['GET'])
def get_items():
    data = load_data()
    items = data.get('items', [])
    # Flag items needing escalation
    for item in items:
        for d in item.get('disputes', []):
            if escalation_needed(d):
                d['needs_escalation'] = True
    return jsonify(items)

@credit_bp.route('/api/credit/items', methods=['POST'])
def add_item():
    data = load_data()
    item = request.json
    item['id'] = str(uuid.uuid4())[:8]
    item['added_at'] = time.time()
    item['disputes'] = []
    data['items'].append(item)
    save_data(data)
    return jsonify({"status": "added", "id": item['id']})

@credit_bp.route('/api/credit/items/<item_id>', methods=['DELETE'])
def delete_item(item_id):
    data = load_data()
    data['items'] = [i for i in data['items'] if i.get('id') != item_id]
    save_data(data)
    return jsonify({"status": "deleted"})

@credit_bp.route('/api/credit/generate', methods=['POST'])
def generate_letter():
    body = request.json or {}
    item_id     = body.get('item_id')
    bureau      = body.get('bureau', 'equifax').lower()
    letter_type = body.get('letter_type', '611')
    round_num   = body.get('round', 1)

    data = load_data()
    item = next((i for i in data['items'] if i.get('id') == item_id), None)
    if not item:
        return jsonify({"error": "Item not found"}), 404

    profile = data.get('profile', {})
    name    = profile.get('name', '[YOUR NAME]')
    address = profile.get('address', '[YOUR ADDRESS]')
    city    = profile.get('city', '[CITY, STATE ZIP]')
    ssn4    = profile.get('ssn4', 'XXXX')
    dob     = profile.get('dob', '[DATE OF BIRTH]')

    creditor   = item.get('creditor', 'Unknown Creditor')
    acct_num   = item.get('account_number', 'Unknown')
    amount     = item.get('amount', 0)
    item_type  = item.get('account_type', 'account')
    dispute_reason = item.get('dispute_reason', 'This item is inaccurate and unverifiable')

    bureau_addresses = {
        'equifax':    'Equifax Information Services LLC\nP.O. Box 740256\nAtlanta, GA 30374',
        'experian':   'Experian\nP.O. Box 4500\nAllen, TX 75013',
        'transunion': 'TransUnion LLC\nConsumer Dispute Center\nP.O. Box 2000\nChester, PA 19016',
    }
    bureau_address = bureau_addresses.get(bureau, bureau.title())
    bureau_label   = bureau.title()
    today          = datetime.now().strftime('%B %d, %Y')
    deadline_date  = (datetime.now() + timedelta(days=30)).strftime('%B %d, %Y')

    context = (
        f"Consumer: {name}, DOB: {dob}, Last 4 SSN: {ssn4}\n"
        f"Address: {address}, {city}\n"
        f"Bureau: {bureau_label}\n"
        f"Bureau Address: {bureau_address}\n"
        f"Creditor/Furnisher: {creditor}\n"
        f"Account Number: {acct_num}\n"
        f"Account Type: {item_type}\n"
        f"Amount: ${amount:,.2f}\n"
        f"Dispute Reason: {dispute_reason}\n"
        f"Letter Type: {LETTER_TYPES.get(letter_type, letter_type)}\n"
        f"Round: {round_num}\n"
        f"Date: {today}\n"
        f"Response Deadline: {deadline_date}\n\n"
    )

    instruction = LETTER_PROMPTS.get(letter_type, LETTER_PROMPTS['611'])
    prompt = (
        f"{context}"
        f"Task: {instruction}\n\n"
        f"Format as a complete formal letter with date, addresses, re: line, body paragraphs, "
        f"and signature block. Include relevant FCRA/FDCPA statute citations. "
        f"Do NOT add any notes or caveats after the letter. Output the letter only."
    )

    try:
        llm = get_llm()
        letter = llm._chat(prompt, system=(
            "You are an expert FCRA/FDCPA consumer rights attorney. "
            "Write aggressive, legally precise dispute letters that get results. "
            "Include exact statute citations. Never add disclaimers after the letter."
        ), timeout=60)
    except Exception as e:
        return jsonify({"error": f"LLM unavailable: {e}"}), 503

    # Save dispute record
    dispute = {
        "id": str(uuid.uuid4())[:8],
        "bureau": bureau,
        "letter_type": letter_type,
        "letter_label": LETTER_TYPES.get(letter_type, letter_type),
        "round": round_num,
        "sent_date": None,
        "sent_ts": None,
        "status": "DRAFT",
        "letter": letter,
        "created_at": time.time(),
    }
    item['disputes'].append(dispute)
    save_data(data)

    return jsonify({"status": "ok", "letter": letter, "dispute_id": dispute['id']})

@credit_bp.route('/api/credit/dispute/<item_id>/<dispute_id>/status', methods=['POST'])
def update_dispute_status(item_id, dispute_id):
    body   = request.json or {}
    status = body.get('status', 'PENDING')
    data   = load_data()
    item   = next((i for i in data['items'] if i.get('id') == item_id), None)
    if not item:
        return jsonify({"error": "Not found"}), 404
    dispute = next((d for d in item.get('disputes', []) if d.get('id') == dispute_id), None)
    if not dispute:
        return jsonify({"error": "Dispute not found"}), 404

    dispute['status'] = status
    if status == 'PENDING' and not dispute.get('sent_ts'):
        dispute['sent_ts'] = time.time()
        dispute['sent_date'] = datetime.now().strftime('%Y-%m-%d')
        dispute['deadline'] = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    save_data(data)
    return jsonify({"status": "updated"})

@credit_bp.route('/api/credit/score', methods=['GET', 'POST'])
def score_log():
    data = load_data()
    if request.method == 'POST':
        entry = request.json
        entry['ts'] = time.time()
        entry['date'] = datetime.now().strftime('%Y-%m-%d')
        data.setdefault('score_log', []).append(entry)
        save_data(data)
        return jsonify({"status": "logged"})
    return jsonify(data.get('score_log', []))

@credit_bp.route('/api/credit/stats', methods=['GET'])
def stats():
    data  = load_data()
    items = data.get('items', [])
    total = len(items)
    all_disputes = [d for i in items for d in i.get('disputes', [])]
    deleted  = sum(1 for i in items if any(d.get('status') == 'DELETED' for d in i.get('disputes', [])))
    pending  = sum(1 for d in all_disputes if d.get('status') == 'PENDING')
    drafts   = sum(1 for d in all_disputes if d.get('status') == 'DRAFT')
    escalate = sum(1 for d in all_disputes if escalation_needed(d))
    win_rate = round((deleted / total * 100) if total else 0)
    score_log = data.get('score_log', [])
    score_gain = 0
    if len(score_log) >= 2:
        score_gain = score_log[-1].get('score', 0) - score_log[0].get('score', 0)
    return jsonify({
        "total_items": total,
        "deleted": deleted,
        "pending": pending,
        "drafts": drafts,
        "needs_escalation": escalate,
        "win_rate": win_rate,
        "score_gain": score_gain,
        "letters_generated": len(all_disputes),
    })

# Standalone runner (optional — normally loaded as blueprint by server_v5.py)
if __name__ == '__main__':
    from flask import Flask
    from flask_cors import CORS
    standalone = Flask(__name__, static_folder='.', static_url_path='')
    CORS(standalone)
    standalone.register_blueprint(credit_bp)
    port = int(os.environ.get('CREDIT_PORT', 8183))
    standalone.run(host='0.0.0.0', port=port, debug=False)
