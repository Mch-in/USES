from django.db import models
from django.contrib.auth.models import User as DjangoUser
from django.utils import timezone
# NOTE: Form classes have been moved to a separate forms.py file.



# Renamed from User to avoid conflict with Django's built-in User model.
class BitrixUser(models.Model):
    user_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255, blank=True)
    is_admin = models.BooleanField(default=False)
    django_user = models.OneToOneField(DjangoUser, on_delete=models.SET_NULL, null=True, blank=True)


    def __str__(self):
        return f"{self.last_name} {self.name}"

class Company(models.Model):
    company_id = models.IntegerField(unique=True)
    title = models.CharField(max_length=255)

    def __str__(self):
        return self.title

class Sale(models.Model):
    id_number = models.CharField(max_length=255, unique=True)
    # Using PROTECT prevents accidental deletion of sales if a manager is deleted.
    manager = models.ForeignKey(BitrixUser, on_delete=models.PROTECT, related_name='sales')
    sale = models.DecimalField(max_digits=20, decimal_places=2)
    # Normalization: Replaced company name and id fields with a ForeignKey.
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, to_field='company_id', related_name='sales')
    account_number = models.CharField(max_length=255)
    salary = models.DecimalField(max_digits=20, decimal_places=2)
    closing_date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.id}:  {self.title}"

class SalaryPayment(models.Model):
    # Using PROTECT prevents accidental deletion of payments if a manager is deleted.
    manager = models.ForeignKey(BitrixUser, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_datetime = models.DateTimeField(default=timezone.now)    


    def __str__(self):
        return f"{self.id}: {self.manager} {self.payment_datetime}"

class ImportLock(models.Model):
    is_locked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

class Employee(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class ExpenseType(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class ProductionExpense(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='expenses', verbose_name="Сотрудник")
    expense_type = models.ForeignKey(ExpenseType, on_delete=models.PROTECT, related_name='expenses', verbose_name="Вид расходов")
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Сумма")
    expense_date = models.DateTimeField(default=timezone.now, verbose_name="Дата расхода")
    comment = models.TextField(blank=True, verbose_name="Комментарий")

    def __str__(self):
        return f"{self.employee} - {self.expense_type} - {self.amount}"
