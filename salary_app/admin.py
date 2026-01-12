from django.contrib import admin
from .models import Sale, SalaryPayment, BitrixUser, Company, Employee, ExpenseType, ProductionExpense

# Register your models here.
admin.site.register(Sale)
admin.site.register(SalaryPayment)
admin.site.register(BitrixUser)
admin.site.register(Company)
admin.site.register(Employee)
admin.site.register(ExpenseType)
admin.site.register(ProductionExpense)
