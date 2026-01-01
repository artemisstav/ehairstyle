import os
import smtplib
from email.message import EmailMessage
from sqlalchemy import text
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy

APP_NAME = "ehairstyle"

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    db_url = (os.environ.get("DATABASE_URL") or "").strip()

    # Render sometimes provides postgres://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # Use psycopg (v3) driver (better for Python 3.13)
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    if not db_url:
        db_url = "sqlite:///data.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    return app

app = create_app()
db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

class Shop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    city = db.Column(db.String(80), nullable=False, default="Χανιά")
    area = db.Column(db.String(80), nullable=False, default="")
    category = db.Column(db.String(80), nullable=False, default="Hair")
    address = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    description = db.Column(db.String(800), nullable=True)
    is_open = db.Column(db.Boolean, nullable=False, default=True)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(80), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    duration_min = db.Column(db.Integer, nullable=False, default=30)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

class StaffHours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)  # 0 Mon .. 6 Sun
    start_hm = db.Column(db.String(5), nullable=False, default="10:00")
    end_hm = db.Column(db.String(5), nullable=False, default="18:00")

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("service.id"), nullable=False)

    appt_date = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD
    start_hm = db.Column(db.String(5), nullable=False)
    end_hm = db.Column(db.String(5), nullable=False)

    customer_name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(60), nullable=False)
    customer_email = db.Column(db.String(200), nullable=False)  # ✅ ΝΕΟ
    notes = db.Column(db.String(300), nullable=True)
    payment_method = db.Column(db.String(40), nullable=False, default="store")
    status = db.Column(db.String(30), nullable=False, default="Νέο")


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    customer_name = db.Column(db.String(120), nullable=False)
    rating = db.Column(db.Integer, nullable=False, default=5)
    comment = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class BusinessLead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    plan = db.Column(db.String(20), nullable=False)      # freemium/solo/duo/team
    billing = db.Column(db.String(10), nullable=False)   # monthly/annual

    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(60), nullable=False)


def ensure_schema():
    """Adds missing columns on existing DBs (simple MVP migration)."""
    try:
        # Postgres supports IF NOT EXISTS
        db.session.execute(text("ALTER TABLE appointment ADD COLUMN IF NOT EXISTS customer_email VARCHAR(180);"))
        db.session.commit()
    except Exception:
        # If it's sqlite or already exists etc., just ignore
        db.session.rollback()


def cents_to_eur(cents: int) -> str:
    return f"{cents/100:.2f}"

def hm_to_minutes(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)

def minutes_to_hm(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def weekday_of(iso_date: str) -> int:
    y, mo, d = map(int, iso_date.split("-"))
    return date(y, mo, d).weekday()

def get_booking_state():
    return session.setdefault("booking", {})

def clear_booking():
    session.pop("booking", None)

def available_slots(staff_id: int, iso_date: str, duration_min: int, step_min: int = 15):
    wd = weekday_of(iso_date)
    hours = StaffHours.query.filter_by(staff_id=staff_id, weekday=wd).first()
    if not hours:
        return []
    start = hm_to_minutes(hours.start_hm)
    end = hm_to_minutes(hours.end_hm)
    if end <= start:
        return []

    appts = Appointment.query.filter_by(staff_id=staff_id, appt_date=iso_date).filter(Appointment.status != "Ακυρωμένο").all()
    busy = [(hm_to_minutes(a.start_hm), hm_to_minutes(a.end_hm)) for a in appts]

    slots = []
    t = start
    last_start = end - duration_min
    while t <= last_start:
        cand = (t, t + duration_min)
        if all(cand[1] <= b[0] or cand[0] >= b[1] for b in busy):
            slots.append(minutes_to_hm(t))
        t += step_min
    return slots

def seed_demo_data():
    """Create tables and insert demo data once.

    NOTE: When deployed with gunicorn, the `__main__` block does NOT run.
    So we initialize the DB during app startup to avoid "no such table".
    """
    db.create_all()

    # (προαιρετικό) αν θες κάποτε να το κλείσεις:
    if (os.environ.get("SEED_DEMO_DATA", "1") or "1").strip() not in ("1","true","TRUE","yes","YES"):
        return

    if Shop.query.count() > 0:
        return
    s1 = Shop(name="EHair Studio Chania", city="Χανιά", area="Κέντρο", category="Hair",
              address="Χανιά", phone="0000000000",
              description="Κλείσε ραντεβού online σε λίγα βήματα. Demo κατάστημα.")
    s2 = Shop(name="Barber Craft", city="Χανιά", area="Νέα Χώρα", category="Barber",
              address="Χανιά", phone="0000000000",
              description="Κουρέματα & περιποίηση γενειάδας. Demo κατάστημα.")
    db.session.add_all([s1, s2]); db.session.commit()

    st1 = Staff(shop_id=s1.id, name="Μαρία", title="Hair Stylist")
    st2 = Staff(shop_id=s1.id, name="Γιάννης", title="Hair Stylist")
    st3 = Staff(shop_id=s2.id, name="Νίκος", title="Barber")
    db.session.add_all([st1, st2, st3]); db.session.commit()

    sv = [
        Service(shop_id=s1.id, name="Γυναικείο κούρεμα", duration_min=45, price_cents=2500),
        Service(shop_id=s1.id, name="Βαφή", duration_min=90, price_cents=4500),
        Service(shop_id=s1.id, name="Χτένισμα", duration_min=30, price_cents=1500),
        Service(shop_id=s2.id, name="Ανδρικό κούρεμα", duration_min=30, price_cents=1300),
        Service(shop_id=s2.id, name="Κούρεμα + Γένια", duration_min=45, price_cents=1700),
        Service(shop_id=s2.id, name="Περιποίηση γενειάδας", duration_min=15, price_cents=600),
    ]
    db.session.add_all(sv); db.session.commit()

def send_booking_email(to_email: str, appt: Appointment, shop: Shop, staff: Staff, service: Service):
    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = (os.environ.get("SMTP_PASS") or "").strip()
    from_email = (os.environ.get("SMTP_FROM") or user).strip()
    port = int(os.environ.get("SMTP_PORT") or "587")
    use_tls = (os.environ.get("SMTP_TLS", "1").strip().lower() in ("1", "true", "yes"))

    # Αν δεν έχεις ρυθμίσει SMTP στο Render, απλά δεν στέλνει (χωρίς να σπάει το booking)
    if not host or not user or not password or not from_email:
        return

    subject = "Επιβεβαίωση κράτησης – ehairstyle"
    body = (
        f"Η κράτησή σου ολοκληρώθηκε!\n\n"
        f"Κατάστημα: {shop.name}\n"
        f"Υπηρεσία: {service.name}\n"
        f"Υπάλληλος: {staff.name}\n"
        f"Ημερομηνία: {appt.appt_date}\n"
        f"Ώρα: {appt.start_hm} - {appt.end_hm}\n"
        f"Όνομα: {appt.customer_name}\n"
        f"Τηλέφωνο: {appt.phone}\n\n"
        f"Σε ευχαριστούμε!"
    )

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port) as server:
        if use_tls:
            server.starttls()
        server.login(user, password)
        server.send_message(msg)



    def add_hours(staff):
        for wd in [1,2,3,4,5]:  # Tue-Sat
            db.session.add(StaffHours(staff_id=staff.id, weekday=wd, start_hm="10:00", end_hm="18:00"))
    add_hours(st1); add_hours(st2); add_hours(st3)
    db.session.commit()

    db.session.add_all([
        Review(shop_id=s1.id, customer_name="Αλέξης", rating=5, comment="Τέλειο αποτέλεσμα!"),
        Review(shop_id=s2.id, customer_name="Κώστας", rating=5, comment="Γρήγορο και προσεγμένο κούρεμα.")
    ])
    db.session.commit()

with app.app_context():
    ensure_schema()
    seed_demo_data()



@app.route("/", methods=["GET"])
def home():
    q = (request.args.get("q") or "").strip()
    city = (request.args.get("city") or "").strip()
    category = (request.args.get("cat") or "").strip()

    query = Shop.query
    if q:
        query = query.filter(Shop.name.ilike(f"%{q}%"))
    if city:
        query = query.filter(Shop.city == city)
    if category:
        query = query.filter(Shop.category == category)

    shops = query.order_by(Shop.is_open.desc(), Shop.name.asc()).all()
    cities = [r[0] for r in db.session.query(Shop.city).distinct().order_by(Shop.city).all()]
    cats = [r[0] for r in db.session.query(Shop.category).distinct().order_by(Shop.category).all()]
    return render_template("index.html", app_name=APP_NAME, shops=shops, cities=cities, cats=cats, q=q, city=city, category=category)

@app.route("/shops/<int:sid>", methods=["GET"])
def shop_detail(sid: int):
    shop = Shop.query.get_or_404(sid)
    services = Service.query.filter_by(shop_id=sid, is_active=True).order_by(Service.name.asc()).all()
    staff = Staff.query.filter_by(shop_id=sid, is_active=True).order_by(Staff.name.asc()).all()
    reviews = Review.query.filter_by(shop_id=sid).order_by(Review.created_at.desc()).limit(30).all()
    avg = round(sum(r.rating for r in reviews)/len(reviews), 1) if reviews else None
    return render_template("shop.html", app_name=APP_NAME, shop=shop, services=services, staff=staff, reviews=reviews, avg=avg, cents_to_eur=cents_to_eur)

@app.route("/shops/<int:sid>/review", methods=["POST"])
def add_review(sid: int):
    _ = Shop.query.get_or_404(sid)
    name = (request.form.get("name") or "").strip() or "Πελάτης"
    rating = max(1, min(5, int(request.form.get("rating") or 5)))
    comment = (request.form.get("comment") or "").strip()
    db.session.add(Review(shop_id=sid, customer_name=name, rating=rating, comment=comment))
    db.session.commit()
    return redirect(url_for("shop_detail", sid=sid))

@app.route("/book/<int:sid>/start", methods=["GET"])
def book_start(sid: int):
    _ = Shop.query.get_or_404(sid)
    clear_booking()
    session["booking"] = {"shop_id": sid}
    return redirect(url_for("book_step1", sid=sid))

@app.route("/book/<int:sid>/step1", methods=["GET", "POST"])
def book_step1(sid: int):
    shop = Shop.query.get_or_404(sid)
    st = get_booking_state()
    st["shop_id"] = sid

    if request.method == "POST":
        iso_date = request.form.get("appt_date") or ""
        try:
            y, m, d = map(int, iso_date.split("-"))
            _ = date(y, m, d)
        except:
            flash("Διάλεξε έγκυρη ημερομηνία.", "danger")
            return redirect(url_for("book_step1", sid=sid))
        st["appt_date"] = iso_date
        session.modified = True
        return redirect(url_for("book_step2", sid=sid))

    today = date.today().isoformat()
    return render_template("book_step1.html", app_name=APP_NAME, shop=shop, today=today, st=st)

@app.route("/book/<int:sid>/step2", methods=["GET", "POST"])
def book_step2(sid: int):
    shop = Shop.query.get_or_404(sid)
    st = get_booking_state()
    if not st.get("appt_date"):
        return redirect(url_for("book_step1", sid=sid))
    services = Service.query.filter_by(shop_id=sid, is_active=True).order_by(Service.name.asc()).all()

    if request.method == "POST":
        service_id = int(request.form.get("service_id") or 0)
        service = Service.query.filter_by(id=service_id, shop_id=sid).first()
        if not service:
            flash("Διάλεξε υπηρεσία.", "danger")
            return redirect(url_for("book_step2", sid=sid))
        st["service_id"] = service.id
        session.modified = True
        return redirect(url_for("book_step3", sid=sid))

    return render_template("book_step2.html", app_name=APP_NAME, shop=shop, services=services, st=st, cents_to_eur=cents_to_eur)

@app.route("/book/<int:sid>/step3", methods=["GET", "POST"])
def book_step3(sid: int):
    shop = Shop.query.get_or_404(sid)
    st = get_booking_state()
    if not st.get("service_id"):
        return redirect(url_for("book_step2", sid=sid))
    staff = Staff.query.filter_by(shop_id=sid, is_active=True).order_by(Staff.name.asc()).all()

    if request.method == "POST":
        staff_id = int(request.form.get("staff_id") or 0)
        s = Staff.query.filter_by(id=staff_id, shop_id=sid).first()
        if not s:
            flash("Διάλεξε υπάλληλο.", "danger")
            return redirect(url_for("book_step3", sid=sid))
        st["staff_id"] = s.id
        session.modified = True
        return redirect(url_for("book_step4", sid=sid))

    return render_template("book_step3.html", app_name=APP_NAME, shop=shop, staff=staff, st=st)


@app.route("/business")
def business():
    return render_template("business.html", app_name=APP_NAME)

@app.route("/business", methods=["GET", "POST"])
def business():
    if request.method == "POST":
        plan = (request.form.get("plan") or "").strip()
        billing = (request.form.get("billing") or "monthly").strip()
        email = (request.form.get("email") or "").strip().lower()
        phone = (request.form.get("phone") or "").strip()

        if plan not in ("freemium", "solo", "duo", "team"):
            flash("Μη έγκυρο πακέτο.", "danger")
            return redirect(url_for("business"))

        if billing not in ("monthly", "annual"):
            billing = "monthly"

        if not email or not phone:
            flash("Συμπλήρωσε email και τηλέφωνο.", "danger")
            return redirect(url_for("business"))

        if "@" not in email or "." not in email:
            flash("Βάλε έγκυρο email.", "danger")
            return redirect(url_for("business"))

        db.session.add(BusinessLead(plan=plan, billing=billing, email=email, phone=phone))
        db.session.commit()

        flash("✅ Λάβαμε το αίτημά σου! Θα επικοινωνήσουμε σύντομα.", "success")
        return redirect(url_for("business"))

    return render_template("business.html", app_name=APP_NAME)



@app.route("/book/<int:sid>/step4", methods=["GET", "POST"])
def book_step4(sid: int):
    shop = Shop.query.get_or_404(sid)
    st = get_booking_state()
    if not st.get("staff_id"):
        return redirect(url_for("book_step3", sid=sid))

    service = Service.query.get(st["service_id"])
    staff = Staff.query.get(st["staff_id"])
    slots = available_slots(staff.id, st["appt_date"], service.duration_min)

    if request.method == "POST":
        hm = (request.form.get("start_hm") or "").strip()
        if hm not in slots:
            flash("Διάλεξε διαθέσιμη ώρα.", "danger")
            return redirect(url_for("book_step4", sid=sid))
        st["start_hm"] = hm
        st["end_hm"] = minutes_to_hm(hm_to_minutes(hm) + service.duration_min)
        session.modified = True
        return redirect(url_for("book_confirm", sid=sid))

    return render_template("book_step4.html", app_name=APP_NAME, shop=shop, staff=staff, service=service, slots=slots, st=st, cents_to_eur=cents_to_eur)

@app.route("/book/<int:sid>/confirm", methods=["GET", "POST"])
def book_confirm(sid: int):
    shop = Shop.query.get_or_404(sid)
    st = get_booking_state()
    if not st.get("start_hm"):
        return redirect(url_for("book_step4", sid=sid))

    service = Service.query.get(st["service_id"])
    staff = Staff.query.get(st["staff_id"])

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        notes = (request.form.get("notes") or "").strip()
        payment = (request.form.get("payment") or "store").strip()
        accept = request.form.get("accept")

        if not name or not phone or not email:
            flash("Συμπλήρωσε όνομα, τηλέφωνο και email.", "danger")
            return redirect(url_for("book_confirm", sid=sid))
    
        if "@" not in email or "." not in email:
            flash("Βάλε έγκυρο email.", "danger")
            return redirect(url_for("book_confirm", sid=sid))
    
        if payment not in ("store", "online"):
            payment = "store"
    
        if accept != "on":
            flash("Πρέπει να αποδεχτείς τους όρους.", "danger")
            return redirect(url_for("book_confirm", sid=sid))

        # re-check
        slots = available_slots(staff.id, st["appt_date"], service.duration_min)
        if st["start_hm"] not in slots:
            flash("Η ώρα μόλις έγινε μη διαθέσιμη. Διάλεξε άλλη.", "warning")
            return redirect(url_for("book_step4", sid=sid))

        appt = Appointment(
            shop_id=sid,
            staff_id=staff.id,
            service_id=service.id,
            appt_date=st["appt_date"],
            start_hm=st["start_hm"],
            end_hm=st["end_hm"],
            customer_name=name,
            phone=phone,
            notes=notes,
            payment_method=payment,
            status="Νέο",
            customer_email=email,

        )
        db.session.add(appt); db.session.commit()
        try:
            send_booking_email(email, appt, shop, staff, service)
        except Exception:
            pass

        clear_booking()
        return redirect(url_for("booking_done", aid=appt.id))

    return render_template("book_confirm.html", app_name=APP_NAME, shop=shop, staff=staff, service=service, st=st, cents_to_eur=cents_to_eur)

@app.route("/booking/<int:aid>", methods=["GET"])
def booking_done(aid: int):
    appt = Appointment.query.get_or_404(aid)
    shop = Shop.query.get(appt.shop_id)
    staff = Staff.query.get(appt.staff_id)
    service = Service.query.get(appt.service_id)
    return render_template("booking_done.html", app_name=APP_NAME, appt=appt, shop=shop, staff=staff, service=service, cents_to_eur=cents_to_eur)

def admin_required():
    return session.get("is_admin") is True

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("password") or "") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Λάθος κωδικός.", "danger")
    return render_template("admin_login.html", app_name=APP_NAME)

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("home"))

@app.route("/admin", methods=["GET"])
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("admin_login"))
    shops = Shop.query.order_by(Shop.name.asc()).all()
    appts = Appointment.query.order_by(Appointment.appt_date.desc(), Appointment.start_hm.desc()).limit(100).all()
    return render_template("admin.html", app_name=APP_NAME, shops=shops, appts=appts)

@app.route("/admin/shops/new", methods=["POST"])
def admin_shop_new():
    if not admin_required():
        return redirect(url_for("admin_login"))
    name = (request.form.get("name") or "").strip()
    city = (request.form.get("city") or "").strip() or "Χανιά"
    area = (request.form.get("area") or "").strip()
    category = (request.form.get("category") or "").strip() or "Hair"
    address = (request.form.get("address") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    description = (request.form.get("description") or "").strip()
    if not name:
        flash("Όνομα απαιτείται.", "danger"); return redirect(url_for("admin_dashboard"))
    s = Shop(name=name, city=city, area=area, category=category, address=address, phone=phone, description=description, is_open=True)
    db.session.add(s); db.session.commit()
    flash("✅ Προστέθηκε κατάστημα.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/staff/new", methods=["POST"])
def admin_staff_new():
    if not admin_required():
        return redirect(url_for("admin_login"))
    shop_id = int(request.form.get("shop_id") or 0)
    name = (request.form.get("name") or "").strip()
    title = (request.form.get("title") or "").strip()
    if not name or shop_id == 0:
        flash("Δώσε κατάστημα και όνομα υπαλλήλου.", "danger"); return redirect(url_for("admin_dashboard"))
    st = Staff(shop_id=shop_id, name=name, title=title, is_active=True)
    db.session.add(st); db.session.commit()
    for wd in [1,2,3,4,5]:
        db.session.add(StaffHours(staff_id=st.id, weekday=wd, start_hm="10:00", end_hm="18:00"))
    db.session.commit()
    flash("✅ Προστέθηκε υπάλληλος.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/service/new", methods=["POST"])
def admin_service_new():
    if not admin_required():
        return redirect(url_for("admin_login"))
    shop_id = int(request.form.get("shop_id") or 0)
    name = (request.form.get("name") or "").strip()
    duration = int(request.form.get("duration") or 30)
    price = (request.form.get("price") or "0").replace(",", ".")
    try:
        price_cents = int(round(float(price) * 100))
    except:
        price_cents = 0
    if not name or shop_id == 0:
        flash("Δώσε κατάστημα και όνομα υπηρεσίας.", "danger"); return redirect(url_for("admin_dashboard"))
    sv = Service(shop_id=shop_id, name=name, duration_min=max(5, duration), price_cents=max(0, price_cents), is_active=True)
    db.session.add(sv); db.session.commit()
    flash("✅ Προστέθηκε υπηρεσία.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/hours/<int:staff_id>", methods=["GET", "POST"])
def admin_hours(staff_id: int):
    if not admin_required():
        return redirect(url_for("admin_login"))
    staff = Staff.query.get_or_404(staff_id)
    shop = Shop.query.get(staff.shop_id)
    hours = StaffHours.query.filter_by(staff_id=staff_id).order_by(StaffHours.weekday.asc()).all()

    if request.method == "POST":
        StaffHours.query.filter_by(staff_id=staff_id).delete()
        for wd in range(7):
            start = (request.form.get(f"start_{wd}") or "").strip()
            end = (request.form.get(f"end_{wd}") or "").strip()
            if start and end:
                db.session.add(StaffHours(staff_id=staff_id, weekday=wd, start_hm=start, end_hm=end))
        db.session.commit()
        flash("✅ Αποθηκεύτηκε ωράριο.", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_hours.html", app_name=APP_NAME, staff=staff, shop=shop, hours=hours)

@app.route("/admin/appt/<int:aid>/cancel", methods=["POST"])
def admin_cancel_appt(aid: int):
    if not admin_required():
        return redirect(url_for("admin_login"))
    appt = Appointment.query.get_or_404(aid)
    appt.status = "Ακυρωμένο"
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

@app.route("/healthz")
def healthz():
    return {"ok": True}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)


