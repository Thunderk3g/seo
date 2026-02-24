"""Central API layer URL routing."""

from django.urls import path, include
from .routers import router

urlpatterns = [
    path("", include(router.urls)),
]
