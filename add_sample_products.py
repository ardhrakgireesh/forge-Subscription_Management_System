"""TEMPORARY helper so you can test subscription lines before the Products page exists.

Run once:  py add_sample_products.py
It is safe to run twice. DELETE this file before your final commit
(your friend's seed.py will create the real demo data).
"""
from app import app, init_db
from models import db, Tax, Product, ProductVariant

init_db()   # makes sure the tables exist

with app.app_context():
    if not Tax.query.filter_by(name="GST 18%").first():
        db.session.add(Tax(name="GST 18%", rate=18))

    samples = [
        ("Accounting Suite", "Software", 1000, 400),
        ("Support Add-on", "Add-on", 250, 80),
        ("Extra Storage", "Add-on", 150, 40),
    ]
    for name, kind, sales, cost in samples:
        if not Product.query.filter_by(name=name).first():
            db.session.add(Product(name=name, type=kind, sales_price=sales, cost_price=cost))
    db.session.flush()

    suite = Product.query.filter_by(name="Accounting Suite").first()
    if not ProductVariant.query.filter_by(product_id=suite.id, value="Odoo").first():
        db.session.add(ProductVariant(product_id=suite.id, attribute="Brand", value="Odoo", extra_price=560))
    db.session.commit()
    print("Sample products ready:", Product.query.count(), "products,", Tax.query.count(), "taxes")
