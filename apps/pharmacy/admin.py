from django.contrib import admin

from .models import StockItem, StockTransaction


class StockTransactionInline(admin.TabularInline):
    model = StockTransaction
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    inlines = [StockTransactionInline]
    list_display = ("name", "quantity_on_hand", "unit", "reorder_level", "is_low", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "drug__generic_name", "drug__brand_name")


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ("item", "change", "reason", "reference", "created_by", "created_at")
    list_filter = ("reason",)
    search_fields = ("item__name", "reference")
    readonly_fields = ("created_at",)
