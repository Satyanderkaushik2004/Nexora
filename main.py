"""NEXORA AI Router entry point (development server)."""

import sys

from api.server import create_app
from core.config import LOOPBACK_HOSTS, ConfigError, load_settings


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")

    if settings.debug and settings.host not in LOOPBACK_HOSTS:
        sys.exit(
            "Refusing to start: NEXORA_DEBUG=true exposes the Werkzeug debugger and "
            "must only be used with NEXORA_HOST set to 127.0.0.1."
        )

    app = create_app(settings)
    app.run(host=settings.host, port=settings.port, debug=settings.debug)


if __name__ == "__main__":
    main()
