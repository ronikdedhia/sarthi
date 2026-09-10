from django.urls import path

from . import views

urlpatterns = [
    path("<uuid:trip_id>/book/", views.book, name="book_trip"),
    path("status/<uuid:booking_id>/", views.booking_status, name="booking_status"),
]
