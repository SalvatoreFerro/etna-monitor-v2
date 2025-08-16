from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..utils.auth import login_required, get_current_user
from ..models import db
from config import Config

bp = Blueprint("dashboard", __name__)

@bp.route("/")
@login_required
def dashboard_home():
    user = get_current_user()
    return render_template("dashboard.html", user=user)

@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = get_current_user()
    
    if request.method == "POST":
        if user.premium:
            threshold = request.form.get("threshold")
            try:
                threshold_value = float(threshold)
                if 0.1 <= threshold_value <= 100.0:
                    user.threshold = threshold_value
                    db.session.commit()
                    flash("Threshold updated successfully!", "success")
                else:
                    flash("Threshold must be between 0.1 and 100.0 mV", "error")
            except (ValueError, TypeError):
                flash("Invalid threshold value", "error")
        else:
            flash("Premium account required for custom thresholds", "error")
    
    return render_template("dashboard_settings.html", user=user, default_threshold=Config.ALERT_THRESHOLD_DEFAULT)
