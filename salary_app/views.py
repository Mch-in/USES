from django.shortcuts import render, redirect, get_object_or_404
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from .models import Sale, SalaryPayment, BitrixUser, Company, ImportLock, Employee, ExpenseType, ProductionExpense
from django.contrib import messages
from django.db.models import Sum, IntegerField, Value, CharField, F
from django.http import JsonResponse, HttpResponse
from django.db.models.functions import Cast, Concat, TruncMonth
from django.views.decorators.http import require_GET
from collections import defaultdict
import requests
from requests.exceptions import RequestException, Timeout
from decimal import Decimal, InvalidOperation
from dateutil.parser import parse as parse_date
import openpyxl
from django.db import transaction
from django.utils.timezone import now
from .forms import RegistrationForm, SalaryPaymentForm, ProductionExpenseForm, EmployeeForm, ExpenseTypeForm
from .decorators import admin_required
from . import ai_views
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from urllib.parse import quote
from django.conf import settings
from django.urls import reverse
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'



def _webhook_urls():
    base = settings.BITRIX_WEBHOOK_BASE
    return {
        'deals': f'{base}/crm.deal.list',
        'users': f'{base}/user.get',
        'companies': f'{base}/crm.company.list',
    }


def _post_with_retry(url, *, json, timeout_seconds=15, max_retries=3):
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=json, timeout=timeout_seconds)
            resp.raise_for_status()
            return resp
        except (Timeout, RequestException) as exc:
            last_exc = exc
            logger.warning("Bitrix POST failed (attempt %s/%s): %s", attempt, max_retries, exc)
            if attempt == max_retries:
                break
    raise last_exc


def _validate_webhook_base():
    base = getattr(settings, 'BITRIX_WEBHOOK_BASE', '') or ''
    try:
        parsed = urlparse(base)
    except Exception:
        return "BITRIX_WEBHOOK_BASE: некорректный URL. Проверьте .env"

    if not parsed.scheme or not parsed.netloc:
        return "BITRIX_WEBHOOK_BASE: отсутствует схема/домен. Пример: https://your.bitrix24.ru/rest/1/token"

    host = parsed.hostname or ''
    path = parsed.path or ''

    if 'example.local' in host or 'placeholder' in base:
        return "Укажите реальный вебхук Bitrix24 в .env (BITRIX_WEBHOOK_BASE). Сейчас установлена заглушка."

    if '/rest/' not in path:
        return "BITRIX_WEBHOOK_BASE должен содержать путь вида /rest/<userId>/<token>"

    return None


def index(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Метод не поддерживается"}, status=405)

    # Проверяем корректность настроек вебхука до сетевых запросов
    settings_error = _validate_webhook_base()
    if settings_error:
        return JsonResponse({"success": False, "error": settings_error})

    # 🔒 Обрабатываем блокировку
    with transaction.atomic():
        lock, _ = ImportLock.objects.select_for_update().get_or_create(id=1)

        if lock.is_locked and (now() - lock.updated_at < timedelta(minutes=5)):
            return JsonResponse({"success": False, "error": "Импорт уже выполняется другим пользователем. Попробуйте позже."})

        lock.is_locked = True
        lock.updated_at = now()
        lock.save()

    try:
        # Импорт пользователей и компаний
        # These functions now return a map for faster lookups
        user_map = import_users()
        company_map = import_companies()

        sales_to_create = []
        start = 0
        # Fetch existing deal IDs to avoid duplicates.
        existing_ids = set(Sale.objects.values_list('id_number', flat=True))

        while True:
            # PERFORMANCE: Select only the fields you need.
            data = {
                'start': start,
                'select': [
                    'ID', 'ASSIGNED_BY_ID', 'STAGE_ID', 'OPPORTUNITY',
                    'CLOSEDATE', 'COMPANY_ID', 'UF_CRM_1736157032', 'UF_CRM_1740138171',
                    'TITLE'
                ]
            }

            response = _post_with_retry(_webhook_urls()['deals'], json=data)
            response_json = response.json()

            batch = response_json.get('result', [])
            if not batch:
                break

            for item in batch:
                # Process only won deals
                if item.get('STAGE_ID') != "C1:WON":
                    continue

                deal_id = str(item.get('ID'))
                # Skip deals that are already in the database
                if deal_id in existing_ids:
                    continue

                # PERFORMANCE: Use pre-fetched map instead of a DB query in a loop.
                manager = user_map.get(int(item.get('ASSIGNED_BY_ID')))
                if not manager:
                    continue  # Неизвестный пользователь — пропускаем

                try:
                    closing_date = parse_date(item.get("CLOSEDATE")).date() if item.get("CLOSEDATE") else None
                except (ValueError, TypeError):
                    closing_date = None

                company_id = item.get('COMPANY_ID')
                # PERFORMANCE: Use pre-fetched map.
                company = company_map.get(int(company_id)) if company_id else None

                sales_to_create.append(Sale(
                    id_number=deal_id,
                    manager=manager,
                    sale=item.get('OPPORTUNITY') or 0,
                    company=company, # Assign ForeignKey object
                    account_number=(
                        item.get('UF_CRM_1740138171')[0]
                        if isinstance(item.get('UF_CRM_1740138171'), list) and item.get('UF_CRM_1740138171')
                        else item.get('UF_CRM_1740138171') or ""
                    ),
                    salary=parse_decimal(item.get('UF_CRM_1736157032')),
                    closing_date=closing_date,
                    title=item.get('TITLE') or '',
                ))

            if 'next' in response_json:
                start = response_json['next']
            else:
                break

        # PERFORMANCE: Use bulk_create for efficient insertion.
        if sales_to_create:
            Sale.objects.bulk_create(sales_to_create, ignore_conflicts=True)
        return JsonResponse({"success": True, "message": f"Обновление завершено. Добавлено {len(sales_to_create)} новых сделок."})

    except Exception as e:
        logger.exception("Import failed: %s", e)
        # Возвращаем 200 с success:false, чтобы фронтенд не считал это сетевой ошибкой
        return JsonResponse({"success": False, "error": "Не удалось обновить продажи. Проверьте настройки интеграции и повторите попытку."}, status=200)

    finally:
        # 🔓 Снимаем блокировку
        ImportLock.objects.filter(id=1).update(is_locked=False)


def import_users():
    """
    Imports or updates users from Bitrix24.
    PERFORMANCE: Uses bulk operations to minimize database queries.
    Returns a dictionary mapping user_id to BitrixUser object for quick lookups.
    """
    try:
        start = 0
        existing_users = {u.user_id: u for u in BitrixUser.objects.all()}
        users_to_create = []
        users_to_update = []

        while True:
            payload = {"start": start}
            response = _post_with_retry(_webhook_urls()['users'], json=payload)
            api_users = response.json().get("result", [])
            if not api_users:
                break

            for u in api_users:
                user_id = int(u["ID"])
                user_data = {
                    "name": u.get("NAME") or "",
                    "last_name": u.get("LAST_NAME") or "",
                }
                if user_id in existing_users:
                    existing_user = existing_users[user_id]
                    if existing_user.name != user_data['name'] or existing_user.last_name != user_data['last_name']:
                        existing_user.name = user_data['name']
                        existing_user.last_name = user_data['last_name']
                        users_to_update.append(existing_user)
                else:
                    users_to_create.append(BitrixUser(user_id=user_id, **user_data))

            if "next" in response.json():
                start = response.json()["next"]
            else:
                break

        if users_to_create:
            BitrixUser.objects.bulk_create(users_to_create)
        if users_to_update:
            BitrixUser.objects.bulk_update(users_to_update, ['name', 'last_name'])

        logger.info("Импорт пользователей завершён")
        # Return a fresh map of all users
        return {u.user_id: u for u in BitrixUser.objects.all()}
    except Exception as e:
        logger.exception("Ошибка при импорте пользователей: %s", e)
        return {}


def import_companies():
    """
    Imports or updates companies from Bitrix24.
    PERFORMANCE: Uses bulk operations to minimize database queries.
    Returns a dictionary mapping company_id to Company object for quick lookups.
    """
    try:
        start = 0
        existing_companies = {c.company_id: c for c in Company.objects.all()}
        companies_to_create = []
        companies_to_update = []

        while True:
            payload = {"start": start, "select": ["ID", "TITLE"]}
            response = _post_with_retry(_webhook_urls()['companies'], json=payload)
            api_companies = response.json().get("result", [])
            if not api_companies:
                break

            for c in api_companies:
                company_id = int(c["ID"])
                title = c.get("TITLE") or ""
                if company_id in existing_companies:
                    if existing_companies[company_id].title != title:
                        existing_companies[company_id].title = title
                        companies_to_update.append(existing_companies[company_id])
                else:
                    companies_to_create.append(Company(company_id=company_id, title=title))

            if "next" in response.json():
                start = response.json()["next"]
            else:
                break

        if companies_to_create:
            Company.objects.bulk_create(companies_to_create)
        if companies_to_update:
            Company.objects.bulk_update(companies_to_update, ['title'])

        logger.info("Импорт компаний завершён")
        return {c.company_id: c for c in Company.objects.all()}
    except Exception as e:
        logger.exception("Ошибка при импорте компаний: %s", e)
        return {}

def parse_decimal(value):
    try:
        if isinstance(value, list):
            value = value[0] if value else ''
        value = str(value).replace(" ", "").replace("М", "").replace(",", ".").strip()
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.0")
    

@login_required
def sales_list(request):
    # Filter parameters
    month = request.GET.get('month')
    year_param = request.GET.get('year')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    filter_type = request.GET.get('filter_type', 'month')
    sort_by = request.GET.get('sort', 'closing_date')
    order = request.GET.get('order', 'desc')

    months = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
    }

    try:
        # Use BitrixUser model
        current_user = BitrixUser.objects.get(django_user=request.user)
    except BitrixUser.DoesNotExist:
        current_user = None

    is_admin = current_user.is_admin if current_user else False

    # Base querysets
    sales = Sale.objects.select_related('manager', 'company').annotate(
        id_as_int=Cast('id_number', IntegerField())
    )

    # Whitelist and mapping for sorting
    sortable_fields = {
        'id': 'id_as_int',
        'manager': 'manager__last_name',
        'company': 'company__title',
        'account_number': 'account_number',
        'closing_date': 'closing_date',
        'sale': 'sale',
        'salary': 'salary',
    }

    # Default sort
    final_order_by = ['-closing_date', '-id_as_int']

    if sort_by in sortable_fields:
        sort_field = sortable_fields[sort_by]
        prefix = '-' if order == 'desc' else ''
        final_order_by = [f'{prefix}{sort_field}', '-id_as_int']

    sales = sales.order_by(*final_order_by)


    salary_qs = SalaryPayment.objects.all()

    manager_id = request.GET.get('manager')

    if not is_admin and current_user:
        # Ограничиваем доступ только к своим продажам
        sales = sales.filter(manager=current_user)
        salary_qs = salary_qs.filter(manager=current_user)
    elif manager_id:
        # Для админа: фильтрация по выбранному менеджеру
        sales = sales.filter(manager_id=manager_id)
        salary_qs = salary_qs.filter(manager_id=manager_id)

    # -------------------------------
    # Date Filtering Logic
    # -------------------------------
    current_year = timezone.now().year
    selected_year = year_param

    # Default to current year if no year is specified on first load
    if year_param is None:
        selected_year = str(current_year)

    if filter_type == 'date_range':
        if date_from and date_to:
            try:
                date_start_naive = datetime.strptime(date_from, "%Y-%m-%d")
                date_end_naive = datetime.strptime(date_to, "%Y-%m-%d")

                # Make them timezone aware
                date_start = timezone.make_aware(date_start_naive)
                date_end = timezone.make_aware(datetime.combine(date_end_naive, datetime.max.time()))

                sales = sales.filter(closing_date__range=(date_start.date(), date_end.date()))
                salary_qs = salary_qs.filter(payment_datetime__gte=date_start, payment_datetime__lte=date_end)
            except ValueError:
                pass # Ignore invalid date formats
    else: # Default to month filtering
        if selected_year:
            try:
                year_int = int(selected_year)
                # Filter by year first
                sales = sales.filter(closing_date__year=year_int)
                
                if month:
                    month_int = int(month)
                    # Filter by month
                    sales = sales.filter(closing_date__month=month_int)
                    
                    # Correctly filter salary_qs for the entire month
                    start_date = datetime(year_int, month_int, 1, tzinfo=timezone.get_current_timezone())
                    if month_int == 12:
                        end_date = datetime(year_int + 1, 1, 1, tzinfo=timezone.get_current_timezone())
                    else:
                        end_date = datetime(year_int, month_int + 1, 1, tzinfo=timezone.get_current_timezone())
                    
                    salary_qs = salary_qs.filter(payment_datetime__gte=start_date, payment_datetime__lt=end_date)
                else:
                    # Filter salary_qs for the entire year if no month is selected
                    salary_qs = salary_qs.filter(payment_datetime__year=year_int)

            except (ValueError, TypeError):
                selected_year = "" # Reset if year is not a valid integer
        elif month:
            # Filter by month only if year is 'All'
            try:
                month_int = int(month)
                sales = sales.filter(closing_date__month=month_int)
                salary_qs = salary_qs.filter(payment_datetime__month=month_int)
            except (ValueError, TypeError):
                pass # Ignore invalid month formats
    # -------------------------------
    # Подсчёты и группировки
    # -------------------------------
    total_salary = sales.aggregate(total=Sum('salary'))['total'] or 0
    total_sales = sales.aggregate(total=Sum('sale'))['total'] or 0

    # Filter expenses based on the same date range
    expenses_qs = ProductionExpense.objects.all()
    expenses_qs = expenses_qs.filter(expense_date__isnull=False)
    if filter_type == 'date_range':
        if date_from and date_to:
            try:
                date_start_naive = datetime.strptime(date_from, "%Y-%m-%d")
                date_end_naive = datetime.strptime(date_to, "%Y-%m-%d")
                date_start = timezone.make_aware(date_start_naive)
                date_end = timezone.make_aware(datetime.combine(date_end_naive, datetime.max.time()))
                expenses_qs = expenses_qs.filter(expense_date__gte=date_start, expense_date__lte=date_end)
            except ValueError:
                pass
    else: # Default to month filtering
        if selected_year:
            try:
                year_int = int(selected_year)
                if month:
                    month_int = int(month)
                    start_date = datetime(year_int, month_int, 1, tzinfo=timezone.get_current_timezone())
                    if month_int == 12:
                        end_date = datetime(year_int + 1, 1, 1, tzinfo=timezone.get_current_timezone())
                    else:
                        end_date = datetime(year_int, month_int + 1, 1, tzinfo=timezone.get_current_timezone())
                    expenses_qs = expenses_qs.filter(expense_date__gte=start_date, expense_date__lt=end_date)
                else:
                    expenses_qs = expenses_qs.filter(expense_date__year=year_int)
            except (ValueError, TypeError):
                pass
        elif month:
            try:
                month_int = int(month)
                expenses_qs = expenses_qs.filter(expense_date__month=month_int)
            except (ValueError, TypeError):
                pass

    total_expenses = expenses_qs.aggregate(total=Sum('amount'))['total'] or 0

    # The salary_qs is now correctly filtered by the same period as sales
    salary_paid = salary_qs.aggregate(total=Sum('amount'))['total'] or 0
    salary_left = total_salary - salary_paid

    grouped_sales = defaultdict(lambda: {'sales': [], 'total_sale': 0, 'total_salary': 0})
    # The sales queryset is already filtered, so we just group it for display.
    for sale in sales:
        if sale.closing_date:
            ym_key = (sale.closing_date.year, sale.closing_date.month)
            grouped_sales[ym_key]['sales'].append(sale)
            grouped_sales[ym_key]['total_sale'] += sale.sale or 0
            grouped_sales[ym_key]['total_salary'] += sale.salary or 0

    grouped_sales = dict(sorted(grouped_sales.items()))

    # --- Chart Data Preparation ---

    # Helper function and dict for sorting month labels
    month_name_to_num = {v: k for k, v in months.items()}
    def month_year_key(m):
        try:
            month_str, year_str = m.split()
            month_num = month_name_to_num.get(month_str, 0)
            year_num = int(year_str)
            return (year_num, month_num)
        except Exception:
            return (0, 0)

    # --- Chart 1: Sales & Salary by Month (using DB aggregation) ---
    chart_agg = sales.annotate(
        month_group=TruncMonth('closing_date')
    ).values('month_group').annotate(
        total_sale=Sum('sale'),
        total_salary=Sum('salary')
    ).order_by('month_group')

    chart_labels = [f"{months[agg['month_group'].month]} {agg['month_group'].year}" for agg in chart_agg if agg['month_group']]
    chart_sales = [agg['total_sale'] for agg in chart_agg if agg['month_group']]
    chart_salary = [agg['total_salary'] for agg in chart_agg if agg['month_group']]
    chart_data = {
        "labels": chart_labels,
        "sales": chart_sales,
        "salaries": chart_salary,
    }

    # --- Chart 2: Expenses by Month (Python aggregation) ---
    monthly_expenses_grouped = defaultdict(float)
    for expense in expenses_qs:
        if expense.expense_date:
            month_label = f"{months[expense.expense_date.month]} {expense.expense_date.year}"
            monthly_expenses_grouped[month_label] += float(expense.amount or 0)
    
    all_months_in_range = set(chart_labels)
    expense_chart_labels = sorted(list(all_months_in_range), key=month_year_key)
    expense_chart_data_values = [monthly_expenses_grouped.get(month, 0) for month in expense_chart_labels]
    expense_chart_data = {
        "labels": expense_chart_labels,
        "data": expense_chart_data_values,
    }

    # --- Chart 3 & 4: Manager Sales and Expenses by Type (Python aggregation) ---
    manager_grouped = defaultdict(lambda: defaultdict(float))
    for sale in sales:
        if sale.closing_date and sale.manager:
            month_label = f"{months[sale.closing_date.month]} {sale.closing_date.year}"
            manager_grouped[str(sale.manager)][month_label] += float(sale.sale or 0)

    expense_type_grouped = defaultdict(lambda: defaultdict(float))
    for expense in expenses_qs.select_related('expense_type'):
        if expense.expense_date and expense.expense_type:
            month_label = f"{months[expense.expense_date.month]} {expense.expense_date.year}"
            expense_type_grouped[str(expense.expense_type.name)][month_label] += float(expense.amount or 0)

    all_sales_months = set(month for manager_data in manager_grouped.values() for month in manager_data)
    all_expense_months = set(month for expense_data in expense_type_grouped.values() for month in expense_data)
    all_months = sorted(list(all_sales_months | all_expense_months), key=month_year_key)

    manager_chart_datasets = []
    for manager, monthly_sales in manager_grouped.items():
        data = [monthly_sales.get(month, 0) for month in all_months]
        manager_chart_datasets.append({
            "label": manager,
            "data": data,
        })

    expense_type_datasets = []
    for expense_type_name, monthly_expenses in expense_type_grouped.items():
        data = [monthly_expenses.get(month, 0) for month in all_months]
        expense_type_datasets.append({
            "label": expense_type_name,
            "data": data,
        })

    chart_data_by_manager = {
        "labels": all_months,
        "datasets": manager_chart_datasets
    }

    salary_manager_grouped = defaultdict(lambda: defaultdict(float))
    for sale in sales:
        if sale.closing_date and sale.manager:
            month_label = f"{months[sale.closing_date.month]} {sale.closing_date.year}"
            salary_manager_grouped[str(sale.manager)][month_label] += float(sale.salary or 0)

    salary_chart_datasets = []
    for manager, monthly_salary in salary_manager_grouped.items():
        data = [monthly_salary.get(month, 0) for month in all_months]
        salary_chart_datasets.append({
            "label": manager,
            "data": data,
        })

    salary_chart_data_by_manager = {
        "labels": all_months,
        "datasets": salary_chart_datasets
    }
    
    expense_type_chart_data = {
        "labels": all_months,
        "datasets": expense_type_datasets
    }

    sales_manager_ids = Sale.objects.values_list('manager_id', flat=True).distinct()

    managers = BitrixUser.objects.filter(id__in=sales_manager_ids).annotate(
        full_name=Concat(F('last_name'), Value(' '), F('name'), output_field=CharField())
    ).values_list('id', 'full_name').distinct()

    # Все доступные года (не из отфильтрованных sales!)
    years = Sale.objects.order_by().values_list('closing_date__year', flat=True).distinct()
    years = sorted(filter(None, years))

    context = {
        "sales": sales,
        "managers": managers,
        "months": months,
        "request": request,
        "selected_year": selected_year,
        "is_admin": is_admin,
        "total_sales": total_sales,
        "total_expenses": total_expenses,
        "salary_paid": salary_paid,
        "salary_left": salary_left,
        "years": years,
        "grouped_sales": grouped_sales,
        "chart_data": chart_data,
        "chart_data_by_manager": chart_data_by_manager,
        "salary_chart_data_by_manager": salary_chart_data_by_manager,
        "expense_chart_data": expense_chart_data,
        "expense_type_chart_data": expense_type_chart_data,
        'sort_by': sort_by,
        'order': order,
    }

    return render(request, 'salary/sales_list.html', context)


def export_salary_excel(request):
    manager_id = request.GET.get('manager')
    month = request.GET.get('month')
    year = request.GET.get('year')

    salary_qs = SalaryPayment.objects.select_related('manager').order_by('-payment_datetime')

    # Определяем, какой год выбран для фильтра
    current_year = datetime.now().year
    if year == "":
        selected_year = ""  # Пользователь выбрал "Все"
    elif not year:
        selected_year = str(current_year)  # По умолчанию текущий год
    else:
        selected_year = year  # Выбран конкретный год

    # Применяем фильтры
    if selected_year:
        try:
            y = int(selected_year)
            tz = timezone.get_current_timezone()
            if month:
                m = int(month)
                start = datetime(y, m, 1, tzinfo=tz)
                end = datetime(y + 1, 1, 1, tzinfo=tz) if m == 12 else datetime(y, m + 1, 1, tzinfo=tz)
            else:
                start = datetime(y, 1, 1, tzinfo=tz)
                end = datetime(y + 1, 1, 1, tzinfo=tz)
            salary_qs = salary_qs.filter(payment_datetime__gte=start, payment_datetime__lt=end)
        except (ValueError, TypeError):
            # Игнорируем некорректные значения года/месяца
            pass

    if manager_id:
        try:
            salary_qs = salary_qs.filter(manager_id=int(manager_id))
        except (ValueError, TypeError):
            # Игнорируем некорректный ID менеджера
            pass

    headers = ["Менеджер", "Дата выплаты", "Сумма"]
    title = "Выплаты"
    filename_prefix = "Выплата ЗП"

    def salary_row_data_extractor(payment):
        manager_name = f"{payment.manager.last_name} {payment.manager.name}"
        date_str = timezone.localtime(payment.payment_datetime).strftime("%d.%m.%Y %H:%M")
        amount = float(payment.amount)
        return [manager_name, date_str, amount]

    return _generate_excel_response(salary_qs, headers, title, filename_prefix, salary_row_data_extractor)


@login_required
@admin_required
def salary_payment_list(request):
    manager_id = request.GET.get('manager')
    month = request.GET.get('month')
    year = request.GET.get('year')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    filter_type = request.GET.get('filter_type', 'month')

    # --- FIX: Get all managers and years for dropdowns from the complete dataset ---
    # This ensures the filter options are always complete.
    all_payments_for_filters = SalaryPayment.objects.all()
    all_payment_manager_ids = all_payments_for_filters.values_list('manager_id', flat=True).distinct()
    all_managers_for_filter = BitrixUser.objects.filter(id__in=all_payment_manager_ids).annotate(
        full_name=Concat(F('last_name'), Value(' '), F('name'), output_field=CharField())
    ).values_list('id', 'full_name')
    # Доступные годы
    years = sorted({dt.year for dt in all_payments_for_filters.values_list('payment_datetime', flat=True) if dt}, reverse=True)
    # --- END FIX ---

    payments = SalaryPayment.objects.select_related('manager').order_by('-payment_datetime')
    
    # Фильтрация по менеджеру
    if manager_id:
        payments = payments.filter(manager_id=manager_id)
    
    # -------------------------------
    # Date Filtering Logic
    # -------------------------------
    current_year = datetime.now().year
    if year == "":
        selected_year = ""          # пользователь выбрал "Все"
    elif not year:
        selected_year = str(current_year)   # первый заход — по умолчанию текущий год
    else:
        selected_year = year        # выбран конкретный год
    
    if filter_type == 'date_range':
        if date_from and date_to:
            try:
                date_start_naive = datetime.strptime(date_from, "%Y-%m-%d")
                date_end_naive = datetime.strptime(date_to, "%Y-%m-%d")
                date_start = timezone.make_aware(date_start_naive)
                date_end = timezone.make_aware(datetime.combine(date_end_naive, datetime.max.time()))
                payments = payments.filter(payment_datetime__gte=date_start, payment_datetime__lte=date_end)
            except ValueError:
                pass  # Ignore invalid date formats
    else:  # Default to month filtering
        if selected_year != "":
            try:
                y = int(selected_year)
                if month:
                    try:
                        m = int(month)
                        tz = timezone.get_current_timezone()
                        start = datetime(y, m, 1, tzinfo=tz)
                        end = datetime(y + 1, 1, 1, tzinfo=tz) if m == 12 else datetime(y, m + 1, 1, tzinfo=tz)
                        payments = payments.filter(payment_datetime__gte=start, payment_datetime__lt=end)
                    except (ValueError, TypeError):
                        pass  # Ignore invalid month formats
                else:
                    tz = timezone.get_current_timezone()
                    start = datetime(y, 1, 1, tzinfo=tz)
                    end = datetime(y + 1, 1, 1, tzinfo=tz)
                    payments = payments.filter(payment_datetime__gte=start, payment_datetime__lt=end)
            except (ValueError, TypeError):
                pass  # Ignore invalid year formats

    total_paid = payments.aggregate(Sum('amount'))['amount__sum'] or 0

    grouped_payments = defaultdict(lambda: {'payments': [], 'total_amount': 0})
    for payment in payments:
        if payment.payment_datetime:
            ym_key = (payment.payment_datetime.year, payment.payment_datetime.month)
            grouped_payments[ym_key]['payments'].append(payment)
            grouped_payments[ym_key]['total_amount'] += payment.amount or 0
            
    grouped_payments = dict(sorted(grouped_payments.items()))

    context = {
        'payments': payments,
        'grouped_payments': grouped_payments,
        'managers': all_managers_for_filter,
        'months': {1:'Январь',2:'Февраль',3:'Март',4:'Апрель',5:'Май',6:'Июнь',
                   7:'Июль',8:'Август',9:'Сентябрь',10:'Октябрь',11:'Ноябрь',12:'Декабрь'},
        'years': years,
        'request': request,
        'selected_year': selected_year,
        'total_paid': total_paid,
    }
    return render(request, 'salary/salary_payment_list.html', context)

@login_required
@admin_required
def production_expense_list(request):
    employee_id = request.GET.get('employee')
    expense_type_id = request.GET.get('expense_type')
    month = request.GET.get('month')
    year = request.GET.get('year')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    filter_type = request.GET.get('filter_type', 'month')

    # Data for filters
    all_employees = Employee.objects.all().order_by('name')
    all_expense_types = ExpenseType.objects.all().order_by('name')
    years = sorted({dt.year for dt in ProductionExpense.objects.values_list('expense_date', flat=True) if dt}, reverse=True)

    expenses = ProductionExpense.objects.select_related('employee', 'expense_type').order_by('-expense_date')

    # Фильтрация по сотруднику и типу расходов
    if employee_id:
        expenses = expenses.filter(employee_id=employee_id)
    
    if expense_type_id:
        expenses = expenses.filter(expense_type_id=expense_type_id)

    # -------------------------------
    # Date Filtering Logic
    # -------------------------------
    req_year = year
    req_month = month

    if req_year == "" or req_year is None:
        selected_year = ""
    else:
        selected_year = req_year

    if filter_type == 'date_range':
        if date_from and date_to:
            try:
                date_start_naive = datetime.strptime(date_from, "%Y-%m-%d")
                date_end_naive = datetime.strptime(date_to, "%Y-%m-%d")
                date_start = timezone.make_aware(date_start_naive)
                date_end = timezone.make_aware(datetime.combine(date_end_naive, datetime.max.time()))
                expenses = expenses.filter(expense_date__gte=date_start, expense_date__lte=date_end)
            except ValueError:
                pass  # Ignore invalid date formats
    else:  # Default to month filtering
        if selected_year != "":
            try:
                y = int(selected_year)
                if month:
                    try:
                        m = int(month)
                        tz = timezone.get_current_timezone()
                        start = datetime(y, m, 1, tzinfo=tz)
                        end = datetime(y + 1, 1, 1, tzinfo=tz) if m == 12 else datetime(y, m + 1, 1, tzinfo=tz)
                        expenses = expenses.filter(expense_date__gte=start, expense_date__lt=end)
                    except (ValueError, TypeError):
                        pass  # Ignore invalid month formats
                else:
                    tz = timezone.get_current_timezone()
                    start = datetime(y, 1, 1, tzinfo=tz)
                    end = datetime(y + 1, 1, 1, tzinfo=tz)  
                    expenses = expenses.filter(expense_date__gte=start, expense_date__lt=end)
            except (ValueError, TypeError):
                pass  # Ignore invalid year formats
        elif not req_year and not req_month:
            current_year = datetime.now().year
            expenses = expenses.filter(expense_date__year=current_year)
            selected_year = str(current_year)

    total_paid = expenses.aggregate(Sum('amount'))['amount__sum'] or 0
    
    grouped_expenses = defaultdict(lambda: {'expenses': [], 'total_amount': 0})
    for expense in expenses:
        if expense.expense_date:
            ym_key = (expense.expense_date.year, expense.expense_date.month)
            grouped_expenses[ym_key]['expenses'].append(expense)
            grouped_expenses[ym_key]['total_amount'] += expense.amount or 0
            
    grouped_expenses = dict(sorted(grouped_expenses.items()))

    context = {
        'expenses': expenses,
        'grouped_expenses': grouped_expenses,
        'employees': all_employees,
        'expense_types': all_expense_types,
        'months': {1:'Январь',2:'Февраль',3:'Март',4:'Апрель',5:'Май',6:'Июнь',
                   7:'Июль',8:'Август',9:'Сентябрь',10:'Октябрь',11:'Ноябрь',12:'Декабрь'},
        'years': years,
        'request': request,
        'selected_year': selected_year,
        'total_paid': total_paid,
    }
    return render(request, 'salary/production_expense_list.html', context)

@login_required
@admin_required
def production_expense_create(request):
    if request.method == 'POST':
        post_data = request.POST.copy()
        if 'amount' in post_data:
            amt = post_data['amount']
            # Remove regular space, no-break space (\u00A0), and narrow no-break space (\u202F)
            amt = amt.replace(' ', '').replace('\xa0', '').replace('\u00a0', '').replace('\u202f', '')
            amt = amt.replace(',', '.')
            post_data['amount'] = amt
        form = ProductionExpenseForm(post_data)
        if form.is_valid():
            expense = form.save(commit=False)
            if not expense.expense_date:
                expense.expense_date = timezone.now()
            expense.save()
            if is_ajax(request):
                return JsonResponse({'success': True})
            messages.success(request, "Расход успешно добавлен.")
            return redirect('production_expense_list')
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = ProductionExpenseForm()
    
    if is_ajax(request):
        return render(request, 'salary/production_expense_form_content.html', {'form': form, 'title': 'Добавить расход'})
    
    return render(request, 'salary/production_expense_form.html', {'form': form, 'title': 'Добавить расход'})

@login_required
@admin_required
def salary_payment_edit(request, pk):
    payment = get_object_or_404(SalaryPayment, pk=pk)
    remaining_salary = None
    if payment.manager:
        remaining_salary = _get_remaining_salary_for_manager(payment.manager.id)

    if request.method == 'POST':
        # Копируем POST и убираем пробелы в сумме
        post_data = request.POST.copy()
        if 'amount' in post_data:
            amt = post_data['amount']
            amt = amt.replace(' ', '').replace('\xa0', '').replace('\u00a0', '').replace('\u202f', '')
            amt = amt.replace(',', '.')
            post_data['amount'] = amt

        form = SalaryPaymentForm(post_data, instance=payment)

        if form.is_valid():
            payment = form.save(commit=False)
            # This line incorrectly updates the payment date on every edit.
            # The date should only be changed if the user explicitly changes it in the form.
            # payment.payment_datetime = timezone.now()
            payment.save()
            if is_ajax(request):
                return JsonResponse({'success': True})
            return redirect('salary_payment_list')
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = SalaryPaymentForm(instance=payment)
        # Отображаем сумму с пробелами (для удобства пользователя)
        if payment.amount is not None:
            form.initial['amount'] = f"{payment.amount:,.2f}".replace(",", " ")
        if payment.payment_datetime:
            form.initial['payment_datetime'] = payment.payment_datetime.strftime('%Y-%m-%dT%H:%M')

    if is_ajax(request):
        return render(request, 'salary/salary_payment_form_content.html', {
            'form': form,
            'payment': payment,
            'action_url': reverse('salary_payment_edit', kwargs={'pk': pk}),
            'title': f'Редактировать выплату №{payment.pk}',
            'remaining_salary': remaining_salary
        })

    return render(request, 'salary/salary_payment_edit.html', {
        'form': form,
        'payment': payment,
        'title': f'Редактировать выплату №{payment.pk}',
        'remaining_salary': remaining_salary
    })

@login_required
@admin_required
def production_expense_edit(request, pk):
    expense = get_object_or_404(ProductionExpense, pk=pk)
    if request.method == 'POST':
        post_data = request.POST.copy()
        if 'amount' in post_data:
            post_data['amount'] = post_data['amount'].replace(' ', '').replace(',', '.')
        form = ProductionExpenseForm(post_data, instance=expense)
        if form.is_valid():
            form.save()
            if is_ajax(request):
                return JsonResponse({'success': True})
            messages.success(request, "Расход успешно обновлен.")
            return redirect('production_expense_list')
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = ProductionExpenseForm(instance=expense)
        if expense.amount is not None:
            form.initial['amount'] = f"{expense.amount:,.2f}".replace(",", " ")

    if is_ajax(request):
        return render(request, 'salary/production_expense_form_content.html', {'form': form, 'title': f'Редактировать расход №{expense.pk}'})

    return render(request, 'salary/production_expense_form.html', {'form': form, 'title': f'Редактировать расход №{expense.pk}'})

@login_required
@admin_required
def export_production_excel(request):
    # Get filter parameters from the request
    employee_id = request.GET.get('employee')
    expense_type_id = request.GET.get('expense_type')
    month = request.GET.get('month')
    year = request.GET.get('year')

    # Base queryset
    expenses = ProductionExpense.objects.select_related('employee', 'expense_type').order_by('-expense_date')

    # Filtering logic (copied from production_expense_list)
    current_year = datetime.now().year
    if year == "":
        selected_year = ""
    elif not year:
        selected_year = str(current_year)
    else:
        selected_year = year

    if selected_year:
        try:
            y = int(selected_year)
            tz = timezone.get_current_timezone()
            if month:
                m = int(month)
                start = datetime(y, m, 1, tzinfo=tz)
                end = datetime(y + 1, 1, 1, tzinfo=tz) if m == 12 else datetime(y, m + 1, 1, tzinfo=tz)
            else:
                start = datetime(y, 1, 1, tzinfo=tz)
                end = datetime(y + 1, 1, 1, tzinfo=tz)
            expenses = expenses.filter(expense_date__gte=start, expense_date__lt=end)
        except (ValueError, TypeError):
            pass
    elif month:
        try:
            m = int(month)
            expenses = expenses.filter(expense_date__month=m)
        except (ValueError, TypeError):
            pass

    if employee_id:
        expenses = expenses.filter(employee_id=employee_id)
    
    if expense_type_id:
        expenses = expenses.filter(expense_type_id=expense_type_id)

    headers = ["Сотрудник", "Вид расходов", "Дата", "Сумма", "Комментарий"]
    title = "Расходы на производство"
    filename_prefix = "Расходы_на_производство"
    column_widths = {1: 25, 2: 25, 3: 20, 4: 18, 5: 50}

    def expense_row_data_extractor(expense):
        return [
            expense.employee.name,
            expense.expense_type.name,
            timezone.localtime(expense.expense_date).strftime("%d.%m.%Y %H:%M"),
            float(expense.amount),
            expense.comment
        ]

    return _generate_excel_response(expenses, headers, title, filename_prefix, expense_row_data_extractor, column_widths)

def _generate_excel_response(queryset, headers, title, filename_prefix, row_data_extractor, column_widths=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title

    header_font = Font(name="Calibri", size=14, bold=True, color="333333")
    thin_border = Border(
        left=Side(style='thin', color="AAAAAA"),
        right=Side(style='thin', color="AAAAAA"),
        top=Side(style='thin', color="AAAAAA"),
        bottom=Side(style='thin', color="AAAAAA")
    )
    header_colors = ["E0E0E0", "D0D0D0", "C0C0C0", "B0B0B0", "A0A0A0"] # Extend as needed

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.font = header_font
        fill_color = header_colors[col_num-1] if col_num-1 < len(header_colors) else "C0C0C0"
        cell.fill = PatternFill("solid", fgColor=fill_color)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    for row_idx, obj in enumerate(queryset, start=2):
        row_data = row_data_extractor(obj)
        fill_color = "EDEDED" if row_idx % 2 == 0 else "FFFFFF"
        
        for col_num, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_num, value=value)
            cell.fill = PatternFill("solid", fgColor=fill_color)
            cell.border = thin_border
            cell.font = Font(name="Calibri", size=14) # Default font size, can be parameterized

            if isinstance(value, (int, float, Decimal)):
                cell.number_format = '# ##0.00'
                cell.alignment = Alignment(horizontal="right")
            elif isinstance(value, datetime):
                cell.number_format = 'DD.MM.YYYY HH:MM'
            
    if column_widths:
        for col_num, width in column_widths.items():
            ws.column_dimensions[get_column_letter(col_num)].width = width
    else:
        for column_cells in ws.columns:
            length = max(len(str(cell.value)) for cell in column_cells)
            ws.column_dimensions[get_column_letter(column_cells[0].column)].width = length + 16

    today_file_str = timezone.localdate().strftime("%d-%m-%Y")
    filename = f"{filename_prefix}_{today_file_str}.xlsx"

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"

    wb.save(response)
    return response

def _get_remaining_salary_for_manager(manager_id):
    """Helper function to calculate remaining salary for a given manager."""
    try:
        manager = BitrixUser.objects.get(id=int(manager_id))
        total_salary = Sale.objects.filter(manager=manager).aggregate(Sum('salary'))['salary__sum'] or 0
        salary_paid = SalaryPayment.objects.filter(manager=manager).aggregate(Sum('amount'))['amount__sum'] or 0
        return total_salary - salary_paid
    except (BitrixUser.DoesNotExist, ValueError, TypeError):
        return None

@login_required
@admin_required
def salary_payment_create(request):
    manager_id = request.POST.get('manager') or request.GET.get('manager')
    remaining_salary = None
    
    if manager_id:
        remaining_salary = _get_remaining_salary_for_manager(manager_id)

    if request.method == 'POST':
        # Копируем POST и убираем пробелы в сумме
        post_data = request.POST.copy()
        if 'amount' in post_data:
            amt = post_data['amount']
            amt = amt.replace(' ', '').replace('\xa0', '').replace('\u00a0', '').replace('\u202f', '')
            amt = amt.replace(',', '.')
            post_data['amount'] = amt

        form = SalaryPaymentForm(post_data)
        if form.is_valid():
            payment = form.save(commit=False)
            # Если поле payment_datetime пустое, ставим текущее время
            if not payment.payment_datetime:
                payment.payment_datetime = timezone.now()
            payment.save()
            if is_ajax(request):
                return JsonResponse({'success': True})
            return redirect('salary_payment_list')
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        initial_data = {'payment_datetime': timezone.now().strftime('%Y-%m-%dT%H:%M')}
        if manager_id:
            initial_data['manager'] = manager_id
        form = SalaryPaymentForm(initial=initial_data)

    if is_ajax(request):
        return render(request, 'salary/salary_payment_form_content.html', {
            'form': form,
            'remaining_salary': remaining_salary,
            'action_url': reverse('salary_payment_create'),
            'title': 'Добавить выплату'
        })

    return render(request, 'salary/salary_payment_form.html', {
        'form': form,
        'remaining_salary': remaining_salary,
        'title': 'Добавить выплату'
    })


@require_GET
def get_remaining_salary(request):
    manager_id = request.GET.get('manager_id')
    remaining_salary = _get_remaining_salary_for_manager(manager_id)
    if remaining_salary is not None:
        return JsonResponse({"remaining_salary": f"{remaining_salary:.2f}"})
    else:
        return JsonResponse({"remaining_salary": "0.00"})

@login_required
@admin_required
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            employee = form.save()
            if is_ajax(request):
                return JsonResponse({'success': True, 'id': employee.id, 'name': employee.name})
            messages.success(request, f"Сотрудник '{form.cleaned_data['name']}' успешно добавлен.")
            return redirect('production_expense_list')
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = EmployeeForm()
    
    if is_ajax(request):
        return render(request, 'salary/simple_form_content.html', {'form': form, 'title': 'Добавить сотрудника', 'action_url': reverse('employee_create')})
    
    return render(request, 'salary/simple_form.html', {'form': form, 'title': 'Добавить сотрудника'})

@login_required
@admin_required
def expense_type_create(request):
    if request.method == 'POST':
        form = ExpenseTypeForm(request.POST)
        if form.is_valid():
            expense_type = form.save()
            if is_ajax(request):
                return JsonResponse({'success': True, 'id': expense_type.id, 'name': expense_type.name})
            messages.success(request, f"Вид расходов '{form.cleaned_data['name']}' успешно добавлен.")
            return redirect('production_expense_list')
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = ExpenseTypeForm()

    if is_ajax(request):
        return render(request, 'salary/simple_form_content.html', {'form': form, 'title': 'Добавить вид расходов', 'action_url': reverse('expense_type_create')})

    return render(request, 'salary/simple_form.html', {'form': form, 'title': 'Добавить вид расходов'})


@login_required
@admin_required
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            if is_ajax(request):
                return JsonResponse({'success': True})
            messages.success(request, "Сотрудник успешно обновлен.")
            return redirect('production_expense_list')
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = EmployeeForm(instance=employee)

    if is_ajax(request):
        return render(request, 'salary/simple_form_content.html', {'form': form, 'title': f'Редактировать сотрудника'})

    return render(request, 'salary/simple_form.html', {'form': form, 'title': f'Редактировать сотрудника'})


@login_required
@admin_required  
def register(request):
    manager_id = request.GET.get('manager_id')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            if is_ajax(request):
                return JsonResponse({'success': True})
            messages.success(request, "Пользователь успешно зарегистрирован.")
            return redirect("users_list")
        else:
            if is_ajax(request):
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        # Если есть manager_id - подставим в начальные данные формы
        initial_data = {}
        if manager_id:
            initial_data['manager'] = manager_id
        form = RegistrationForm(initial=initial_data)

    if is_ajax(request):
        return render(request, "salary/register_form_content.html", {"form": form, 'action_url': reverse('register')})

    return render(request, "salary/register.html", {"form": form})


@login_required
@admin_required
def users_list(request):
    users = BitrixUser.objects.select_related('django_user').all()
    return render(request, 'salary/users_list.html', {'users': users})


@login_required
@admin_required
def delete_user_account(request, manager_id):
    manager = get_object_or_404(BitrixUser, id=manager_id)
    if manager.django_user:
        # Удаляем связанного пользователя django (логин и пароль)
        # The on_delete=models.SET_NULL on the User.django_user field
        # automatically handles setting the field to None.
        manager.django_user.delete()

        messages.success(request, f"У пользователя {manager.last_name} {manager.name} удалены логин и пароль.")
    else:
        messages.warning(request, "У этого менеджера нет зарегистрированного пользователя.")
    return redirect('users_list')

def register_with_manager(request, manager_id):
    """
    Переходим на страницу регистрации, передавая id менеджера.
    На странице регистрации этот id можно использовать, чтобы
    привязать создаваемого django_user к выбранному менеджеру.
    """
    return redirect(f"/register?manager_id={manager_id}")


# AI Analysis views
ai_analysis_view = ai_views.ai_analysis_view
ai_analyze_data = ai_views.ai_analyze_data
ai_generate_chart = ai_views.ai_generate_chart
ai_check_model_status = ai_views.ai_check_model_status
