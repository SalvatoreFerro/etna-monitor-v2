from flask import Blueprint, request, jsonify, redirect, url_for, render_template, session, flash
import stripe
import os
import json
from datetime import datetime
from ..utils.auth import login_required, get_current_user
from ..models import db
from ..models.user import User
from ..models.billing import Invoice, EventLog

bp = Blueprint("billing", __name__)

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
