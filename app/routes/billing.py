from flask import Blueprint, request, jsonify, redirect, url_for, render_template, session, flash, current_app
import stripe
import os
import json
from datetime import datetime
from ..utils.auth import login_required, get_current_user
from ..models import db
from ..models.user import User
from ..models.billing import Invoice, EventLog
from ..utils.csrf import validate_csrf_token
from ..services.notifications import notify_admin_new_donation

bp = Blueprint("billing", __name__, url_prefix="/billing")

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

@bp.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    user = get_current_user()
    
    try:
        if not user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=user.email,
                metadata={'user_id': user.id}
            )
            user.stripe_customer_id = customer.id
            db.session.commit()
        
        checkout_session = stripe.checkout.Session.create(
            customer=user.stripe_customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': os.getenv('STRIPE_PRICE_PREMIUM'),
                'quantity': 1,
            }],
            mode='subscription',
            success_url=url_for('billing.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('main.pricing', _external=True),
            metadata={'user_id': user.id}
        )
        
        return jsonify({'checkout_url': checkout_session.url})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@bp.route('/customer-portal')
@login_required
def customer_portal():
    user = get_current_user()
    
    if not user.stripe_customer_id:
        flash('No billing account found', 'error')
        return redirect(url_for('main.pricing'))
    
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=url_for('dashboard.dashboard_home', _external=True)
        )
        return redirect(portal_session.url)
        
    except Exception as e:
        flash(f'Error accessing billing portal: {str(e)}', 'error')
        return redirect(url_for('dashboard.dashboard_home'))

@bp.route('/success')
@login_required
def success():
    session_id = request.args.get('session_id')
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            flash('Subscription activated successfully!', 'success')
        except:
            pass
    return redirect(url_for('dashboard.dashboard_home'))

@bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return 'Invalid payload', 400
    except Exception:
        return 'Invalid signature', 400
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session['metadata']['user_id']
        user = User.query.get(user_id)
        if user:
            user.premium = True
            user.is_premium = True
            if not user.premium_since:
                user.premium_since = datetime.utcnow()
            user.subscription_status = 'active'
            user.subscription_id = session['subscription']
            db.session.commit()
            
            log = EventLog(
                user_id=user_id,
                event_type='billing.subscription_created',
                event_data=json.dumps({'session_id': session['id']})
            )
            db.session.add(log)
            db.session.commit()
    
    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        user = User.query.filter_by(subscription_id=subscription['id']).first()
        if user:
            user.subscription_status = subscription['status']
            user.current_period_end = datetime.fromtimestamp(subscription['current_period_end'])
            db.session.commit()
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        user = User.query.filter_by(subscription_id=subscription['id']).first()
        if user:
            user.premium = False
            if not user.premium_lifetime:
                user.is_premium = False
            user.subscription_status = 'canceled'
            db.session.commit()
    
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        customer_id = invoice['customer']
        user = User.query.filter_by(stripe_customer_id=customer_id).first()
        if user:
            invoice_record = Invoice(
                user_id=user.id,
                stripe_invoice_id=invoice['id'],
                amount_cents=invoice['amount_paid'],
                currency=invoice['currency'],
                status='paid',
                hosted_invoice_url=invoice['hosted_invoice_url'],
                invoice_pdf=invoice['invoice_pdf']
            )
            db.session.add(invoice_record)
            db.session.commit()
    
    return 'Success', 200


@bp.route('/donate', methods=['GET'])
@login_required
def donate():
    user = get_current_user()
    return render_template('billing/donate.html', user=user)


@bp.route('/confirm_donation', methods=['POST'])
@login_required
def confirm_donation():
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('Token di sicurezza non valido. Riprova.', 'error')
        return redirect(url_for('billing.donate'))

    user = get_current_user()
    tx_id = (request.form.get('tx_id') or '').strip()
    amount = (request.form.get('amount') or '').strip()

    if not tx_id:
        flash('Inserisci un ID transazione valido.', 'error')
        return redirect(url_for('billing.donate'))

    user.donation_tx = tx_id
    db.session.commit()

    if amount:
        current_app.logger.info(
            "New PayPal donation recorded", extra={"user_email": user.email, "tx_id": tx_id, "amount": amount}
        )

    notify_admin_new_donation(user.email, tx_id)

    flash('Richiesta registrata, attiveremo il premium dopo verifica.', 'success')
    return redirect(url_for('billing.donate'))
