from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext as _
from functools import wraps
from .models import CrmUser

def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            current_user = CrmUser.objects.get(django_user=request.user)
            if not current_user.is_admin:
                messages.error(request, _("You do not have permission to access this page."))
                return redirect('sales_list')
        except CrmUser.DoesNotExist:
            messages.error(request, _("You do not have permission to access this page."))
            return redirect('sales_list')
        return view_func(request, *args, **kwargs)
    return wrapper