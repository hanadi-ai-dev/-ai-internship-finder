"""Explicit approval, idempotency, and delivery uncertainty handling."""
import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from .core import now, demo


def draft(store, opportunity_id, applicant_summary):
    item = store.get(opportunity_id)
    if not item:
        raise ValueError('Unknown opportunity')
    if not item.get('email') or item.get('email_kind') != 'recruitment':
        return {'manual_required':True, 'reason':'Only verified recruitment emails support email applications', 'source_url':item['source_url']}
    prior = store.db.execute('SELECT payload FROM applications WHERE id=?', (opportunity_id,)).fetchone()
    if prior:
        return json.loads(prior[0])
    application = {'id':opportunity_id, 'opportunity_id':opportunity_id, 'state':'draft', 'created_at':now(),
        'recipient':item['email'], 'subject':f"Internship application — {item['title']}",
        'body':f"Dear {item['company']} Recruitment Team,\n\nI am writing to apply for {item['title']}.\n\n{applicant_summary}\n\nPlease find my CV and university training letter attached. I would welcome the opportunity to discuss my suitability and availability.\n\nKind regards"}
    save(store, application)
    return application


def save(store, application):
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO applications VALUES(?,?)', (application['id'], json.dumps(application)))


def approve(store, id):
    row = store.db.execute('SELECT payload FROM applications WHERE id=?', (id,)).fetchone()
    if not row:
        raise ValueError('Unknown application')
    item = json.loads(row[0])
    if item['state'] != 'draft':
        raise ValueError('Only drafts can be approved')
    item.update(state='approved', approved_at=now())
    save(store, item)
    return item


def send(store, id):
    if demo() or os.getenv('EMAIL_SENDING_ENABLED', 'false').lower() != 'true':
        raise ValueError('Email sending disabled')
    # Claim + rate check in one transaction; uncertain sends cannot be retried automatically.
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        row = store.db.execute('SELECT payload FROM applications WHERE id=?', (id,)).fetchone()
        if not row:
            raise ValueError('Unknown application')
        item = json.loads(row[0])
        auto = os.getenv('EMAIL_AUTO_APPROVED', 'false').lower() == 'true'
        if item['state'] != 'approved' and not (auto and item['state'] == 'draft'):
            raise ValueError('Approval required or application already attempted')
        today = datetime.now(timezone.utc).date().isoformat()
        attempts = sum(1 for a in store.all('applications') if a.get('attempted_at', '').startswith(today))
        if attempts >= int(os.getenv('EMAIL_DAILY_LIMIT', '5')):
            raise ValueError('Daily send limit reached')
        msg = EmailMessage()
        msg['To'], msg['From'], msg['Subject'] = item['recipient'], os.environ['SMTP_FROM'], item['subject']
        msg.set_content(item['body'])
        for variable in ('CV_PATH', 'TRAINING_LETTER_PATH'):
            path = Path(os.environ[variable])
            if path.suffix.lower() != '.pdf' or path.stat().st_size > 10_000_000:
                raise ValueError('Attachments must be PDFs under 10 MB')
            msg.add_attachment(path.read_bytes(), maintype='application', subtype='pdf', filename=path.name)
        item.update(state='sending', attempted_at=now())
        store.db.execute('UPDATE applications SET payload=? WHERE id=?', (json.dumps(item), id))
    try:
        with smtplib.SMTP_SSL(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '465')), context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            smtp.send_message(msg)
        item.update(state='sent', sent_at=now())
        save(store, item)
        store.status(item['opportunity_id'], 'Applied')
    except Exception:
        item.update(state='delivery_unknown', error='Delivery failed or uncertain; manual reconciliation required; automatic retry blocked')
        save(store, item)
        raise ValueError(item['error']) from None
    return item
