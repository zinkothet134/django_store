"""
URL configuration for chuefamily project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from . import views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    # path("admin/", include('admin_honeypot.urls', namespace='admin_honeypot')),
    path("admin/", admin.site.urls),

    #for all apps
    path("", views.home, name='home'),
    path("store/", include('store.urls')),
    path("accounts/", include('accounts.urls')),
    path("warehouse/", include('warehouse.urls')),

    # for languages
    path("i18n/", include('django.conf.urls.i18n')), # for language setup
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
