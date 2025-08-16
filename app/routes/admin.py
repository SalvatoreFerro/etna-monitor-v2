from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from ..utils.auth import admin_required
from ..models import db
from ..models.user import User

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
