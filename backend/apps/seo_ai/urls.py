from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SEORunViewSet, overview, start_grade

app_name = "seo_ai"

_router = DefaultRouter()
_router.register(r"grade", SEORunViewSet, basename="grade")

urlpatterns = [
    path("overview/", overview, name="overview"),
    path("grade/start/", start_grade, name="start-grade"),
    path("", include(_router.urls)),
]
