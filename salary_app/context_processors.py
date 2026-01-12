from .models import BitrixUser

def global_user_context(request):
    if request.user.is_authenticated:
        try:
            current_user = BitrixUser.objects.get(django_user=request.user)
            is_admin = current_user.is_admin
        except BitrixUser.DoesNotExist:
            current_user = None
            is_admin = False
    else:
        current_user = None
        is_admin = False

    return {
        'current_user': current_user,
        'is_admin': is_admin
    }