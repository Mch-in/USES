from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from .models import BitrixUser

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            current_user = BitrixUser.objects.get(django_user=request.user)
            if not current_user.is_admin:
                messages.error(request, "У вас нет прав для доступа к этой странице.")
                return redirect('sales_list')
        except BitrixUser.DoesNotExist:
            messages.error(request, "У вас нет прав для доступа к этой странице.")
            return redirect('sales_list')
        return view_func(request, *args, **kwargs)
    return wrapper