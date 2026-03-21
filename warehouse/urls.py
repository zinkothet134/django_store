from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='warehouse_dashboard'),
    path('products/', views.product_list, name='warehouse_products'),
    path('products/<str:sku>/', views.product_detail, name='warehouse_product_detail'),
    path('products/<str:sku>/print/', views.print_qr, name='warehouse_print_qr'),
    path('scan/<str:sku>/', views.scan, name='warehouse_scan'),
    path('movements/', views.movement_list, name='warehouse_movements'),
    path('retail-partitions/', views.retail_partition_list, name='warehouse_retail_partition_list'),
    path('retail-partitions/create/', views.retail_partition_create, name='warehouse_retail_partition_create'),
    path('retail-partitions/<int:partition_id>/', views.retail_partition_detail, name='warehouse_retail_partition_detail'),
]