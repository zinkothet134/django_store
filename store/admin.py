from django.contrib import admin
from .models import Product, Variation, StockMovement, WholesaleMovement, RetailPartitionMovement, RetailPartition
# Register your models here.

class ProductAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'price','stock','category','modified_date','is_available')
    exclude = ('sku',)
    prepopulated_fields = {'slug':('product_name',)}
    readonly_fields = ('qr_code',)
    

class VariationAdmin(admin.ModelAdmin):
    list_display =('product','variation_category','variation_value','is_active')
    list_editable = ('is_active',)
    list_filter = ('product','variation_category','variation_value')
    


admin.site.register(Product, ProductAdmin)
admin.site.register(Variation, VariationAdmin)
admin.site.register(StockMovement)
admin.site.register(WholesaleMovement)
admin.site.register(RetailPartition)
admin.site.register(RetailPartitionMovement)

