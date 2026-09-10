from django.urls import path

from . import views

urlpatterns = [
    path("on_search/", views.on_search, name="ondc_on_search"),
    path("on_select/", views.on_select, name="ondc_on_select"),
    path("on_init/", views.on_init, name="ondc_on_init"),
    path("on_confirm/", views.on_confirm, name="ondc_on_confirm"),
    path("on_status/", views.on_status, name="ondc_on_status"),
]
