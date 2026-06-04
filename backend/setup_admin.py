
from werkzeug.security import generate_password_hash
from db import get_db_connection

def create_admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    name = 'Admin User'
    role = 'admin'
    mobile = '1234567890'
    password = 'admin123'
    
    hashed_password = generate_password_hash(password)
    
    try:
        cursor.execute("""
            INSERT INTO users (name, role, mobile, password)
            VALUES (?, ?, ?, ?)
        """, (name, role, mobile, hashed_password))
        
        conn.commit()
        print(f"✅ Admin user created successfully!")
        print(f"📱 Mobile: {mobile}")
        print(f"🔑 Password: {password}")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("ℹ️  Admin user might already exist!")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    create_admin()
