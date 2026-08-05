from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

# Initialize extensions without app
login_manager = LoginManager()
csrf = CSRFProtect()
