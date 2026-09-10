from django.urls import path

from . import views

urlpatterns = [
    path("search/", views.search, name="mock_bpp_search"),
    path("select/", views.select, name="mock_bpp_select"),
    path("init/", views.init, name="mock_bpp_init"),
    path("confirm/", views.confirm, name="mock_bpp_confirm"),
    path("status/", views.status, name="mock_bpp_status"),
]
