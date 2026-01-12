from main import app, db, User
from werkzeug.security import generate_password_hash
import config

with app.app_context():
    u = config.ADMIN_USERNAME
    p = config.ADMIN_PASSWORD

    user = User.query.filter_by(username=u).first()
    if user:
        print(f"🔄 Updating password for '{u}'...")
        user.password = generate_password_hash(p)
        db.session.commit()
        print(f"✅ Password reset to: {p}")
    else:
        print(f"⚠️ User '{u}' not found. Creating now...")
        admin = User(username=u, password=generate_password_hash(p), role='ADMIN')
        db.session.add(admin)
        db.session.commit()
        print(f"✅ Admin created with password: {p}")
