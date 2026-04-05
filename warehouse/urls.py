from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='warehouse_dashboard'),
    path('products/', views.product_list, name='warehouse_products'),
    path('products/prints/', views.print_all_qr, name='warehouse_print_all_qr'),
    path('products/<str:sku>/', views.product_detail, name='warehouse_product_detail'),
    path('products/<str:sku>/print/', views.print_qr, name='warehouse_print_qr'),

    path('scan/<str:sku>/', views.scan, name='warehouse_scan'),
    path('movements/', views.movement_list, name='warehouse_movements'),

    path('wholesale/invoices/', views.wholesale_invoice_list, name='warehouse_wholesale_invoice_list'),
    path('wholesale/invoices/create/', views.wholesale_invoice_create, name='warehouse_wholesale_invoice_create'),
    path('wholesale/invoices/<int:invoice_id>/', views.wholesale_invoice_detail, name='warehouse_wholesale_invoice_detail'),
    path('wholesale/invoices/<int:invoice_id>/scan/', views.wholesale_invoice_scan_item, name='warehouse_wholesale_invoice_scan_item'),
    path('wholesale/invoices/<int:invoice_id>/item/<int:item_id>/update/', views.wholesale_invoice_update_item, name='warehouse_wholesale_invoice_update_item'),
    path('wholesale/invoices/<int:invoice_id>/item/<int:item_id>/delete/', views.wholesale_invoice_delete_item, name='warehouse_wholesale_invoice_delete_item'),
    path('wholesale/invoices/<int:invoice_id>/confirm/', views.wholesale_invoice_confirm, name='warehouse_wholesale_invoice_confirm'),
    path('wholesale/invoices/<int:invoice_id>/print/', views.wholesale_invoice_print, name='warehouse_wholesale_invoice_print'),

    path('retail-partitions/', views.retail_partition_list, name='warehouse_retail_partition_list'),
    path('retail-partitions/create/', views.retail_partition_create, name='warehouse_retail_partition_create'),
    path('retail-partitions/<int:partition_id>/', views.retail_partition_detail, name='warehouse_retail_partition_detail'),
]