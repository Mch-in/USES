from django import forms
from .models import Employee, ExpenseType, ProductionExpense, SalaryPayment, BitrixUser
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User as DjangoUser
from django.db import transaction

class RegistrationForm(UserCreationForm):
    manager = forms.ModelChoiceField(
        queryset=BitrixUser.objects.filter(django_user__isnull=True),
        label="Сотрудник из Bitrix",
        required=True,
        help_text="Выберите сотрудника, для которого создается аккаунт."
    )
    is_admin = forms.BooleanField(label="Сделать администратором", required=False)

    class Meta(UserCreationForm.Meta):
        model = DjangoUser
        fields = ("username", "manager")

    @transaction.atomic
    def save(self, commit=True):
        django_user = super().save(commit=commit)
        if commit:
            bitrix_user = self.cleaned_data['manager']
            bitrix_user.django_user = django_user
            bitrix_user.is_admin = self.cleaned_data.get('is_admin', False)
            bitrix_user.save()
        return django_user

class SalaryPaymentForm(forms.ModelForm):
    class Meta:
        model = SalaryPayment
        fields = ['manager', 'amount', 'payment_datetime']
        widgets = {
            'payment_datetime': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
        labels = {
            'manager': 'Менеджер',
            'amount': 'Сумма выплаты',
            'payment_datetime': 'Дата и время выплаты',
        }

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['name']
        labels = {'name': 'Имя сотрудника'}

class ExpenseTypeForm(forms.ModelForm):
    class Meta:
        model = ExpenseType
        fields = ['name']
        labels = {'name': 'Название вида расходов'}

class ProductionExpenseForm(forms.ModelForm):
    class Meta:
        model = ProductionExpense
        fields = ['employee', 'expense_type', 'amount', 'comment', 'expense_date']
        widgets = {
            'expense_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'comment': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'employee': 'Сотрудник',
            'expense_type': 'Вид расходов',
            'amount': 'Сумма',
            'expense_date': 'Дата расхода',
            'comment': 'Комментарий',
        }