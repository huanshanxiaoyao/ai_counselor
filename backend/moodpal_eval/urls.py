from django.urls import path

from . import views

app_name = 'moodpal_eval'

urlpatterns = [
    path('', views.index, name='index'),
    path('runs/', views.run_list, name='run_list'),
    path('runs/new/', views.run_create, name='run_create'),
    path('runs/<uuid:run_id>/', views.run_detail, name='run_detail'),
    path('items/<uuid:item_id>/', views.item_detail, name='item_detail'),
]
