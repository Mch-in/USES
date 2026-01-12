from django.urls import path
from . import views
from . import ai_views
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("", views.sales_list, name='sales_list'),
    path("index/", views.index, name="index"),
    path('salary_payments/', views.salary_payment_list, name='salary_payment_list'),
    path('production/', views.production_expense_list, name='production_expense_list'),
    path('production/new/', views.production_expense_create, name='production_expense_create'),
    path('production/<int:pk>/edit/', views.production_expense_edit, name='production_expense_edit'),
    path('production/export_excel/', views.export_production_excel, name='export_production_excel'),
    path('employees/new/', views.employee_create, name='employee_create'),
    path('expense_types/new/', views.expense_type_create, name='expense_type_create'),
    path('salary_payments/new/', views.salary_payment_create, name='salary_payment_create'),
    path('salary/payment/<int:pk>/edit/', views.salary_payment_edit, name='salary_payment_edit'),
    path('login/', auth_views.LoginView.as_view(template_name='salary/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('export_salary_excel/', views.export_salary_excel, name='export_salary_excel'),
    path("register/", views.register, name="register"),
    path('users/', views.users_list, name='users_list'),
    path('users/delete/<int:manager_id>/', views.delete_user_account, name='delete_user_account'),
    path('users/add/<int:manager_id>/', views.register_with_manager, name='register_with_manager'),
    # ✅ Новый маршрут
    path('get-remaining-salary/', views.get_remaining_salary, name='get_remaining_salary'),
    # AI Analysis routes
    path('ai-analysis/', ai_views.ai_analysis_view, name='ai_analysis'),
    path('api/ai/analyze/', ai_views.ai_analyze_data, name='ai_analyze_data'),
    path('api/ai/generate-chart/', ai_views.ai_generate_chart, name='ai_generate_chart'),
    path('api/ai/generate-insights/', ai_views.ai_generate_insights, name='ai_generate_insights'),
    path('api/ai/status/', ai_views.ai_check_model_status, name='ai_check_model_status'),
    path('api/ai/csrf-token/', ai_views.get_csrf_token, name='get_csrf_token'),
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 