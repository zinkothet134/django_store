from io import BytesIO

import qrcode
from django.conf import settings
from django.core.files import File
from django.db import models
from django.db.models import Sum, Q, F, ExpressionWrapper, IntegerField
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.functional import cached_property

from category.models import Category


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True, blank=True)
    product_name = models.CharField(max_length=200, unique=True)
    name_my = models.CharField(max_length=200, blank=True, null=True)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(max_length=500, blank=True)
    price = models.IntegerField()
    wholesale_price = models.IntegerField(default=0)
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

    def get_warehouse_scan_url(self):
        return reverse('warehouse_scan', args=[self.sku])

    def generate_sku(self):
        prefix = (
            getattr(self.category, 'sku_prefix', None)
            or self.category.category_name[:2]
        ).upper()
        return f"{prefix}-{str(self.id).zfill(5)}"

    def generate_qr(self):
        qr_data = f"CHUE|{self.sku}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')

        buffer = BytesIO()
        img.save(buffer, format='PNG')

        self.qr_code.save(f"{self.sku}.png", File(buffer), save=False)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and not self.sku:
            self.sku = self.generate_sku()
            super().save(update_fields=['sku'])

        if self.sku and not self.qr_code:
            self.generate_qr()
            super().save(update_fields=['qr_code'])

    @property
    def total_value(self):
        return self.price * self.stock

    @cached_property
    def retail_in(self):
        return self.stockmovement_set.filter(movement_type=StockMovement.IN).aggregate(
            total=Sum('quantity')
        )['total'] or 0

    @cached_property
    def retail_out(self):
        return self.stockmovement_set.filter(movement_type=StockMovement.OUT).aggregate(
            total=Sum('quantity')
        )['total'] or 0

    @cached_property
    def retail_net(self):
        return self.retail_in - self.retail_out

    @cached_property
    def wholesale_in(self):
        return self.wholesalemovement_set.filter(movement_type=WholesaleMovement.IN).aggregate(
            total=Sum('quantity')
        )['total'] or 0

    @cached_property
    def wholesale_out(self):
        return self.wholesalemovement_set.filter(movement_type=WholesaleMovement.OUT).aggregate(
            total=Sum('quantity')
        )['total'] or 0

    @cached_property
    def wholesale_net(self):
        return self.wholesale_in - self.wholesale_out
    
    @cached_property
    def partition_in(self):
        return self.retailpartitionmovement_set.filter(
            action_type=RetailPartitionMovement.TRANSFER
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @cached_property
    def partition_sold(self):
        return self.retailpartitionmovement_set.filter(
            action_type=RetailPartitionMovement.SALE
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @cached_property
    def partition_returned(self):
        return self.retailpartitionmovement_set.filter(
            action_type=RetailPartitionMovement.RETURN
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @cached_property
    def partition_balance(self):
        return self.partition_in - self.partition_sold - self.partition_returned

    @cached_property
    def partition_retail_sale_qty(self):
        return self.retailpartitionmovement_set.filter(
            action_type=RetailPartitionMovement.SALE
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @cached_property
    def partition_retail_sale_amount(self):
        return self.retailpartitionmovement_set.filter(
            action_type=RetailPartitionMovement.SALE
        ).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('quantity') * F('unit_price'),
                    output_field=IntegerField(),
                )
            )
        )['total'] or 0

    @cached_property
    def direct_retail_sale_qty(self):
        return self.stockmovement_set.filter(
            movement_type=StockMovement.OUT,
            ref_type__in=['CUS_INV', 'CUS_REQ'],
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @cached_property
    def direct_retail_sale_amount(self):
        return self.stockmovement_set.filter(
            movement_type=StockMovement.OUT,
            ref_type__in=['CUS_INV', 'CUS_REQ'],
        ).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('quantity') * F('unit_price'),
                    output_field=IntegerField(),
                )
            )
        )['total'] or 0

    @cached_property
    def total_retail_sale_qty(self):
        return self.partition_retail_sale_qty + self.direct_retail_sale_qty

    @cached_property
    def total_retail_sale_amount(self):
        return self.partition_retail_sale_amount + self.direct_retail_sale_amount

    def __str__(self):
        return self.product_name


class VariationManager(models.Manager):
    def colors(self):
        return super().filter(variation_category='color', is_active=True)

    def sizes(self):
        return super().filter(variation_category='size', is_active=True)


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
    unit_price = models.IntegerField(default=0)
    quantity = models.PositiveIntegerField()
    ref_type = models.CharField(max_length=20, choices=REF_TYPES, blank=True)
    ref_no = models.CharField(max_length=50, blank=True)
    remark = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now, blank=True)

    def __str__(self):
        return f"{self.product} {self.movement_type} {self.quantity}"


class WholesaleMovement(models.Model):
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
    requisition = models.ForeignKey(SupplierRequisition, on_delete=models.CASCADE, related_name='items')
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
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_cost = models.IntegerField(default=0)

class RetailPartition(models.Model):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'
    CANCELLED = 'CANCELLED'

    STATUS_CHOICES = (
        (OPEN, 'Open'),
        (CLOSED, 'Closed'),
        (CANCELLED, 'Cancelled'),
    )

    code = models.CharField(max_length=30, unique=True, blank=True)
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='retail_partitions'
    )
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=OPEN)
    remark = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_retail_partitions'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f"RP-{str(self.pk).zfill(5)}"
            super().save(update_fields=['code'])

    @property
    def total_transferred(self):
        return self.movements.filter(
            action_type=RetailPartitionMovement.TRANSFER
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def total_sold(self):
        return self.movements.filter(
            action_type=RetailPartitionMovement.SALE
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def total_returned(self):
        return self.movements.filter(
            action_type=RetailPartitionMovement.RETURN
        ).aggregate(total=Sum('quantity'))['total'] or 0

    @property
    def current_balance(self):
        return self.total_transferred - self.total_sold - self.total_returned

    def __str__(self):
        return self.code or f"Retail Partition {self.pk}"


class RetailPartitionMovement(models.Model):
    TRANSFER = 'TRANSFER'
    SALE = 'SALE'
    RETURN = 'RETURN'

    ACTION_TYPES = (
        (TRANSFER, 'Transfer to Retail Partition'),
        (SALE, 'Retail Sale'),
        (RETURN, 'Return to Warehouse'),
    )

    partition = models.ForeignKey(
        RetailPartition,
        on_delete=models.CASCADE,
        related_name='movements'
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    quantity = models.PositiveIntegerField()
    unit_price = models.IntegerField(default=0)
    ref_no = models.CharField(max_length=50, blank=True)
    remark = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    created_at = models.DateTimeField(default=timezone.now, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.partition} {self.product} {self.action_type} {self.quantity}"