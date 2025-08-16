from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from ..utils.auth import login_required, get_current_user
from ..models import db
from ..models.event import Event
from ..utils.plot import make_tremor_figure
from config import Config
import pandas as pd
import plotly
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

bp = Blueprint("dashboard", __name__)

@bp.route("/")
@login_required
def dashboard_home():
    user = get_current_user()
    
    DATA_DIR = os.getenv("DATA_DIR", "data")
    
    try:
        curva_file = os.path.join(DATA_DIR, "curva.csv")
        if os.path.exists(curva_file):
            df = pd.read_csv(curva_file, parse_dates=['timestamp'])
            df = df.tail(100)  # Last 100 points for performance
        else:
            Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
            empty_df = pd.DataFrame(columns=['timestamp', 'value'])
            empty_df.to_csv(curva_file, index=False)
            df = empty_df
        
        threshold = user.threshold if user.premium and user.threshold else Config.ALERT_THRESHOLD_DEFAULT
        
        fig = make_tremor_figure(df['timestamp'], df['value'], threshold)
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='#e6e7ea',
            height=400
        )
        graph_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        
        latest_value = df['value'].iloc[-1] if not df.empty else 0
        status = 'above' if latest_value > threshold else 'below'
        
    except Exception as e:
        graph_json = None
        latest_value = 0
        status = 'unknown'
        threshold = Config.ALERT_THRESHOLD_DEFAULT
    
    recent_events = []
    if user.premium:
        recent_events = Event.query.filter_by(user_id=user.id)\
                                 .order_by(Event.timestamp.desc())\
                                 .limit(10).all()
    
    return render_template("dashboard.html", 
                         user=user, 
                         graph_json=graph_json,
                         latest_value=latest_value,
                         threshold=threshold,
                         status=status,
                         recent_events=recent_events)

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
                    old_threshold = user.threshold
                    user.threshold = threshold_value
                    db.session.commit()
                    
                    event = Event(
                        user_id=user.id,
                        event_type='threshold_change',
                        threshold=threshold_value,
                        message=f'Threshold changed from {old_threshold} to {threshold_value} mV'
                    )
                    db.session.add(event)
                    db.session.commit()
                    
                    flash("Threshold updated successfully!", "success")
                else:
                    flash("Threshold must be between 0.1 and 100.0 mV", "error")
            except (ValueError, TypeError):
                flash("Invalid threshold value", "error")
        else:
            flash("Premium account required for custom thresholds", "error")
    
    return render_template("dashboard_settings.html", user=user, default_threshold=Config.ALERT_THRESHOLD_DEFAULT)
