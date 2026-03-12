from django.shortcuts import render, get_object_or_404,redirect
from django.db.models import Sum, Q, Case, When, IntegerField, F, ExpressionWrapper
from django.db.models.functions import TruncDate
from store.models import Product, StockMovement
from category.models import Category
from .permissions import in_group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.contrib import messages
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from datetime import timedelta
# Create your views here.

def is_warehouse_staff(user):
    return user.is_superuser or user.is_staff or user.groups.filter(name='Warehouse Staff').exists()

@login_required
@user_passes_test(is_warehouse_staff)
# @in_group('Warehouse Staff')
def dashboard(request):
    total_products = Product.objects.count()
    total_stock = Product.objects.aggregate(total=Sum('stock'))['total'] or 0

    # ---- Date range (default last 15 days) ----
    start_str = (request.GET.get('start') or '').strip()
    end_str = (request.GET.get('end') or '').strip()

    today = timezone.localdate()
    start_date = parse_date(start_str) if start_str else (today - timedelta(days=14))
    end_date = parse_date(end_str) if end_str else today

    # Swap if reversed
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    movements_range = StockMovement.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)

    # ---- Horizontal bar: Top OUT products by quantity (within range) ----
    top_out = (
        movements_range
        .filter(movement_type=StockMovement.OUT)
        .values('product__product_name')
        .annotate(qty_out=Sum('quantity'))
        .order_by('-qty_out')[:10]
    )
    bar_labels = [r['product__product_name'] for r in top_out]
    bar_qty = [r['qty_out'] or 0 for r in top_out]

    # ---- Line chart: Daily OUT quantity + daily OUT income (qty * unit_price) ----
    daily = (
        movements_range
        .filter(movement_type=StockMovement.OUT)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            qty_out=Sum('quantity'),
            income=Sum(ExpressionWrapper(F('quantity') * F('unit_price'), output_field=IntegerField())),
        )
        .order_by('day')
    )

    line_labels = [d['day'].strftime('%Y-%m-%d') for d in daily]
    line_qty = [d['qty_out'] or 0 for d in daily]
    line_income = [d['income'] or 0 for d in daily]

    context = {
        'total_products': total_products,
        'total_stock': total_stock,

        # date range
        'start': start_date.strftime('%Y-%m-%d') if start_date else '',
        'end': end_date.strftime('%Y-%m-%d') if end_date else '',

        # bar chart
        'bar_labels': bar_labels,
        'bar_qty': bar_qty,

        # line chart
        'line_labels': line_labels,
        'line_qty': line_qty,
        'line_income': line_income,
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
        'selected_category':category_id,
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
# @in_group('Warehouse Staff')
def scan(request, sku):
    product = get_object_or_404(Product, sku=sku)
    ref_type_choices = StockMovement.REF_TYPES
    error = None

    # Default form values (so template won’t crash on GET)
    form_values = {
        'action': 'IN',
        'quantity': '',
        'created_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'ref_type': '',
        'ref_no': '',
        'remark': '',
    }


    if request.method == 'POST':
        action = request.POST.get('action')
        qty = int(request.POST.get('quantity') or 0 )
        qty_raw = request.POST.get('quantity')
        created_at_raw = (request.POST.get('created_at') or '').strip()
        ref_type = (request.POST.get('ref_type') or '').strip()
        ref_no = (request.POST.get('ref_no') or '').strip()
        remark = (request.POST.get('remark') or '').strip()

        # keep user inputs if validation fails
        form_values = {
            'action': action or 'IN',
            'quantity': qty_raw or '',
            'created_at': created_at_raw or timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
            'ref_type': ref_type,
            'ref_no': ref_no,
            'remark': remark,
        }
         # safe int conversion 
        try:
            qty = int(qty_raw)
        except(TypeError, ValueError):
            qty = 0

        created_at = parse_datetime(created_at_raw) if created_at_raw else timezone.now()
        if created_at is None and created_at_raw:
            error = 'Invalid date/time'
        elif created_at is not None and timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at, timezone.get_current_timezone())

        if qty <= 0: 
            error = 'Quantity must be greater than 0'
        elif action not in (StockMovement.IN, StockMovement.OUT):
            error = 'Invalid action'
        elif action == StockMovement.OUT and qty > product.stock:
            error = f'Not enough stock. Current stock is {product.stock}'

        valid_ref_types = {code for code, _ in StockMovement.REF_TYPES}
        if ref_type and ref_type not in valid_ref_types:
            error = "Invalid referrence type"
        allowed_by_action = {
            StockMovement.IN: {'SUP_INV', 'SUP_REQ', 'RET_RETURN', 'ADJ'},
            StockMovement.OUT: {'CUS_INV', 'CUS_REQ', 'RET_PART', 'ADJ'},
        }
        if not error and ref_type and ref_type not in allowed_by_action.get(action, set()):
            error = "Selected Ref Type is not allowed for this action."
        if not error:
            unit_price = product.price

            StockMovement.objects.create(
                product = product,
                movement_type = action,
                quantity = qty,
                unit_price = unit_price,
                ref_type = ref_type,
                ref_no = ref_no,
                remark = remark,
                created_by=request.user,
                created_at=created_at,
            )

            #update stock 
            if action == StockMovement.IN:
                product.stock += qty
                # product.save()
                # return redirect('warehouse_scan', sku=sku)
                messages.success(request, 'Stock IN recorded successfully.')
            else:
                product.stock -= qty
                messages.success(request, 'Stock OUT recorded successfully.')
            
            product.save(update_fields=['stock'])
            return redirect('warehouse_products')
    movements_qs = StockMovement.objects.filter(product=product).order_by('-created_at')
    # # pagination 
    # paginator = Paginator(movements_qs, 5)
    # page_number = request.GET.get('page')
    # movements = paginator.get_page(page_number)
    #         # if action == 'OUT':
    #         #     if qty > product.stock:
    #         #         error = 'Not enough stock'
    #         #     else:
    #         #         product.stock -= qty
    #         #         product.save()
    #         #         return redirect('warehouse_scan', sku=sku)
    # context = {
    #     'product': product,
    #     'error': error,
    #     'movements': movements,
    #     'ref_type_choices': ref_type_choices,
    #     'form_values': form_values,
    # }
    # return render(request, 'warehouse/scan.html', context)
    movements_qs = StockMovement.objects.filter(product=product).order_by('-created_at')

# Totals (all records for this product)
    total_in = movements_qs.filter(movement_type=StockMovement.IN).aggregate(s=Sum('quantity'))['s'] or 0
    total_out = movements_qs.filter(movement_type=StockMovement.OUT).aggregate(s=Sum('quantity'))['s'] or 0
    net_total = total_in - total_out

    # Pagination (20 per page)
    paginator = Paginator(movements_qs, 10)
    page_number = request.GET.get('page')
    movements = paginator.get_page(page_number)

    # Running balance for THIS PAGE (from current stock backwards)
    running = product.stock
    page_rows = []
    for m in movements:  # movements is a Page object (iterable)
        # Balance AFTER this movement happened (walking backward in time)
        after = running

        # Move backwards to compute "before"
        if m.movement_type == StockMovement.IN:
            before = running - m.quantity
        else:
            before = running + m.quantity

        page_rows.append({
            "obj": m,
            "balance_after": after,
            "balance_before": before,
        })
        running = before

    context = {
        'product': product,
        'error': error,
        'movements': movements,
        'rows': page_rows,              # ✅ use this in template instead of movements
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
        # Monday .. Sunday of current week
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif preset == 'monthly' and not (start_date or end_date):
        start_date = today.replace(day=1)
        # first day next month minus 1 day
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1, day=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1, day=1)
        end_date = next_month - timedelta(days=1)

    if start_date and end_date and start_date > end_date:
        # swap if user entered reversed
        start_date, end_date = end_date, start_date

    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)

    # --- Totals for the filtered result set ---
    total_in = qs.filter(movement_type=StockMovement.IN).aggregate(s=Sum('quantity'))['s'] or 0
    total_out = qs.filter(movement_type=StockMovement.OUT).aggregate(s=Sum('quantity'))['s'] or 0
    net_total = total_in - total_out

    total_sell_amount = qs.filter(
        movement_type=StockMovement.OUT
        ).aggregate(
            total=Sum(ExpressionWrapper(F('quantity') * F('unit_price'), output_field=IntegerField()))
        )['total'] or 0
    # The above is not correct value; compute value totals using Python over paginated rows or annotate if needed.
    # We'll compute on the current page in the template using qty*unit_price, and show qty totals here.

    # Pagination
    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page')
    movements = paginator.get_page(page_number)

    categories = Category.objects.all().order_by('category_name')

    context = {
        'movements': movements,
        'categories': categories,
        'keyword': keyword,
        'selected_category': category_id,
        'movement_type': movement_type,
        'start': start_date_str,
        'end': end_date_str,
        'preset': preset,
        'total_in': total_in,
        'total_out': total_out,
        'net_total': net_total,
        'total_sell_amount':total_sell_amount,
    }
    return render(request, 'warehouse/movements.html', context)
    