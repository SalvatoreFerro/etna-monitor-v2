from flask import session
from .utils.auth import get_current_user

def inject_user():
    return dict(current_user=get_current_user())
