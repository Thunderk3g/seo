from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SEORunViewSet, start_grade

app_name = "seo_ai"

_router = DefaultRouter()
_router.register(r"grade", SEORunViewSet, basename="grade")

urlpatterns = [
    path("grade/start/", start_grade, name="start-grade"),
    path("", include(_router.urls)),
]
