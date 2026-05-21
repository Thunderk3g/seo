"""Django manage.py file."""

import os
import sys

# Inject the OS trust store into urllib3 / requests BEFORE anything else
# imports SSL. Corporate MITM proxies (e.g. Bajaj's Zscaler) intercept
# HTTPS with a custom root CA that isn't in certifi's bundle, so any
# urllib3 SSLContext built before this would fail CERTIFICATE_VERIFY_
# FAILED on calls to Adobe IMS / Google PSI / etc. truststore is a no-op
# on systems whose OS store already matches certifi.
try:
    import truststore  # type: ignore[import-not-found]
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass


def main():
    # Load environment variables from .env file
    try:
        from dotenv import load_dotenv
        # Find .env at project root
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(env_path)
    except ImportError:
        pass

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()
