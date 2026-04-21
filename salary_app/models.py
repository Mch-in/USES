from django.db import models
from django.contrib.auth.models import User as DjangoUser
from django.utils import timezone
# NOTE: Form classes have been moved to a separate forms.py file.



# Renamed from User to avoid conflict with Django's built-in User model.
class CrmUser(models.Model):
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
    manager = models.ForeignKey(CrmUser, on_delete=models.PROTECT, related_name='sales')
    sale = models.DecimalField(max_digits=20, decimal_places=2)
    # Normalization: Replaced company name and id fields with a ForeignKey.
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, to_field='company_id', related_name='sales')
    account_number = models.CharField(max_length=255)
    salary = models.DecimalField(max_digits=20, decimal_places=2)
    closing_date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.pk}:  {self.title}"

class SalaryPayment(models.Model):
    # Using PROTECT prevents accidental deletion of payments if a manager is deleted.
    manager = models.ForeignKey(CrmUser, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_datetime = models.DateTimeField(default=timezone.now)    


    def __str__(self):
        return f"{self.pk}: {self.manager} {self.payment_datetime}"

class ImportLock(models.Model):
    is_locked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    stage = models.CharField(max_length=32, default="idle", blank=True)
    message = models.CharField(max_length=255, blank=True, default="")
    progress_percent = models.FloatField(default=0.0)
    processed = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    eta_seconds = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)

class Employee(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class ExpenseType(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

class AIAnalysisHistory(models.Model):
    """History of ChatGPT requests and responses for each manager."""
    manager = models.ForeignKey(CrmUser, on_delete=models.CASCADE, related_name='ai_analysis_history')
    question = models.TextField(verbose_name="Question")
    answer = models.TextField(verbose_name="Answer", blank=True)
    table_data = models.JSONField(null=True, blank=True, verbose_name="Table data")
    token_usage = models.JSONField(null=True, blank=True, verbose_name="Token usage")
    conversation_history = models.JSONField(null=True, blank=True, verbose_name="Conversation history")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Created at")
    
    class Meta:
        verbose_name = "AI analysis history record"
        verbose_name_plural = "AI analysis history"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['manager', '-created_at']),
        ]
    
    def __str__(self):
        question_preview = self.question[:50] + "..." if len(self.question) > 50 else self.question
        return f"{self.manager} - {question_preview} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"

class ProductionExpense(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='expenses', verbose_name="Employee")
    expense_type = models.ForeignKey(ExpenseType, on_delete=models.PROTECT, related_name='expenses', verbose_name="Expense type")
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="Amount")
    expense_date = models.DateTimeField(default=timezone.now, verbose_name="Expense date")
    comment = models.TextField(blank=True, verbose_name="Comment")

    def __str__(self):
        return f"{self.employee} - {self.expense_type} - {self.amount}"
