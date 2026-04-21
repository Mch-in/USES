from django import forms
from decimal import Decimal, InvalidOperation
from .models import Employee, ExpenseType, ProductionExpense, SalaryPayment, CrmUser
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User as DjangoUser
from django.db import transaction
from django.utils.translation import gettext_lazy as _

class RegistrationForm(UserCreationForm):
    manager = forms.ModelChoiceField(
        queryset=CrmUser.objects.filter(django_user__isnull=True),
        label=_("Employee from CRM"),
        required=True,
        help_text=_("Select the employee for whom the account is being created.")
    )
    is_admin = forms.BooleanField(label=_("Make admin"), required=False)

    class Meta:
        model = DjangoUser
        fields = ("username", "manager")

    @transaction.atomic
    def save(self, commit=True):
        django_user = super().save(commit=commit)
        if commit:
            crm_user = self.cleaned_data['manager']
            crm_user.django_user = django_user
            crm_user.is_admin = self.cleaned_data.get('is_admin', False)
            crm_user.save()
        return django_user

class SalaryPaymentForm(forms.ModelForm):
    class Meta:
        model = SalaryPayment
        fields = ['manager', 'amount', 'payment_datetime']
        widgets = {
            'payment_datetime': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
        labels = {
            'manager': _("Manager"),
            'amount': _("Payment amount"),
            'payment_datetime': _("Payment date and time"),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')

        if amount in (None, ''):
            raise forms.ValidationError(_("Enter payment amount."))

        # Keep validation strict for salary payments: decimal number only.
        if not isinstance(amount, Decimal):
            try:
                amount = Decimal(str(amount))
            except (InvalidOperation, ValueError, TypeError):
                raise forms.ValidationError(_("Enter a valid decimal number."))

        return amount

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['name']
        labels = {'name': _("Employee name")}

class ExpenseTypeForm(forms.ModelForm):
    class Meta:
        model = ExpenseType
        fields = ['name']
        labels = {'name': _("Expense type name")}

class ProductionExpenseForm(forms.ModelForm):
    class Meta:
        model = ProductionExpense
        fields = ['employee', 'expense_type', 'amount', 'comment', 'expense_date']
        widgets = {
            'expense_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'comment': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'employee': _("Employee"),
            'expense_type': _("Expense type"),
            'amount': _("Amount"),
            'expense_date': _("Expense date"),
            'comment': _("Comment"),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')

        if amount in (None, ''):
            raise forms.ValidationError(_("Enter amount."))

        if not isinstance(amount, Decimal):
            try:
                amount = Decimal(str(amount))
            except (InvalidOperation, ValueError, TypeError):
                raise forms.ValidationError(_("Enter a valid decimal number."))

        return amount