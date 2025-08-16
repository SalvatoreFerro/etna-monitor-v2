from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from ..models import db
from ..models.user import User
from ..utils.auth import hash_password, check_password
from config import Config

bp = Blueprint("auth", __name__)

@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("auth/register.html")
        
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("auth/register.html")
        
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
            return render_template("auth/register.html")
        
        user = User(
            email=email,
            password_hash=hash_password(password)
        )
        db.session.add(user)
        db.session.commit()
        
        session['user_id'] = user.id
        flash("Registration successful!", "success")
        return redirect(url_for('dashboard.dashboard_home'))
    
    return render_template("auth/register.html")

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("auth/login.html")
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password(password, user.password_hash):
            session['user_id'] = user.id
            flash("Login successful!", "success")
            
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('dashboard.dashboard_home'))
        else:
            flash("Invalid email or password.", "error")
    
    return render_template("auth/login.html")

@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('main.index'))
