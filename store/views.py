from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from category.models import Category
from .models import Product, Variation
from django.db.models import Q, Min, Max

def store(request, category_slug=None):
    category = None

    # Base queryset
    products = Product.objects.filter(
        is_available=True,
        category__isnull=False,
        slug__isnull=False,
        category__slug__isnull=False,
    ).exclude(
        slug='',
        category__slug='',
    )

    # Category filter
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category=category)

    # Size filter
    selected_sizes = request.GET.getlist('size')
    if selected_sizes:
        products = products.filter(
            variation__variation_category='size',
            variation__variation_value__in=selected_sizes,
            variation__is_active=True,
        ).distinct()

    # Dynamic sizes (always available)
    size_manager = getattr(Variation.objects, 'sizes', None)
    if callable(size_manager):
        sizes_qs = size_manager()
    else:
        sizes_qs = Variation.objects.filter(
            variation_category__iexact='size',
            is_active=True,
        )

    sizes = (
        sizes_qs
        .filter(product__in=products)
        .values_list('variation_value', flat=True)
        .distinct()
        .order_by('variation_value')
    )

    # Price filter from DB
    try:
        price_stats = products.aggregate(min_price=Min('price'), max_price=Max('price'))
        db_min_price = price_stats['min_price']
        db_max_price = price_stats['max_price']
        price_ranges = _build_price_ranges(db_min_price, db_max_price, buckets=5)
    except Exception:
        db_min_price = None
        db_max_price = None
        price_ranges = []

    # From browser request
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    if min_price:
        try:
            products = products.filter(price__gte=int(min_price))
        except (TypeError, ValueError):
            min_price = None

    if max_price:
        try:
            products = products.filter(price__lte=int(max_price))
        except (TypeError, ValueError):
            max_price = None

    # Order newest first
    products = products.order_by('-created_at')

    # Pagination (consistent)
    paginator = Paginator(products, 6)
    page = request.GET.get('page')
    paged_products = paginator.get_page(page)

    context = {
        'products': paged_products,
        'product_count': products.count(),
        'category': category,
        'sizes': sizes,
        'selected_sizes': selected_sizes,
        'min_price': min_price,
        'max_price': max_price,
        'db_min_price': db_min_price,
        'db_max_price': db_max_price,
        'price_ranges': price_ranges,
    }

    return render(request, 'store/store.html', context)

def _build_price_ranges(min_p, max_p, buckets=5):
    """
    Return list of dicts:
    [{'min': 100, 'max': 180}, ...] length=buckets

    Uses equal-width ranges. Handles edge cases (min==max, None).
    """
    if min_p is None or max_p is None:
        return []
    min_p = int(min_p)
    max_p = int(max_p)

    if min_p >= max_p:
        #All products are the same prices --> one range
        return [{
            'min': min_p,
            'max': max_p,
            }]
    span = max_p - min_p
    step = max(1, span // buckets) #avoid zero step 

    ranges = []
    start = min_p
    for i in range(buckets):
        end = start + step
        if i == buckets -1:
            end = max_p
        ranges.append({
            'min': start,
            'max': end,
        })
        start = end + 1

        if start > max_p:
            break
    return ranges



def product_detail(request, category_slug, product_slug):
    """
    Product detail page:
    /store/<category_slug>/<product_slug>/
    """
    category = get_object_or_404(Category, slug=category_slug)
    product = get_object_or_404(Product, slug=product_slug, category=category)

    context = {
        'single_product': product,
    }
    return render(request, 'store/product_detail.html', context)

def search(request):
    """
    Search products by keyword in product_name (and optionally description).
    URL:
      /store/search/?keyword=xxx
    """
    keyword = request.GET.get('keyword', '').strip()
    product_qs = Product.objects.filter(
        is_available=True,
        category__isnull=False,
        slug__isnull=False,
        category__slug__isnull=False,
    ).exclude(
        slug='',
        category__slug='',
    )

    if keyword:
        product_qs = product_qs.filter(
            Q(product_name__icontains=keyword) |
            Q(description__icontains=keyword)
        ).order_by('-created_at')
    else:
        product_qs = product_qs.order_by('-created_at')

    paginator = Paginator(product_qs, 6)
    page = request.GET.get('page')
    paged_products = paginator.get_page(page)

    context = {
        'products': paged_products,
        'product_count': product_qs.count(),
        'keyword': keyword,
        'category': None,
        'sizes': [],
        'selected_sizes': [],
        'min_price': None,
        'max_price': None,
        'db_min_price': None,
        'db_max_price': None,
        'price_ranges': [],
    }
    return render(request, 'store/store.html', context)



