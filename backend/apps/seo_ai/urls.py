from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SEORunViewSet,
    chat_stream,
    competitor_dashboard,
    gsc_dashboard,
    overview,
    semrush_dashboard,
    sitemap_dashboard,
    sitemap_page_detail,
    start_grade,
)

app_name = "seo_ai"

_router = DefaultRouter()
_router.register(r"grade", SEORunViewSet, basename="grade")

urlpatterns = [
    path("overview/", overview, name="overview"),
    path("grade/start/", start_grade, name="start-grade"),
    path("gsc/", gsc_dashboard, name="gsc-dashboard"),
    path("semrush/", semrush_dashboard, name="semrush-dashboard"),
    path("sitemap/", sitemap_dashboard, name="sitemap-dashboard"),
    path("sitemap/page/", sitemap_page_detail, name="sitemap-page-detail"),
    path("competitor/", competitor_dashboard, name="competitor-dashboard"),
    path("chat/stream/", chat_stream, name="chat-stream"),
    path("", include(_router.urls)),
]
