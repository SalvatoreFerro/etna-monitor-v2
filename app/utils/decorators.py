from functools import wraps
from flask import jsonify, flash, redirect, url_for, request
from .auth import get_current_user

def requires_premium(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.is_json:
                return jsonify({"error": "Authentication required"}), 401
            flash('Please log in to access this feature.', 'error')
            return redirect(url_for('auth.login'))
        
        if not user.has_premium_access:
            if request.is_json:
                return jsonify({
                    "error": "Premium subscription required",
                    "upgrade_url": url_for('main.pricing')
                }), 403
            flash('Premium subscription required for this feature.', 'error')
            return redirect(url_for('main.pricing'))
        
        return f(*args, **kwargs)
    return decorated_function

def requires_plan(plan_level):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                if request.is_json:
                    return jsonify({"error": "Authentication required"}), 401
                return redirect(url_for('auth.login'))
            
            if plan_level == "premium" and not user.has_premium_access:
                if request.is_json:
                    return jsonify({
                        "error": "Premium subscription required",
                        "current_plan": "free",
                        "required_plan": "premium"
                    }), 403
                flash('Premium subscription required.', 'error')
                return redirect(url_for('main.pricing'))
            
            if plan_level == "admin" and not user.is_admin:
                if request.is_json:
                    return jsonify({"error": "Admin access required"}), 403
                flash('Admin access required.', 'error')
                return redirect(url_for('main.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
