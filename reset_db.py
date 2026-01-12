from main import app, db, init_db_and_admin

if __name__ == "__main__":
    with app.app_context():
        print("⚠️  Dropping all existing tables...")
        db.drop_all()
        
        print("✅ Creating new database schema...")
        db.create_all()
        
        print("👑 Re-initializing Admin User...")
        init_db_and_admin()
        
        print("🎉 Success! Database has been reset. You may now restart the main app.")
