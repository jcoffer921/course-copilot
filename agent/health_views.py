from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .services import operations


@require_GET
def health(request):
    snapshot, ready = operations.health_snapshot()
    return JsonResponse(snapshot, status=200 if ready else 503)
