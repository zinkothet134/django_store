from django.shortcuts import render, get_object_or_404, redirect
from django.db import transaction
from django.db.models import Sum, Q, Case, When, IntegerField, F, ExpressionWrapper
from django.db.models.functions import TruncDate
from store.models import (
    Product,
    StockMovement,
    WholesaleMovement,
    RetailPartition,
    RetailPartitionMovement,
    WholesaleInvoice,
    WholesaleInvoiceItem,
)
from category.models import Category
from .permissions import in_group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.contrib import messages
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from datetime import timedelta
from zoneinfo import ZoneInfo
from itertools import chain
from urllib.parse import urlencode
# Create your views here.

def is_warehouse_staff(user):
    return user.is_superuser or user.is_staff or user.groups.filter(name='Warehouse Staff').exists()

@login_required
@user_passes_test(is_warehouse_staff)
def dashboard(request):
    products_qs = Product.objects.all().order_by('-created_at')
    total_products = products_qs.count()
    total_stock = products_qs.aggregate(total=Sum('stock'))['total'] or 0

    keyword = (request.GET.get('keyword') or '').strip()
    if keyword:
        products_qs = products_qs.filter(
            Q(product_name__icontains=keyword) |
            Q(sku__icontains=keyword) |
            Q(category__category_name__icontains=keyword)
        )

    stock_filter = (request.GET.get('stock') or '').strip()
    if stock_filter.lower() == 'none':
        stock_filter = ''
    if stock_filter == 'in':
        products_qs = products_qs.filter(stock__gt=0)
    elif stock_filter == 'out':
        products_qs = products_qs.filter(stock=0)

    category_id = (request.GET.get('category') or '').strip()
    if category_id.lower() == 'none':
        category_id = ''
    if category_id.isdigit():
        products_qs = products_qs.filter(category_id=int(category_id))

    start_str = (request.GET.get('start') or '').strip()
    end_str = (request.GET.get('end') or '').strip()

    today = timezone.localdate()
    start_date = parse_date(start_str) if start_str else (today - timedelta(days=14))
    end_date = parse_date(end_str) if end_str else today

    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    # -----------------------------
    # RETAIL = 2 pathways
    # 1) partition sale
    # 2) direct retail sale from warehouse
    # -----------------------------
    retail_partition_sales = RetailPartitionMovement.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        action_type=RetailPartitionMovement.SALE,
    )

    retail_direct_sales = StockMovement.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        movement_type=StockMovement.OUT,
        ref_type__in=['CUS_INV', 'CUS_REQ'],
    )

    retail_transfer_range = RetailPartitionMovement.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        action_type=RetailPartitionMovement.TRANSFER,
    )

    retail_return_range = RetailPartitionMovement.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        action_type=RetailPartitionMovement.RETURN,
    )

    wholesale_range = WholesaleMovement.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )

    # -----------------------------
    # Retail top sold products
    # combine partition sale + direct retail warehouse sale
    # -----------------------------
    retail_product_totals = {}

    for row in (
        retail_partition_sales
        .values('product__product_name')
        .annotate(qty_out=Sum('quantity'))
    ):
        name = row['product__product_name']
        retail_product_totals[name] = retail_product_totals.get(name, 0) + (row['qty_out'] or 0)

    for row in (
        retail_direct_sales
        .values('product__product_name')
        .annotate(qty_out=Sum('quantity'))
    ):
        name = row['product__product_name']
        retail_product_totals[name] = retail_product_totals.get(name, 0) + (row['qty_out'] or 0)

    retail_top_out = sorted(
        retail_product_totals.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]

    retail_bar_labels = [name for name, qty in retail_top_out]
    retail_bar_qty = [qty for name, qty in retail_top_out]

    wholesale_top_out = (
        wholesale_range
        .filter(movement_type=WholesaleMovement.OUT)
        .values('product__product_name')
        .annotate(qty_out=Sum('quantity'))
        .order_by('-qty_out')[:10]
    )
    wholesale_bar_labels = [r['product__product_name'] for r in wholesale_top_out]
    wholesale_bar_qty = [r['qty_out'] or 0 for r in wholesale_top_out]

    # -----------------------------
    # Retail daily qty + income
    # combine partition sale + direct retail warehouse sale
    # -----------------------------
    retail_daily_map = {}

    partition_daily = (
        retail_partition_sales
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            qty_out=Sum('quantity'),
            income=Sum(
                ExpressionWrapper(
                    F('quantity') * F('unit_price'),
                    output_field=IntegerField(),
                )
            ),
        )
        .order_by('day')
    )

    direct_daily = (
        retail_direct_sales
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            qty_out=Sum('quantity'),
            income=Sum(
                ExpressionWrapper(
                    F('quantity') * F('unit_price'),
                    output_field=IntegerField(),
                )
            ),
        )
        .order_by('day')
    )

    for row in partition_daily:
        day = row['day']
        retail_daily_map.setdefault(day, {'qty_out': 0, 'income': 0})
        retail_daily_map[day]['qty_out'] += row['qty_out'] or 0
        retail_daily_map[day]['income'] += row['income'] or 0

    for row in direct_daily:
        day = row['day']
        retail_daily_map.setdefault(day, {'qty_out': 0, 'income': 0})
        retail_daily_map[day]['qty_out'] += row['qty_out'] or 0
        retail_daily_map[day]['income'] += row['income'] or 0

    retail_daily_sorted = sorted(retail_daily_map.items(), key=lambda x: x[0])

    retail_line_labels = [day.strftime('%Y-%m-%d') for day, _ in retail_daily_sorted]
    retail_line_qty = [vals['qty_out'] for _, vals in retail_daily_sorted]
    retail_line_income = [vals['income'] for _, vals in retail_daily_sorted]

    wholesale_daily = (
        wholesale_range
        .filter(movement_type=WholesaleMovement.OUT)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            qty_out=Sum('quantity'),
            income=Sum(
                ExpressionWrapper(
                    F('quantity') * F('unit_price'),
                    output_field=IntegerField(),
                )
            ),
        )
        .order_by('day')
    )
    wholesale_line_labels = [d['day'].strftime('%Y-%m-%d') for d in wholesale_daily]
    wholesale_line_qty = [d['qty_out'] or 0 for d in wholesale_daily]
    wholesale_line_income = [d['income'] or 0 for d in wholesale_daily]

    # -----------------------------
    # Retail summary
    # transferred / sold / returned
    # sold includes both pathways
    # -----------------------------
    retail_partition_sale_total = retail_partition_sales.aggregate(total=Sum('quantity'))['total'] or 0
    retail_direct_sale_total = retail_direct_sales.aggregate(total=Sum('quantity'))['total'] or 0

    retail_total_in = retail_transfer_range.aggregate(total=Sum('quantity'))['total'] or 0
    retail_total_out = retail_partition_sale_total + retail_direct_sale_total
    retail_return_total = retail_return_range.aggregate(total=Sum('quantity'))['total'] or 0
    retail_net_total = retail_total_in - retail_total_out - retail_return_total

    wholesale_total_in = wholesale_range.filter(
        movement_type=WholesaleMovement.IN
    ).aggregate(total=Sum('quantity'))['total'] or 0

    wholesale_total_out = wholesale_range.filter(
        movement_type=WholesaleMovement.OUT
    ).aggregate(total=Sum('quantity'))['total'] or 0

    wholesale_net_total = wholesale_total_in - wholesale_total_out

    retail_paginator = Paginator(products_qs, 10)
    retail_page_number = request.GET.get('retail_page')
    retail_products = retail_paginator.get_page(retail_page_number)

    wholesale_paginator = Paginator(products_qs, 10)
    wholesale_page_number = request.GET.get('wholesale_page')
    wholesale_products = wholesale_paginator.get_page(wholesale_page_number)

    categories = Category.objects.all().order_by('category_name')

    context = {
        'total_products': total_products,
        'total_stock': total_stock,
        'keyword': keyword,
        'stock_filter': stock_filter,
        'selected_category': category_id,
        'categories': categories,
        'start': start_date.strftime('%Y-%m-%d') if start_date else '',
        'end': end_date.strftime('%Y-%m-%d') if end_date else '',
        'retail_products': retail_products,
        'wholesale_products': wholesale_products,

        'retail_total_in': retail_total_in,
        'retail_total_out': retail_total_out,
        'retail_return_total': retail_return_total,
        'retail_net_total': retail_net_total,

        'wholesale_total_in': wholesale_total_in,
        'wholesale_total_out': wholesale_total_out,
        'wholesale_net_total': wholesale_net_total,

        'retail_bar_labels': retail_bar_labels,
        'retail_bar_qty': retail_bar_qty,
        'retail_line_labels': retail_line_labels,
        'retail_line_qty': retail_line_qty,
        'retail_line_income': retail_line_income,

        'wholesale_bar_labels': wholesale_bar_labels,
        'wholesale_bar_qty': wholesale_bar_qty,
        'wholesale_line_labels': wholesale_line_labels,
        'wholesale_line_qty': wholesale_line_qty,
        'wholesale_line_income': wholesale_line_income,
    }
    return render(request, 'warehouse/dashboard.html', context)

@login_required
@user_passes_test(is_warehouse_staff)
# @in_group('Warehouse Staff')
def product_list(request):
    products = Product.objects.all().order_by('-created_at')
    
    keyword = request.GET.get('keyword','')
    if keyword:
        products = products.filter(
            Q(product_name__icontains = keyword)|
            Q(sku__icontains = keyword) |
            Q(category__category_name__icontains=keyword)
        )
    stock_filter = (request.GET.get('stock') or '').strip()
    # Sometimes links may include stock=None; treat it as empty
    if stock_filter.lower() == 'none':
        stock_filter = ''
    if stock_filter == 'in':
        products = products.filter(stock__gt=0)
    elif stock_filter == 'out':
        products = products.filter(stock=0)

    # category filter
    category_id = (request.GET.get('category') or '').strip()
    # Sometimes links may include category=None; treat it as empty
    if category_id.lower() == 'none':
        category_id = ''

    # Only filter if it's a valid integer id
    if category_id.isdigit():
        products = products.filter(category_id=int(category_id))
    
    # Pagination 
    paginator = Paginator(products, 10) #10 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    categories = Category.objects.all()
    
    context = {
        'products': page_obj,
        'categories': categories, 
        'keyword': keyword,
        'stock_filter': stock_filter,
        'selected_category': category_id,
        'retail_label': 'Retail',
        'wholesale_label': 'Wholesale',
    }
    return render(request, 'warehouse/product_list.html', context)

@login_required
@user_passes_test(is_warehouse_staff)
# @in_group('Warehouse Staff')
def product_detail(request, sku):
    product = get_object_or_404(Product, sku=sku)
    # Daily stock movement summary last 30 days
    daily_movements = (
        StockMovement.objects
        .filter(product=product)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            qty_in=Sum(
                Case(
                    When(
                        movement_type=StockMovement.IN, then='quantity'),
                        default=0,
                        output_field=IntegerField(),
                )
            ),
            qty_out = Sum(
                Case(When(
                    movement_type=StockMovement.OUT, then='quantity'),
                    default=0,
                    output_field=IntegerField(),
                )
            )
        ).order_by('-day')
    )
    # optional limit rows displayed
    daily_movements = daily_movements[:30]
    daily_movements = list(daily_movements[:30])
    #Calulate net (net-out)
    for row in daily_movements:
        qty_in = row.get('qty_in') or 0
        qty_out = row.get('qty_out') or 0
        row['net'] = qty_in - qty_out
    context = {
        'product': product,
        'daily_movements': daily_movements,
    }
    return render(request, 'warehouse/product_detail.html', context)

def _get_partition_product_balance(partition, product):
    transferred = partition.movements.filter(
        product=product,
        action_type=RetailPartitionMovement.TRANSFER
    ).aggregate(total=Sum('quantity'))['total'] or 0

    sold = partition.movements.filter(
        product=product,
        action_type=RetailPartitionMovement.SALE
    ).aggregate(total=Sum('quantity'))['total'] or 0

    returned = partition.movements.filter(
        product=product,
        action_type=RetailPartitionMovement.RETURN
    ).aggregate(total=Sum('quantity'))['total'] or 0

    return transferred - sold - returned

@login_required
@user_passes_test(is_warehouse_staff)
def retail_partition_list(request):
    partitions = RetailPartition.objects.select_related('staff', 'created_by').order_by('-created_at')

    status = (request.GET.get('status') or '').strip().upper()
    if status in {RetailPartition.OPEN, RetailPartition.CLOSED, RetailPartition.CANCELLED}:
        partitions = partitions.filter(status=status)

    context = {
        'partitions': partitions,
        'selected_status': status,
    }
    return render(request, 'warehouse/retail_partition_list.html', context)

@login_required
@user_passes_test(is_warehouse_staff)
def retail_partition_create(request):
    error = None

    if request.method == 'POST':
        start_date_raw = (request.POST.get('start_date') or '').strip()
        end_date_raw = (request.POST.get('end_date') or '').strip()
        staff_id = (request.POST.get('staff_id') or '').strip()
        remark = (request.POST.get('remark') or '').strip()

        start_date = parse_date(start_date_raw) if start_date_raw else timezone.localdate()
        end_date = parse_date(end_date_raw) if end_date_raw else None

        if staff_id and not staff_id.isdigit():
            error = 'Invalid staff selected.'
        elif start_date and end_date and start_date > end_date:
            error = 'End date must be on or after start date.'
        else:
            partition = RetailPartition.objects.create(
                staff_id=int(staff_id) if staff_id else None,
                start_date=start_date,
                end_date=end_date,
                remark=remark,
                created_by=request.user,
            )
            messages.success(request, f'Retail partition {partition.code} created successfully.')
            return redirect('warehouse_retail_partition_detail', partition_id=partition.id)

    context = {
        'error': error,
        'today': timezone.localdate(),
    }
    return render(request, 'warehouse/retail_partition_form.html', context)

@login_required
@user_passes_test(is_warehouse_staff)
def retail_partition_detail(request, partition_id):
    partition = get_object_or_404(RetailPartition, id=partition_id)
    products = Product.objects.all().order_by('product_name')
    error = None
    status_error = None

    if request.method == 'POST':
        form_type = (request.POST.get('form_type') or '').strip()

        if form_type == 'status_update':
            new_status = (request.POST.get('status') or '').strip().upper()
            allowed_statuses = {
                RetailPartition.OPEN,
                RetailPartition.CLOSED,
                RetailPartition.CANCELLED,
            }

            if new_status not in allowed_statuses:
                status_error = 'Invalid partition status.'
            else:
                partition.status = new_status
                if new_status == RetailPartition.CLOSED and not partition.end_date:
                    partition.end_date = timezone.localdate()
                partition.save(update_fields=['status', 'end_date'])
                messages.success(request, f'Partition status updated to {partition.get_status_display()}.')
                return redirect('warehouse_retail_partition_detail', partition_id=partition.id)

        elif partition.status != RetailPartition.OPEN:
            error = 'This partition is not open. Re-open it first to record movements.'
        else:
            action_type = (request.POST.get('action_type') or '').strip().upper()
            product_id = (request.POST.get('product_id') or '').strip()
            quantity_raw = (request.POST.get('quantity') or '').strip()
            ref_no = (request.POST.get('ref_no') or '').strip()
            remark = (request.POST.get('remark') or '').strip()

            try:
                quantity = int(quantity_raw)
            except (TypeError, ValueError):
                quantity = 0

            product = Product.objects.filter(id=product_id).first() if product_id.isdigit() else None

            if action_type not in {
                RetailPartitionMovement.TRANSFER,
                RetailPartitionMovement.SALE,
                RetailPartitionMovement.RETURN,
            }:
                error = 'Invalid partition action.'
            elif not product:
                error = 'Please choose a product.'
            elif quantity <= 0:
                error = 'Quantity must be greater than 0.'
            else:
                current_partition_balance = _get_partition_product_balance(partition, product)

                if action_type == RetailPartitionMovement.TRANSFER and quantity > product.stock:
                    error = f'Not enough warehouse stock. Current stock is {product.stock}.'
                elif action_type in {RetailPartitionMovement.SALE, RetailPartitionMovement.RETURN} and quantity > current_partition_balance:
                    error = f'Not enough partition stock. Current partition balance is {current_partition_balance}.'

            if not error:
                unit_price = product.price

                RetailPartitionMovement.objects.create(
                    partition=partition,
                    product=product,
                    action_type=action_type,
                    quantity=quantity,
                    unit_price=unit_price,
                    ref_no=ref_no,
                    remark=remark,
                    created_by=request.user,
                )

                if action_type == RetailPartitionMovement.TRANSFER:
                    product.stock -= quantity
                    StockMovement.objects.create(
                        product=product,
                        movement_type=StockMovement.OUT,
                        unit_price=product.price,
                        quantity=quantity,
                        ref_type='RET_PART',
                        ref_no=partition.code,
                        remark=remark or f'Transferred to retail partition {partition.code}',
                        created_by=request.user,
                    )
                    messages.success(request, 'Stock transferred to retail partition successfully.')

                elif action_type == RetailPartitionMovement.SALE:
                    messages.success(request, 'Retail partition sale recorded successfully.')

                elif action_type == RetailPartitionMovement.RETURN:
                    product.stock += quantity
                    StockMovement.objects.create(
                        product=product,
                        movement_type=StockMovement.IN,
                        unit_price=product.price,
                        quantity=quantity,
                        ref_type='RET_RETURN',
                        ref_no=partition.code,
                        remark=remark or f'Returned from retail partition {partition.code}',
                        created_by=request.user,
                    )
                    messages.success(request, 'Stock returned from retail partition successfully.')

                product.save(update_fields=['stock'])
                return redirect('warehouse_retail_partition_detail', partition_id=partition.id)

    movement_rows = []
    for product in products:
        transferred = partition.movements.filter(
            product=product,
            action_type=RetailPartitionMovement.TRANSFER
        ).aggregate(total=Sum('quantity'))['total'] or 0

        sold = partition.movements.filter(
            product=product,
            action_type=RetailPartitionMovement.SALE
        ).aggregate(total=Sum('quantity'))['total'] or 0

        returned = partition.movements.filter(
            product=product,
            action_type=RetailPartitionMovement.RETURN
        ).aggregate(total=Sum('quantity'))['total'] or 0

        balance = transferred - sold - returned

        if transferred or sold or returned:
            movement_rows.append({
                'product': product,
                'transferred': transferred,
                'sold': sold,
                'returned': returned,
                'balance': balance,
            })

    partition_movements = partition.movements.select_related('product', 'created_by').order_by('-created_at')

    context = {
        'partition': partition,
        'products': products,
        'movement_rows': movement_rows,
        'partition_movements': partition_movements,
        'error': error,
        'status_error': status_error,
        'status_choices': RetailPartition.STATUS_CHOICES,
        'action_types': RetailPartitionMovement.ACTION_TYPES,
    }
    return render(request, 'warehouse/retail_partition_detail.html', context)

@login_required
@user_passes_test(is_warehouse_staff)
# @in_group('Warehouse Staff')
def print_qr(request, sku):
    product = get_object_or_404(Product, sku=sku)
    context = {
        'product': product,
    }
    return render(request, 'warehouse/print_qr.html', context)




@login_required
@user_passes_test(is_warehouse_staff)
def print_all_qr(request):
    products = Product.objects.all().order_by("product_name", "sku")
    context = {
        'products': products,
    }
    return render(request, 'warehouse/print_all_qr.html', context)


@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_list(request):
    invoices = WholesaleInvoice.objects.select_related('created_by').prefetch_related('items').all()

    status = (request.GET.get('status') or '').strip().upper()
    keyword = (request.GET.get('keyword') or '').strip()

    if status in {WholesaleInvoice.DRAFT, WholesaleInvoice.CONFIRMED, WholesaleInvoice.CANCELLED}:
        invoices = invoices.filter(status=status)
    else:
        status = ''

    if keyword:
        invoices = invoices.filter(
            Q(invoice_no__icontains=keyword) |
            Q(customer_name__icontains=keyword) |
            Q(customer_phone__icontains=keyword)
        )

    paginator = Paginator(invoices.order_by('-created_at', '-id'), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'invoices': page_obj,
        'selected_status': status,
        'keyword': keyword,
        'status_choices': WholesaleInvoice.STATUS_CHOICES,
    }
    return render(request, 'warehouse/wholesale_invoice_list.html', context)


@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_create(request):
    error = None

    form_values = {
        'customer_name': '',
        'customer_phone': '',
        'customer_address': '',
        'invoice_date': timezone.localdate().strftime('%Y-%m-%d'),
        'payment_method': '',
        'payment_status': WholesaleInvoice.UNPAID,
        'payment_note': '',
        'discount_amount': '0',
        'remark': '',
    }

    if request.method == 'POST':
        customer_name = (request.POST.get('customer_name') or '').strip()
        customer_phone = (request.POST.get('customer_phone') or '').strip()
        customer_address = (request.POST.get('customer_address') or '').strip()
        invoice_date_raw = (request.POST.get('invoice_date') or '').strip()
        payment_method = (request.POST.get('payment_method') or '').strip()
        payment_status = (request.POST.get('payment_status') or WholesaleInvoice.UNPAID).strip()
        payment_note = (request.POST.get('payment_note') or '').strip()
        discount_raw = (request.POST.get('discount_amount') or '0').strip()
        remark = (request.POST.get('remark') or '').strip()

        form_values = {
            'customer_name': customer_name,
            'customer_phone': customer_phone,
            'customer_address': customer_address,
            'invoice_date': invoice_date_raw or timezone.localdate().strftime('%Y-%m-%d'),
            'payment_method': payment_method,
            'payment_status': payment_status,
            'payment_note': payment_note,
            'discount_amount': discount_raw,
            'remark': remark,
        }

        invoice_date = parse_date(invoice_date_raw) if invoice_date_raw else timezone.localdate()

        try:
            discount_amount = int(discount_raw or 0)
        except (TypeError, ValueError):
            discount_amount = -1

        valid_payment_methods = {code for code, _ in WholesaleInvoice.PAYMENT_METHOD_CHOICES}
        valid_payment_statuses = {code for code, _ in WholesaleInvoice.PAYMENT_STATUS_CHOICES}

        if not customer_name:
            error = 'Customer name is required.'
        elif invoice_date is None:
            error = 'Invalid invoice date.'
        elif payment_method and payment_method not in valid_payment_methods:
            error = 'Invalid payment method.'
        elif payment_status not in valid_payment_statuses:
            error = 'Invalid payment status.'
        elif discount_amount < 0:
            error = 'Discount amount cannot be negative.'
        else:
            invoice = WholesaleInvoice.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_address=customer_address,
                invoice_date=invoice_date,
                payment_method=payment_method,
                payment_status=payment_status,
                payment_note=payment_note,
                discount_amount=discount_amount,
                remark=remark,
                created_by=request.user,
            )
            invoice.recalculate_totals()
            messages.success(request, f'Wholesale invoice {invoice.invoice_no} created successfully.')
            return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    context = {
        'error': error,
        'form_values': form_values,
        'payment_method_choices': WholesaleInvoice.PAYMENT_METHOD_CHOICES,
        'payment_status_choices': WholesaleInvoice.PAYMENT_STATUS_CHOICES,
    }
    return render(request, 'warehouse/wholesale_invoice_form.html', context)


@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_detail(request, invoice_id):
    invoice = get_object_or_404(
        WholesaleInvoice.objects.prefetch_related('items__product').select_related('created_by'),
        id=invoice_id,
    )
    error = None

    detail_form_values = {
        'customer_name': invoice.customer_name,
        'customer_phone': invoice.customer_phone,
        'customer_address': invoice.customer_address,
        'invoice_date': invoice.invoice_date.strftime('%Y-%m-%d') if invoice.invoice_date else '',
        'payment_method': invoice.payment_method,
        'payment_status': invoice.payment_status,
        'payment_note': invoice.payment_note,
        'discount_amount': str(invoice.discount_amount or 0),
        'remark': invoice.remark,
    }

    scan_value = ''

    if request.method == 'POST':
        form_type = (request.POST.get('form_type') or 'details').strip()

        if form_type == 'details':
            customer_name = (request.POST.get('customer_name') or '').strip()
            customer_phone = (request.POST.get('customer_phone') or '').strip()
            customer_address = (request.POST.get('customer_address') or '').strip()
            invoice_date_raw = (request.POST.get('invoice_date') or '').strip()
            payment_method = (request.POST.get('payment_method') or '').strip()
            payment_status = (request.POST.get('payment_status') or WholesaleInvoice.UNPAID).strip()
            payment_note = (request.POST.get('payment_note') or '').strip()
            discount_raw = (request.POST.get('discount_amount') or '0').strip()
            remark = (request.POST.get('remark') or '').strip()

            detail_form_values = {
                'customer_name': customer_name,
                'customer_phone': customer_phone,
                'customer_address': customer_address,
                'invoice_date': invoice_date_raw,
                'payment_method': payment_method,
                'payment_status': payment_status,
                'payment_note': payment_note,
                'discount_amount': discount_raw,
                'remark': remark,
            }

            invoice_date = parse_date(invoice_date_raw) if invoice_date_raw else None

            try:
                discount_amount = int(discount_raw or 0)
            except (TypeError, ValueError):
                discount_amount = -1

            valid_payment_methods = {code for code, _ in WholesaleInvoice.PAYMENT_METHOD_CHOICES}
            valid_payment_statuses = {code for code, _ in WholesaleInvoice.PAYMENT_STATUS_CHOICES}

            if invoice.status != WholesaleInvoice.DRAFT:
                error = 'Only draft invoices can be edited.'
            elif not customer_name:
                error = 'Customer name is required.'
            elif invoice_date is None:
                error = 'Invalid invoice date.'
            elif payment_method and payment_method not in valid_payment_methods:
                error = 'Invalid payment method.'
            elif payment_status not in valid_payment_statuses:
                error = 'Invalid payment status.'
            elif discount_amount < 0:
                error = 'Discount amount cannot be negative.'
            else:
                invoice.customer_name = customer_name
                invoice.customer_phone = customer_phone
                invoice.customer_address = customer_address
                invoice.invoice_date = invoice_date
                invoice.payment_method = payment_method
                invoice.payment_status = payment_status
                invoice.payment_note = payment_note
                invoice.discount_amount = discount_amount
                invoice.remark = remark
                invoice.save(update_fields=[
                    'customer_name',
                    'customer_phone',
                    'customer_address',
                    'invoice_date',
                    'payment_method',
                    'payment_status',
                    'payment_note',
                    'discount_amount',
                    'remark',
                ])
                invoice.recalculate_totals()
                messages.success(request, 'Wholesale invoice updated successfully.')
                return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    items = invoice.items.select_related('product').all().order_by('id')
    invoice.recalculate_totals(save=False)

    context = {
        'invoice': invoice,
        'items': items,
        'error': error,
        'detail_form_values': detail_form_values,
        'scan_value': scan_value,
        'payment_method_choices': WholesaleInvoice.PAYMENT_METHOD_CHOICES,
        'payment_status_choices': WholesaleInvoice.PAYMENT_STATUS_CHOICES,
    }
    return render(request, 'warehouse/wholesale_invoice_detail.html', context)


@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_scan_item(request, invoice_id):
    invoice = get_object_or_404(WholesaleInvoice, id=invoice_id)

    if request.method != 'POST':
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    if invoice.status != WholesaleInvoice.DRAFT:
        messages.error(request, 'Only draft invoices can accept scanned products.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    scanned_code = (request.POST.get('scanned_code') or '').strip()
    quantity_raw = (request.POST.get('quantity') or '1').strip()

    try:
        quantity = int(quantity_raw or 1)
    except (TypeError, ValueError):
        quantity = 0

    if not scanned_code:
        messages.error(request, 'Please scan or enter a product QR/SKU.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    if quantity <= 0:
        messages.error(request, 'Quantity must be greater than 0.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    sku = scanned_code
    if '|' in scanned_code:
        parts = scanned_code.split('|', 1)
        sku = parts[1].strip()

    product = Product.objects.filter(sku=sku).first()
    if not product:
        messages.error(request, f'No product found for scanned code: {scanned_code}')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    item, created = WholesaleInvoiceItem.objects.get_or_create(
        invoice=invoice,
        product=product,
        defaults={
            'quantity': quantity,
            'unit_price': product.wholesale_price or 0,
        },
    )

    if not created:
        item.quantity += quantity
        item.save(update_fields=['quantity', 'unit_price', 'line_total'])

    invoice.recalculate_totals()

    messages.success(
        request,
        f'{product.product_name} added to {invoice.invoice_no}.' if created else f'{product.product_name} quantity updated in {invoice.invoice_no}.',
    )
    return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)


@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_update_item(request, invoice_id, item_id):
    invoice = get_object_or_404(WholesaleInvoice, id=invoice_id)
    item = get_object_or_404(WholesaleInvoiceItem, id=item_id, invoice=invoice)

    if request.method != 'POST':
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    if invoice.status != WholesaleInvoice.DRAFT:
        messages.error(request, 'Only draft invoices can be edited.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    quantity_raw = (request.POST.get('quantity') or '').strip()
    unit_price_raw = (request.POST.get('unit_price') or '').strip()

    try:
        quantity = int(quantity_raw)
    except (TypeError, ValueError):
        quantity = 0

    try:
        unit_price = int(unit_price_raw)
    except (TypeError, ValueError):
        unit_price = -1

    if quantity <= 0:
        messages.error(request, 'Quantity must be greater than 0.')
    elif unit_price < 0:
        messages.error(request, 'Unit price cannot be negative.')
    else:
        item.quantity = quantity
        item.unit_price = unit_price
        item.save(update_fields=['quantity', 'unit_price', 'line_total'])
        invoice.recalculate_totals()
        messages.success(request, 'Invoice item updated successfully.')

    return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)


@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_delete_item(request, invoice_id, item_id):
    invoice = get_object_or_404(WholesaleInvoice, id=invoice_id)
    item = get_object_or_404(WholesaleInvoiceItem, id=item_id, invoice=invoice)

    if request.method != 'POST':
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    if invoice.status != WholesaleInvoice.DRAFT:
        messages.error(request, 'Only draft invoices can be edited.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    product_name = item.product.product_name
    item.delete()
    invoice.recalculate_totals()
    messages.success(request, f'{product_name} removed from invoice.')
    return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)


@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_confirm(request, invoice_id):
    invoice = get_object_or_404(WholesaleInvoice.objects.prefetch_related('items__product'), id=invoice_id)

    if request.method != 'POST':
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    if invoice.status != WholesaleInvoice.DRAFT:
        messages.error(request, 'This invoice is already processed.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    items = list(invoice.items.select_related('product').all())
    if not items:
        messages.error(request, 'Cannot confirm an invoice without items.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    insufficient_products = []
    for item in items:
        if item.quantity > item.product.stock:
            insufficient_products.append(
                f'{item.product.product_name} (stock {item.product.stock}, requested {item.quantity})'
            )

    if insufficient_products:
        messages.error(request, 'Not enough stock for: ' + ', '.join(insufficient_products))
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    with transaction.atomic():
        for item in items:
            product = Product.objects.select_for_update().get(id=item.product_id)
            if item.quantity > product.stock:
                messages.error(
                    request,
                    f'Not enough stock for {product.product_name}. Current stock is {product.stock}.',
                )
                return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

            product.stock -= item.quantity
            product.save(update_fields=['stock'])

            WholesaleMovement.objects.create(
                product=product,
                invoice=invoice,
                movement_type=WholesaleMovement.OUT,
                unit_price=item.unit_price,
                quantity=item.quantity,
                ref_type='CUS_INV',
                ref_no=invoice.invoice_no,
                remark=invoice.remark or f'Wholesale invoice {invoice.invoice_no}',
                created_by=request.user,
            )

        invoice.status = WholesaleInvoice.CONFIRMED
        invoice.save(update_fields=['status'])
        invoice.recalculate_totals()

    messages.success(request, f'Wholesale invoice {invoice.invoice_no} confirmed successfully.')
    return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)


# wholesale_invoice_print
@login_required
@user_passes_test(is_warehouse_staff)
def wholesale_invoice_print(request, invoice_id):
    invoice = get_object_or_404(
        WholesaleInvoice.objects.prefetch_related('items__product').select_related('created_by'),
        id=invoice_id,
    )

    if invoice.status != WholesaleInvoice.CONFIRMED:
        messages.error(request, 'Only confirmed invoices can be printed.')
        return redirect('warehouse_wholesale_invoice_detail', invoice_id=invoice.id)

    items = invoice.items.select_related('product').all().order_by('id')
    invoice.recalculate_totals(save=False)

    context = {
        'invoice': invoice,
        'items': items,
    }
    return render(request, 'warehouse/wholesale_invoice_print.html', context)

@login_required
@user_passes_test(is_warehouse_staff)
def scan(request, sku):
    product = get_object_or_404(Product, sku=sku)
    ref_type_choices = StockMovement.REF_TYPES
    error = None
    mm_tz = ZoneInfo('Asia/Yangon')
    current_mm_time = timezone.now().astimezone(mm_tz)

    form_values = {
        'sale_type': 'retail',
        'action': 'IN',
        'quantity': '',
        'created_at': current_mm_time.strftime('%Y-%m-%dT%H:%M'),
        'ref_type': '',
        'ref_no': '',
        'remark': '',
    }

    if request.method == 'POST':
        sale_type = (request.POST.get('sale_type') or 'retail').strip().lower()
        action = request.POST.get('action')
        qty_raw = request.POST.get('quantity')
        created_at_raw = (request.POST.get('created_at') or '').strip()
        ref_type = (request.POST.get('ref_type') or '').strip()
        ref_no = (request.POST.get('ref_no') or '').strip()
        remark = (request.POST.get('remark') or '').strip()

        form_values = {
            'sale_type': sale_type,
            'action': action or 'IN',
            'quantity': qty_raw or '',
            'created_at': created_at_raw or current_mm_time.strftime('%Y-%m-%dT%H:%M'),
            'ref_type': ref_type,
            'ref_no': ref_no,
            'remark': remark,
        }

        try:
            qty = int(qty_raw)
        except (TypeError, ValueError):
            qty = 0

        created_at = parse_datetime(created_at_raw) if created_at_raw else current_mm_time
        if created_at is None and created_at_raw:
            error = 'Invalid date/time'
        elif created_at is not None and timezone.is_naive(created_at):
            created_at = created_at.replace(tzinfo=mm_tz)
        elif created_at is not None:
            created_at = created_at.astimezone(mm_tz)

        if qty <= 0:
            error = 'Quantity must be greater than 0'
        elif sale_type not in ('retail', 'wholesale'):
            error = 'Invalid sale type'
        elif action not in (StockMovement.IN, StockMovement.OUT):
            error = 'Invalid action'
        elif action == StockMovement.OUT and qty > product.stock:
            error = f'Not enough stock. Current stock is {product.stock}'

        valid_ref_types = {code for code, _ in StockMovement.REF_TYPES}
        if ref_type and ref_type not in valid_ref_types:
            error = "Invalid reference type"

        allowed_by_action = {
            StockMovement.IN: {'SUP_INV', 'SUP_REQ', 'RET_RETURN', 'ADJ'},
            StockMovement.OUT: {'CUS_INV', 'CUS_REQ', 'RET_PART', 'ADJ'},
        }
        if not error and ref_type and ref_type not in allowed_by_action.get(action, set()):
            error = "Selected Ref Type is not allowed for this action."

        if not error:
            movement_model = StockMovement if sale_type == 'retail' else WholesaleMovement
            unit_price = product.price if sale_type == 'retail' else product.wholesale_price

            movement_model.objects.create(
                product=product,
                movement_type=action,
                quantity=qty,
                unit_price=unit_price,
                ref_type=ref_type,
                ref_no=ref_no,
                remark=remark,
                created_by=request.user,
                created_at=created_at,
            )

            if action == StockMovement.IN:
                product.stock += qty
                messages.success(request, f'{sale_type.title()} stock IN recorded successfully.')
            else:
                product.stock -= qty
                messages.success(request, f'{sale_type.title()} stock OUT recorded successfully.')

            product.save(update_fields=['stock'])
            return redirect('warehouse_products')

    retail_movements_qs = StockMovement.objects.filter(product=product).order_by('-created_at')
    wholesale_movements_qs = WholesaleMovement.objects.filter(product=product).order_by('-created_at')

    total_in = (product.retail_in or 0) + (product.wholesale_in or 0)
    total_out = (product.retail_out or 0) + (product.wholesale_out or 0)
    net_total = total_in - total_out

    combined_movements = []
    for m in retail_movements_qs:
        m.sale_type = 'retail'
        m.sale_type_label = 'Retail'
        combined_movements.append(m)

    for m in wholesale_movements_qs:
        m.sale_type = 'wholesale'
        m.sale_type_label = 'Wholesale'
        combined_movements.append(m)

    combined_movements.sort(key=lambda m: m.created_at, reverse=True)

    paginator = Paginator(combined_movements, 10)
    page_number = request.GET.get('page')
    movements = paginator.get_page(page_number)

    running = product.stock
    page_rows = []
    for m in movements:
        after = running

        if m.movement_type == StockMovement.IN:
            before = running - m.quantity
        else:
            before = running + m.quantity

        page_rows.append({
            'obj': m,
            'sale_type': getattr(m, 'sale_type', ''),
            'sale_type_label': getattr(m, 'sale_type_label', ''),
            'balance_after': after,
            'balance_before': before,
        })
        running = before

    context = {
        'product': product,
        'error': error,
        'movements': movements,
        'rows': page_rows,
        'ref_type_choices': ref_type_choices,
        'form_values': form_values,
        'total_in': total_in,
        'total_out': total_out,
        'net_total': net_total,
    }
    return render(request, 'warehouse/scan.html', context)


# from django.utils.dateparse import parse_date
# from django.utils import timezone
# from datetime import timedelta

@login_required
@user_passes_test(is_warehouse_staff)
def movement_list(request):
    """All stock movements with filters + date range, suitable for printing receipts."""

    qs = (
        StockMovement.objects
        .select_related('product', 'product__category', 'created_by')
        .all()
        .order_by('-created_at')
    )

    # --- Filters ---
    keyword = (request.GET.get('keyword') or '').strip()
    if keyword:
        qs = qs.filter(
            Q(product__product_name__icontains=keyword) |
            Q(product__sku__icontains=keyword)
        )

    category_id = (request.GET.get('category') or '').strip()
    if category_id.lower() == 'none':
        category_id = ''
    if category_id.isdigit():
        qs = qs.filter(product__category_id=int(category_id))

    movement_type = (request.GET.get('type') or '').strip().upper()
    if movement_type in (StockMovement.IN, StockMovement.OUT):
        qs = qs.filter(movement_type=movement_type)
    else:
        movement_type = ''

    ref_type = (request.GET.get('ref_type') or '').strip()
    valid_ref_types = {code for code, _ in StockMovement.REF_TYPES}
    if ref_type in valid_ref_types:
        qs = qs.filter(ref_type=ref_type)
    else:
        ref_type = ''

    # Date range (inclusive)
    start_date_str = (request.GET.get('start') or '').strip()
    end_date_str = (request.GET.get('end') or '').strip()

    start_date = parse_date(start_date_str) if start_date_str else None
    end_date = parse_date(end_date_str) if end_date_str else None

    # Quick presets (daily/weekly/monthly)
    preset = (request.GET.get('preset') or '').strip().lower()
    today = timezone.localdate()

    if preset in ('daily', 'today') and not (start_date or end_date):
        start_date = today
        end_date = today
    elif preset == 'weekly' and not (start_date or end_date):
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif preset == 'monthly' and not (start_date or end_date):
        start_date = today.replace(day=1)
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1, day=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1, day=1)
        end_date = next_month - timedelta(days=1)

    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)

    # --- Totals for the filtered result set ---
    total_in = qs.filter(movement_type=StockMovement.IN).aggregate(s=Sum('quantity'))['s'] or 0
    total_out = qs.filter(movement_type=StockMovement.OUT).aggregate(s=Sum('quantity'))['s'] or 0
    net_total = total_in - total_out

    total_out_amount = qs.filter(
        movement_type=StockMovement.OUT
    ).aggregate(
        total=Sum(ExpressionWrapper(F('quantity') * F('unit_price'), output_field=IntegerField()))
    )['total'] or 0

    total_in_amount = qs.filter(
        movement_type=StockMovement.IN
    ).aggregate(
        total=Sum(ExpressionWrapper(F('quantity') * F('unit_price'), output_field=IntegerField()))
    )['total'] or 0

    total_sell_amount = total_out_amount - total_in_amount

    # Pagination
    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page')
    movements = paginator.get_page(page_number)

    categories = Category.objects.all().order_by('category_name')
    ref_type_choices = StockMovement.REF_TYPES

    context = {
        'movements': movements,
        'categories': categories,
        'keyword': keyword,
        'selected_category': category_id,
        'movement_type': movement_type,
        'ref_type': ref_type,
        'ref_type_choices': ref_type_choices,
        'start': start_date_str,
        'end': end_date_str,
        'preset': preset,
        'total_in': total_in,
        'total_out': total_out,
        'net_total': net_total,
        'total_sell_amount': total_sell_amount,
    }
    return render(request, 'warehouse/movements.html', context)
    