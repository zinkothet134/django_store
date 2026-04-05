from django.shortcuts import render
from store.models import Product

def home(request):
    products = Product.objects.filter(
        is_available=True,
        category__isnull=False,
        slug__isnull=False,
        category__slug__isnull=False,
    ).exclude(
        slug='',
        category__slug='',
    )

    top_products = sorted(
        products,
        key=lambda p: p.total_retail_sale_qty,
        reverse=True
    )[:8]

    context = {
        'products': top_products,
    }
    return render(request, 'home.html', context)