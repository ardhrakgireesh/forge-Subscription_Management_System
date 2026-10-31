"""Brightloop Subscription Management System - starter app.

Run:  python app.py   then open http://127.0.0.1:5000
First admin login:  admin@brightloop.com / Admin@12345!
"""
import re
import secrets
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-me-before-deploying"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///brightloop.db"
db.init_app(app)


# ---------- validation ----------
def validate_password(pw):
    """More than 8 chars, one upper, one lower, one special character."""
    errors = []
    if len(pw) <= 8:
        errors.append("Password must be more than 8 characters.")
    if not re.search(r"[A-Z]", pw):
        errors.append("Password needs an uppercase letter.")
    if not re.search(r"[a-z]", pw):
        errors.append("Password needs a lowercase letter.")
    if not re.search(r"[^A-Za-z0-9]", pw):
        errors.append("Password needs a special character.")
    return errors


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- login helpers ----------
def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


@app.context_processor
def inject_user():
    return {"user": current_user()}


def login_required(roles=None):
    """Use @login_required() for any logged-in user, or @login_required(["admin"])."""
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


# ---------- auth routes ----------
@app.route("/")
def home():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        errors = []
        if not name:
            errors.append("Name is required.")
        if not EMAIL_RE.match(email):
            errors.append("Enter a valid email.")
        elif User.query.filter_by(email=email).first():
            errors.append("This email already has an account.")
        errors += validate_password(pw)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html", name=name, email=email)
        db.session.add(User(name=name, email=email, role="customer",
                            password_hash=generate_password_hash(pw)))
        db.session.commit()
        flash("Account created. Please log in.", "ok")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = User.query.filter_by(email=email).first()
        if u and check_password_hash(u.password_hash, request.form.get("password", "")):
            session["user_id"] = u.id
            return redirect(url_for("dashboard"))
        flash("Wrong email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = User.query.filter_by(email=email).first()
        if u:
            u.reset_token = secrets.token_urlsafe(24)
            db.session.commit()
            # TODO: send this by email (smtplib). For the demo we print it.
            print("RESET LINK:", url_for("reset", token=u.reset_token, _external=True))
        flash("If that email exists, a reset link has been sent.", "ok")
        return redirect(url_for("login"))
    return render_template("forgot.html")


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    u = User.query.filter_by(reset_token=token).first()
    if not u:
        abort(404)
    if request.method == "POST":
        pw = request.form.get("password", "")
        errors = validate_password(pw)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("reset.html")
        u.password_hash = generate_password_hash(pw)
        u.reset_token = None
        db.session.commit()
        flash("Password updated. Please log in.", "ok")
        return redirect(url_for("login"))
    return render_template("reset.html")


# ---------- admin: add staff ----------
@app.route("/staff/new", methods=["GET", "POST"])
@login_required(["admin"])
def new_staff():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        errors = validate_password(pw)
        if not name:
            errors.append("Name is required.")
        if not EMAIL_RE.match(email):
            errors.append("Enter a valid email.")
        elif User.query.filter_by(email=email).first():
            errors.append("This email already has an account.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("new_staff.html")
        db.session.add(User(name=name, email=email, role="staff",
                            password_hash=generate_password_hash(pw)))
        db.session.commit()
        flash("Staff member added.", "ok")
        return redirect(url_for("dashboard"))
    return render_template("new_staff.html")


# ---------- dashboard ----------
@app.route("/dashboard")
@login_required()
def dashboard():
    # TODO (Ardhra): replace with real numbers: active subs, revenue, outstanding, overdue
    return render_template("dashboard.html")


# ---------- setup ----------
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(role="admin").first():
            db.session.add(User(name="Admin", email="admin@brightloop.com", role="admin",
                                password_hash=generate_password_hash("Admin@12345!")))
            db.session.commit()


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
