from django.db import models
from django.urls import reverse
from django.utils import translation
# Create your models here.


class Category(models.Model):
    category_name = models.CharField(max_length=100, unique=True)
    name_my = models.CharField(max_length=100, blank=True, null=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(max_length=500, blank=True)
    cat_image = models.ImageField(upload_to='photos/categories/', blank=True)
    sku_prefix = models.CharField(max_length=50, unique=True)


    class Meta:
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'

    def get_url(self):
        return reverse('products_by_category', args=[self.slug])
    
    @property
    def display_name(self):
        if translation.get_language() == "my" and self.name_my:
            return self.name_my
        return self.category_name

    def save(self, *args, **kwargs):
        if not self.sku_prefix:
            self.sku_prefix = self.category_name[:2].upper()
        super().save(*args, **kwargs)



    def __str__(self):
        return self.category_name