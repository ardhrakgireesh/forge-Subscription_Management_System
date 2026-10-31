"""Small shared helpers used by every page (login check, role check)."""
from functools import wraps

from flask import session, redirect, url_for, abort

from models import db, User


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def login_required(roles=None):
    """@login_required()            -> any logged-in user
       @login_required(["admin"])   -> admin only
       @login_required(["admin", "staff"]) -> admin and staff"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            u = current_user()
            if not u:
                return redirect(url_for("login"))
            if roles and u.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator
