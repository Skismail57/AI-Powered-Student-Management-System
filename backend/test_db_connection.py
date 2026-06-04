
import mysql.connector
from config import Config

print("Testing MySQL connection...")
print(f"Host: {Config.DB_HOST}")
print(f"User: {Config.DB_USER}")
print(f"Database: {Config.DB_NAME}")

try:
    conn = mysql.connector.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD
    )
    print("\n✅ Successfully connected to MySQL server!")
    
    cursor = conn.cursor()
    
    # Create database if not exists
    cursor.execute("CREATE DATABASE IF NOT EXISTS student_system")
    print("✅ Database 'student_system' created/verified")
    
    cursor.execute("USE student_system")
    print("✅ Using database 'student_system'")
    
    cursor.close()
    conn.close()
    print("\n✅ All tests passed!")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
