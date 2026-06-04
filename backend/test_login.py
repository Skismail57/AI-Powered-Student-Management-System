
from werkzeug.security import check_password_hash
from db import get_db_connection

print("Testing login...")
conn = get_db_connection()
cursor = conn.cursor()

mobile = '1234567890'
password = 'admin123'

cursor.execute("SELECT * FROM users WHERE mobile = ?", (mobile,))
user = cursor.fetchone()

if user:
    print("\nUser found!")
    print(f"- Name: {user['name']}")
    print(f"- Role: {user['role']}")
    print(f"- Mobile: {user['mobile']}")
    
    print(f"\nChecking password...")
    print(f"Stored password hash: {user['password']}")
    print(f"Input password: {password}")
    
    if check_password_hash(user['password'], password):
        print("\n✅ Password matches! Login successful!")
    else:
        print("\n❌ Password does NOT match! Let's fix that!")
        from werkzeug.security import generate_password_hash
        new_hash = generate_password_hash(password)
        cursor.execute("UPDATE users SET password = ? WHERE id = ?", (new_hash, user['id']))
        conn.commit()
        print("✅ Password reset to 'admin123'!")

else:
    print("\n❌ No user found!")

cursor.close()
conn.close()
print("\n✅ Test complete!")
