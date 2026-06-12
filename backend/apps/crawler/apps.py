import os
import sys
import threading

from django.apps import AppConfig


class CrawlerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.crawler"
    verbose_name = "Crawler Engine"

    def ready(self) -> None:
        """Warm the lean crawl-results projection on web-server startup.

        Report endpoints read a few-MB lean sidecar derived from the
        ~900 MB crawl_results.csv. That sidecar lives in /tmp (chosen so
        Django's autoreloader doesn't watch it), so a container restart /
        OOM wipes it — and the FIRST Reports request then rebuilds it
        SYNCHRONOUSLY from the 900 MB master, which exceeds the browser
        timeout and shows up as "reports not loading". Kicking the rebuild
        off in a background thread at boot means the projection is ready
        (or nearly so) by the time anyone opens Reports.

        Guarded so it only runs in the serving process — never during
        migrate / celery workers / beat / shell / tests, and only in the
        runserver worker (not the autoreload watcher).
        """
        argv = sys.argv
        blocked = {
            "migrate", "makemigrations", "collectstatic", "shell",
            "shell_plus", "test", "celery", "createsuperuser",
            "gen_cluster_specs", "psi_sweep", "dbshell",
        }
        if any(b in argv for b in blocked):
            return
        # Under runserver's reloader, ready() fires in both the watcher and
        # the worker; only the worker has RUN_MAIN=true. (gunicorn/prod
        # doesn't set RUN_MAIN and isn't 'runserver', so it warms once.)
        if "runserver" in argv and os.environ.get("RUN_MAIN") != "true":
            return

        def _warm() -> None:
            try:
                from .storage import repository as repo
                repo._ensure_lean()
            except Exception:  # noqa: BLE001 — best-effort cache warm
                pass

        threading.Thread(target=_warm, name="lean-warm", daemon=True).start()
