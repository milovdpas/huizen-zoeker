import logging
from flask import Flask

from .config import settings
from .db import init_db
from .routes import bp as web_bp


def create_app() -> Flask:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.flask_secret_key

    init_db(settings.database_url)
    app.register_blueprint(web_bp)
    return app
