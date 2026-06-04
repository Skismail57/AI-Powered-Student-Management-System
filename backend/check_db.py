
from db import get_db_connection

print("Checking database...")
conn = get_db_connection()
cursor = conn.cursor()

cursor.execute("SELECT * FROM users")
users = cursor.fetchall()

print("\nUsers in database:")
for user in users:
    print(f"- ID: {user['id']}, Name: {user['name']}, Role: {user['role']}, Mobile: {user['mobile']}")

if len(users) == 0:
    print("\n⚠️ No users found! Let's create admin user...")
    from werkzeug.security import generate_password_hash
    name = 'Admin User'
    role = 'admin'
    mobile = '1234567890'
    password = 'admin123'
    hashed_password = generate_password_hash(password)
    
    cursor.execute("""
        INSERT INTO users (name, role, mobile, password)
        VALUES (?, ?, ?, ?)
    """, (name, role, mobile, hashed_password))
    conn.commit()
    print("✅ Admin user created!")

cursor.close()
conn.close()
print("\n✅ Check complete!")
