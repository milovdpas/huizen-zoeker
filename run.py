"""Entry point — loads env, builds Flask app, starts scheduler, serves UI."""
from dotenv import load_dotenv
load_dotenv()

from huizenzoeker import create_app
from huizenzoeker.config import settings
from huizenzoeker.scheduler import init_scheduler


app = create_app()
init_scheduler(app)


if __name__ == "__main__":
    # use_reloader=False so APScheduler isn't started twice
    app.run(
        host=settings.flask_host,
        port=settings.flask_port,
        debug=False,
        use_reloader=False,
    )
