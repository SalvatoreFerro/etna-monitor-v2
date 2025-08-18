from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from ..utils.auth import admin_required
from ..models import db
from ..models.user import User
from ..models.event import Event
from ..services.telegram_service import TelegramService

bp = Blueprint("admin", __name__)

@bp.route("/")
@admin_required
def admin_home():
    users = User.query.all()
    return render_template("admin.html", users=users)

@bp.route("/toggle_premium/<int:user_id>", methods=["POST"])
@admin_required
def toggle_premium(user_id):
    user = User.query.get_or_404(user_id)
    user.premium = not user.premium
    
    if not user.premium:
        user.threshold = None
    
    db.session.commit()
    
    if request.is_json:
        return jsonify({
            "success": True,
            "premium": user.premium,
            "message": f"User {user.email} {'upgraded to' if user.premium else 'downgraded from'} Premium"
        })
    else:
        flash(f"User {user.email} {'upgraded to' if user.premium else 'downgraded from'} Premium", "success")
        return redirect(url_for('admin.admin_home'))

@bp.route("/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if user.is_admin:
        if request.is_json:
            return jsonify({"success": False, "message": "Cannot delete admin users"})
        else:
            flash("Cannot delete admin users", "error")
            return redirect(url_for('admin.admin_home'))
    
    Event.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    
    if request.is_json:
        return jsonify({"success": True, "message": f"User {user.email} deleted successfully"})
    else:
        flash(f"User {user.email} deleted successfully", "success")
        return redirect(url_for('admin.admin_home'))

@bp.route("/test-alert", methods=["POST"])
@admin_required
def test_alert():
    """Test alert endpoint - manually trigger Telegram alert checking"""
    try:
        telegram_service = TelegramService()
        result = telegram_service.check_and_send_alerts()
        
        premium_users = User.query.filter(
            User.premium == True,
            User.chat_id.isnot(None),
            User.chat_id != ''
        ).count()
        
        recent_alerts = Event.query.filter_by(event_type='alert').count()
        
        message = f"Controllo completato.\n"
        message += f"Utenti Premium con Telegram: {premium_users}\n"
        message += f"Alert totali nel sistema: {recent_alerts}"
        
        return jsonify({
            "success": True,
            "message": message
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Errore durante il controllo: {str(e)}"
        }), 500

@bp.route("/users")
@admin_required
def users_list():
    users = User.query.all()
    return jsonify([{
        "id": user.id,
        "email": user.email,
        "premium": user.premium,
        "is_admin": user.is_admin,
        "chat_id": user.chat_id,
        "threshold": user.threshold
    } for user in users])
