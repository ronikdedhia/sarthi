from django.urls import path

from . import views

urlpatterns = [
    path("search/", views.search, name="trip_search"),
    path("plan/", views.plan, name="trip_plan"),
    path("plan_from_text/", views.plan_from_text, name="trip_plan_from_text"),
]
