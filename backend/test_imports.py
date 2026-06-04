
from importlib.metadata import version

print("Testing imports...")

try:
    import flask
    print(f"✅ Flask {version('Flask')} imported successfully!")
except ImportError as e:
    print(f"❌ Flask import failed: {e}")

try:
    import flask_cors
    print("✅ Flask-CORS imported successfully!")
except ImportError as e:
    print(f"❌ Flask-CORS import failed: {e}")

try:
    import flask_socketio
    print("✅ Flask-SocketIO imported successfully!")
except ImportError as e:
    print(f"❌ Flask-SocketIO import failed: {e}")

try:
    import flask_mail
    print("✅ Flask-Mail imported successfully!")
except ImportError as e:
    print(f"❌ Flask-Mail import failed: {e}")

try:
    import jwt
    print("✅ PyJWT imported successfully!")
except ImportError as e:
    print(f"❌ PyJWT import failed: {e}")

try:
    import werkzeug
    print(f"✅ Werkzeug {version('Werkzeug')} imported successfully!")
except ImportError as e:
    print(f"❌ Werkzeug import failed: {e}")

try:
    import dotenv
    print("✅ python-dotenv imported successfully!")
except ImportError as e:
    print(f"❌ python-dotenv import failed: {e}")

try:
    import mysql.connector
    print("✅ mysql-connector-python imported successfully!")
except ImportError as e:
    print(f"❌ mysql-connector-python import failed: {e}")

try:
    import sklearn
    print(f"✅ scikit-learn {sklearn.__version__} imported successfully!")
except ImportError as e:
    print(f"❌ scikit-learn import failed: {e}")

try:
    import numpy as np
    print(f"✅ numpy {np.__version__} imported successfully!")
except ImportError as e:
    print(f"❌ numpy import failed: {e}")

try:
    import model
    print("✅ model.py imported successfully!")
    print("Testing prediction...")
    result = model.predict_marks(3, 7, 85)
    print(f"✅ Prediction works! Predicted marks: {result:.2f}")
except Exception as e:
    print(f"❌ model.py import/test failed: {e}")

print("\nImport test complete!")
