from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


@login_required
def dashboard(request):
    return render(request, "core/dashboard.html")


def healthz(request):
    connection.ensure_connection()
    return JsonResponse({"ok": True})
