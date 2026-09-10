from django.urls import path

from . import views

urlpatterns = [
    path("<uuid:trip_id>/book/", views.book, name="book_trip"),
    path("<uuid:trip_id>/book_itinerary/", views.book_itinerary_view, name="book_itinerary"),
    path("status/<uuid:booking_id>/", views.booking_status, name="booking_status"),
]
