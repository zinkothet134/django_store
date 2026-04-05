from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import (
    Product,
    Variation,
    StockMovement,
    WholesaleMovement,
    RetailPartitionMovement,
    RetailPartition,
    WholesaleInvoice,
    WholesaleInvoiceItem,
    Supplier,
    SupplierRequisition,
    SupplierRequisitionItem,
    SupplierInvoice,
    SupplierInvoiceItem,
)


admin.site.site_header = 'CHUE Family Back Office'
admin.site.site_title = 'CHUE Admin'
admin.site.index_title = 'Warehouse, Products, Invoices and Access Control'


class VariationInline(admin.TabularInline):
    model = Variation
    extra = 0
    fields = ('variation_category', 'variation_value', 'is_active')


class WholesaleInvoiceItemInline(admin.TabularInline):
    model = WholesaleInvoiceItem
    extra = 0
    fields = ('product', 'quantity', 'unit_price', 'line_total')
    readonly_fields = ('line_total',)


class SupplierRequisitionItemInline(admin.TabularInline):
    model = SupplierRequisitionItem
    extra = 0
    fields = ('product', 'quantity', 'unit_cost')


class SupplierInvoiceItemInline(admin.TabularInline):
    model = SupplierInvoiceItem
    extra = 0
    fields = ('product', 'quantity', 'unit_cost')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'product_name',
        'sku',
        'category',
        'price',
        'wholesale_price',
        'stock',
        'is_available',
        'modified_date',
    )
    list_filter = ('category', 'is_available', 'created_at', 'modified_date')
    search_fields = ('product_name', 'name_my', 'sku', 'category__category_name')
    exclude = ('sku',)
    prepopulated_fields = {'slug': ('product_name',)}
    readonly_fields = ('qr_code', 'created_at', 'modified_date')
    inlines = [VariationInline]
    list_per_page = 30


@admin.register(Variation)
class VariationAdmin(admin.ModelAdmin):
    list_display = ('product', 'variation_category', 'variation_value', 'is_active')
    list_editable = ('is_active',)
    list_filter = ('variation_category', 'is_active', 'product')
    search_fields = ('product__product_name', 'variation_value')
    list_per_page = 50


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'movement_type', 'quantity', 'unit_price', 'ref_type', 'ref_no', 'created_by', 'created_at')
    list_filter = ('movement_type', 'ref_type', 'created_at')
    search_fields = ('product__product_name', 'product__sku', 'ref_no', 'remark')
    autocomplete_fields = ('product', 'created_by')
    date_hierarchy = 'created_at'
    list_per_page = 50


@admin.register(WholesaleMovement)
class WholesaleMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'invoice', 'movement_type', 'quantity', 'unit_price', 'ref_type', 'ref_no', 'created_by', 'created_at')
    list_filter = ('movement_type', 'ref_type', 'created_at')
    search_fields = ('product__product_name', 'product__sku', 'ref_no', 'invoice__invoice_no', 'remark')
    autocomplete_fields = ('product', 'invoice', 'created_by')
    date_hierarchy = 'created_at'
    list_per_page = 50


@admin.register(RetailPartition)
class RetailPartitionAdmin(admin.ModelAdmin):
    list_display = ('code', 'staff', 'start_date', 'end_date', 'status', 'current_balance', 'created_by', 'created_at')
    list_filter = ('status', 'start_date', 'end_date', 'created_at')
    search_fields = ('code', 'staff__username', 'staff__first_name', 'staff__last_name', 'remark')
    autocomplete_fields = ('staff', 'created_by')
    readonly_fields = ('code', 'created_at')
    list_per_page = 30


@admin.register(RetailPartitionMovement)
class RetailPartitionMovementAdmin(admin.ModelAdmin):
    list_display = ('partition', 'product', 'action_type', 'quantity', 'unit_price', 'ref_no', 'created_by', 'created_at')
    list_filter = ('action_type', 'created_at')
    search_fields = ('partition__code', 'product__product_name', 'product__sku', 'ref_no', 'remark')
    autocomplete_fields = ('partition', 'product', 'created_by')
    date_hierarchy = 'created_at'
    list_per_page = 50


@admin.register(WholesaleInvoice)
class WholesaleInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_no',
        'customer_name',
        'invoice_date',
        'status',
        'payment_method',
        'payment_status',
        'subtotal',
        'discount_amount',
        'total_amount',
    )
    list_filter = ('status', 'payment_method', 'payment_status', 'invoice_date', 'created_at')
    search_fields = ('invoice_no', 'customer_name', 'customer_phone', 'customer_address', 'remark')
    autocomplete_fields = ('created_by',)
    readonly_fields = ('invoice_no', 'subtotal', 'total_amount', 'created_at')
    inlines = [WholesaleInvoiceItemInline]
    list_per_page = 30


@admin.register(WholesaleInvoiceItem)
class WholesaleInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'product', 'quantity', 'unit_price', 'line_total')
    list_filter = ('invoice__status',)
    search_fields = ('invoice__invoice_no', 'product__product_name', 'product__sku')
    autocomplete_fields = ('invoice', 'product')
    list_per_page = 50


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'address')
    search_fields = ('name', 'phone', 'address')
    list_per_page = 30


@admin.register(SupplierRequisition)
class SupplierRequisitionAdmin(admin.ModelAdmin):
    list_display = ('req_no', 'supplier', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('req_no', 'supplier__name')
    autocomplete_fields = ('supplier', 'created_by')
    inlines = [SupplierRequisitionItemInline]
    list_per_page = 30


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = ('inv_no', 'supplier', 'requisition', 'status', 'created_by', 'posted_at')
    list_filter = ('status', 'posted_at')
    search_fields = ('inv_no', 'supplier__name', 'requisition__req_no')
    autocomplete_fields = ('supplier', 'requisition', 'created_by')
    inlines = [SupplierInvoiceItemInline]
    list_per_page = 30


User = get_user_model()


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'first_name', 'last_name', 'email', 'is_staff', 'is_active', 'is_superuser')
    list_filter = ('is_staff', 'is_active', 'is_superuser', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    filter_horizontal = ('groups', 'user_permissions')
    list_per_page = 30


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    search_fields = ('name',)
    filter_horizontal = ('permissions',)