from django.contrib import admin
from .models import Sale, SalaryPayment, CrmUser, Company, Employee, ExpenseType, ProductionExpense, AIAnalysisHistory

# Register your models here.
admin.site.register(Sale)
admin.site.register(SalaryPayment)
admin.site.register(CrmUser)
admin.site.register(Company)
admin.site.register(Employee)
admin.site.register(ExpenseType)
admin.site.register(ProductionExpense)
admin.site.register(AIAnalysisHistory)
