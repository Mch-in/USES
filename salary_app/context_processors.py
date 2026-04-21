from .utils import get_current_crm_user


def global_user_context(request):
    current_user, is_admin = get_current_crm_user(request)
    return {
        'current_user': current_user,
        'is_admin': is_admin
    }