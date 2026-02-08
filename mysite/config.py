# ---- Config class (put just above app = Flask(...) or in a separate config.py) ----
class BaseConfig:
    SESSION_TYPE = "filesystem"
    SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32).hex())
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = 300

    JSON_DIR = os.environ.get("JSON_DIR", "/home/lszoszk/mysite/json_data")
    JSON_SP_DIR = os.environ.get("JSON_SP_DIR", "/home/lszoszk/mysite/json_data_sp")
    MD_SP_DIR = os.environ.get("MD_SP_DIR", "/home/lszoszk/mysite/md_data_sp")

# ---- Create app and apply config ----
app = Flask(__name__)
app.config.from_object(BaseConfig)

# Flask-Session and Flask-Caching now read from app.config
Session(app)
cache = Cache(app)  # no dict needed, uses CACHE_* from app.config

# ---- Use config values instead of literals ----
JSON_DIR    = app.config["JSON_DIR"]
JSON_SP_DIR = app.config["JSON_SP_DIR"]
MD_SP_DIR   = app.config["MD_SP_DIR"]
