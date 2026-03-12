from django.db import models
from category.models import Category
from django.urls import reverse
import qrcode
from io import BytesIO
from django.core.files import File
from django.db.models import Max
from django.utils import translation
from django.utils import timezone
# Create your models here.

class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True, blank=True)
    product_name = models.CharField(max_length=200, unique=True)
    name_my = models.CharField(max_length=200, blank=True, null= True)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(max_length=500, blank=True)
    price = models.IntegerField()
    images = models.ImageField(upload_to='photos/products/', blank=True)
    stock = models.IntegerField()
    is_available = models.BooleanField(default=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(auto_now=True)

    qr_code = models.ImageField(upload_to='photos/qr/', blank=True, null=True)

    @property
    def display_name(self):
        lang = translation.get_language()
        if lang == 'my' and self.name_my:
            return self.name_my
        return self.product_name
    
    def get_url(self):
        return reverse('product_detail', args=[self.category.slug, self.slug])
    def __str__(self):
        return self.product_name
    
    def get_warehouse_scan_url(self):
        return reverse('warehouse_scan', args=[self.sku])
    
    def generate_sku(self):
        """
        Generate unique SKU based on category prefix + ID
        Example: FW-00012
        """
        prefix = (
            getattr(self.category, "sku_prefix", None)
            or self.category.category_name[:2]
        ).upper()

        return f"{prefix}-{str(self.id).zfill(5)}"

    def generate_qr(self):
        """
        Generate QR image encoding ONLY SKU
        """
        qr_data = f"CHUE|{self.sku}"

        qr = qrcode.QRCode(
            version=1,
            box_size=10,
            border=4,
        )

        qr.add_data(qr_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        self.qr_code.save(
            f"{self.sku}.png",
            File(buffer),
            save=False
        )

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # First save to get ID
        super().save(*args, **kwargs)

        # If new object and SKU not set → generate SKU
        if is_new and not self.sku:
            self.sku = self.generate_sku()
            super().save(update_fields=["sku"])

        # Generate QR if missing
        if self.sku and not self.qr_code:
            self.generate_qr()
            super().save(update_fields=["qr_code"])

    @property
    def total_value(self):
        return self.price * self.stock

    def __str__(self):
        return self.product_name
  

    def __str__(self):
        return self.product_name
    
    
# code for the variation manager

class VariationManager(models.Manager):
    def colors(self):
        return super(VariationManager, self).filter(variation_category='color', is_active=True)
    def sizes(self):
        return super(VariationManager, self).filter(variation_category='size', is_active=True)
    
variation_category_choice = (
    ('color', 'color'),
    ('size', 'size'),
)

class Variation(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variation_category = models.CharField(max_length=100, choices=variation_category_choice)
    variation_value = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now=True)

    objects = VariationManager()

    def __str__(self):
        return self.variation_value 


    
# for Warehouse

from django.conf import settings

class StockMovement(models.Model):
    IN = 'IN'
    OUT = 'OUT'

    MOVEMENT_TYPES = (
        (IN, 'Stock In'),
        (OUT, 'Stock Out'),
    )
    REF_TYPES = (
        ('SUP_INV', 'Supplier Invoice'),
        ('CUS_INV', 'Customer Invoice'),
        ('SUP_REQ', 'Supplier Requisition'),
        ('CUS_REQ', 'Customer Requisition'),
        ('RET_PART', 'Stock Partition for Retail'),
        ('RET_RETURN', 'Return from Retail'),
        ('ADJ', 'Adjustment'),
    )

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    movement_type = models.CharField(max_length=3, choices=MOVEMENT_TYPES)
    # Snapshot of unit price at the time of movement (product price may change later)
    unit_price = models.IntegerField(default=0)
    quantity = models.PositiveIntegerField()
    ref_type = models.CharField(max_length=20, choices=REF_TYPES, blank=True)
    ref_no = models.CharField(max_length=50, blank=True)
    remark = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now, blank=True)


    def __str__(self):
        return f"{self.product} {self.movement_type} {self.quantity}"
    
class Supplier(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)

class SupplierRequisition(models.Model):
    DRAFT = 'DRAFT'
    SUBMITTED = 'SUBMITTED'
    APPROVED = 'APPROVED'
    CANCELLED = 'CANCELLED'
    STATUS = (
        (DRAFT, 'Draft'),
        (SUBMITTED, 'Submitted'),
        (APPROVED, 'Approved'),
        (CANCELLED, 'Cancelled'),
    )

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    req_no = models.CharField(max_length=30, unique=True)
    status = models.CharField(max_length=15, choices=STATUS, default=DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.req_no

class SupplierRequisitionItem(models.Model):
    requisition = models.ForeignKey(SupplierRequisition, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_cost = models.IntegerField(default=0)

class SupplierInvoice(models.Model):
    DRAFT = 'DRAFT'
    POSTED = 'POSTED'
    CANCELLED = 'CANCELLED'

    STATUS = (
        (DRAFT, 'Draft'),
        (POSTED, 'Posted'),
        (CANCELLED, 'Cancelled'),
    )

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    inv_no = models.CharField(max_length=30, unique=True)
    requisition = models.ForeignKey(SupplierRequisition, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default=DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.inv_no

class SupplierInvoiceItem(models.Model):
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_cost = models.IntegerField(default=0)