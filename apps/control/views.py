import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.dj.permissions import ADMIN_GROUP, DJ_GROUP
from apps.events.forms import EventForm
from apps.events.models import Event
from apps.songs.models import ExperienceRating, Guest, LimitReset, SongRating, SongRequest
from apps.songs.services import limits_for, requests_counted_for_limit, reset_limit
from apps.venues.models import Venue

from .forms import StaffCreateForm, StaffEditForm, StaffPasswordForm, VenueForm, apply_role, role_of
from .permissions import admin_required


def songs_word(n):
    return "canción" if n == 1 else "canciones"


def _ctx(tab, **extra):
    return {"control_tab": tab, **extra}


# --- Resumen ---------------------------------------------------------------

@admin_required
def dashboard(request):
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    songs = SongRequest.objects.all()
    status = songs.aggregate(
        pending=Count("id", filter=Q(status=SongRequest.Status.PENDING)),
        played=Count("id", filter=Q(status=SongRequest.Status.PLAYED)),
        rejected=Count("id", filter=Q(status=SongRequest.Status.REJECTED)),
        today=Count("id", filter=Q(created_at__gte=today_start)),
        week=Count("id", filter=Q(created_at__gte=now - timedelta(days=7))),
    )
    staff = User.objects.filter(Q(groups__name__in=[DJ_GROUP, ADMIN_GROUP]) | Q(is_superuser=True)).distinct()
    kpis = {
        **status,
        "total": songs.count(),
        "guests": Guest.objects.count(),
        "guests_today": Guest.objects.filter(created_at__gte=today_start).count(),
        "google": Guest.objects.exclude(google_sub=None).count(),
        "djs": staff.filter(groups__name=DJ_GROUP).count(),
        "admins": staff.exclude(groups__name=DJ_GROUP).count(),
        "events_open": Event.objects.filter(is_open=True).count(),
        "venues": Venue.objects.filter(is_active=True).count(),
        "votes": SongRating.objects.count(),
    }

    top_songs = list(
        songs.values("title_key", "artist_key")
        .annotate(n=Count("id"), title=Max("title"), artist=Max("artist"))
        .order_by("-n", "title")[:6]
    )
    genre_labels = dict(SongRequest.Genre.choices)
    top_genres = [
        {"label": genre_labels.get(g["genre"], g["genre"]), "n": g["n"]}
        for g in songs.values("genre").annotate(n=Count("id")).order_by("-n")[:6]
    ]
    top_people = Guest.objects.annotate(n=Count("requests")).filter(n__gt=0).order_by("-n")[:6]
    for rows in (top_songs, top_genres):
        peak = max((r["n"] for r in rows), default=1)
        for r in rows:
            r["pct"] = round(r["n"] * 100 / peak)
    recent = songs.select_related("guest", "venue", "event").order_by("-created_at")[:10]
    kpis["ratings"] = ExperienceRating.objects.count()
    ratings = {
        "venues": Venue.objects.annotate(avg=Avg("experience_ratings__venue_stars"), n=Count("experience_ratings"))
                  .filter(n__gt=0).order_by("-avg", "-n")[:8],
        "events": Event.objects.select_related("venue").annotate(
                  avg=Avg("experience_ratings__event_stars"), n=Count("experience_ratings__event_stars"))
                  .filter(n__gt=0).order_by("-avg", "-n")[:8],
        "djs": User.objects.annotate(avg=Avg("experience_ratings__dj_stars"), n=Count("experience_ratings__dj_stars"))
               .filter(n__gt=0).order_by("-avg", "-n")[:8],
    }
    return render(request, "control/dashboard.html", _ctx(
        "dashboard", kpis=kpis, top_songs=top_songs, top_genres=top_genres, top_people=top_people, recent=recent,
        ratings=ratings,
    ))


# --- Usuarios DJ y Admin ---------------------------------------------------

@admin_required
def staff_list(request):
    form = StaffCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"Usuario «{user.username}» creado como {dict(form.fields['role'].choices)[form.cleaned_data['role']]}.")
        return redirect("control:staff")
    users = (
        User.objects.filter(Q(groups__name__in=[DJ_GROUP, ADMIN_GROUP]) | Q(is_superuser=True) | Q(is_staff=True))
        .distinct().annotate(handled=Count("handled_requests", distinct=True), events_n=Count("events", distinct=True))
        .order_by("-is_active", "username")
    )
    rows = [{"user": u, "role": role_of(u)} for u in users]
    return render(request, "control/staff_list.html", _ctx("staff", form=form, rows=rows))


@admin_required
def staff_edit(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    is_self = target == request.user
    form = StaffEditForm(request.POST or None, initial={
        "first_name": target.first_name, "role": role_of(target), "is_active": target.is_active,
    })
    pass_form = StaffPasswordForm(user=target)
    if request.method == "POST" and form.is_valid():
        role, active = form.cleaned_data["role"], form.cleaned_data["is_active"]
        if is_self and (role != "admin" or not active):
            messages.error(request, "No puedes quitarte el rol de Admin ni desactivar tu propia cuenta.")
        elif target.is_superuser and role != "admin":
            messages.error(request, "El superusuario siempre es Admin.")
        else:
            target.first_name = form.cleaned_data["first_name"]
            target.is_active = active
            target.save()
            apply_role(target, role)
            messages.success(request, "Usuario actualizado.")
            return redirect("control:staff")
    return render(request, "control/staff_edit.html", _ctx(
        "staff", target=target, form=form, pass_form=pass_form, is_self=is_self, role=role_of(target),
    ))


@require_POST
@admin_required
def staff_password(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    form = StaffPasswordForm(request.POST, user=target)
    if form.is_valid():
        target.set_password(form.cleaned_data["password1"])
        target.save()
        messages.success(request, f"Contraseña de «{target.username}» actualizada.")
        return redirect("control:staff")
    edit_form = StaffEditForm(initial={"first_name": target.first_name, "role": role_of(target), "is_active": target.is_active})
    return render(request, "control/staff_edit.html", _ctx(
        "staff", target=target, form=edit_form, pass_form=form, is_self=target == request.user, role=role_of(target),
    ))


# --- Personas que piden canciones -------------------------------------------

def _people_queryset(request):
    query = request.GET.get("q", "").strip()
    people = Guest.objects.annotate(
        n=Count("requests", distinct=True), last=Max("requests__created_at"),
        played=Count("requests", filter=Q(requests__status=SongRequest.Status.PLAYED), distinct=True),
    )
    if query:
        people = people.filter(
            Q(email__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query)
            | Q(alias__icontains=query) | Q(phone__icontains=query)
        )
    order = {"recientes": "-created_at", "pedidos": "-n", "nombre": "first_name"}.get(request.GET.get("orden"), "-last")
    return people.order_by(order, "-created_at"), query


@admin_required
def people_list(request):
    people, query = _people_queryset(request)
    page = Paginator(people, 50).get_page(request.GET.get("pagina"))
    return render(request, "control/people_list.html", _ctx(
        "people", page=page, query=query, orden=request.GET.get("orden", ""), total=people.count(),
    ))


@admin_required
def people_export(request):
    people, _ = _people_queryset(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="personas-cronso-dplay.csv"'
    response.write("﻿")  # BOM para que Excel abra bien las tildes
    writer = csv.writer(response)
    writer.writerow(["Nombres", "Apellidos", "Alias", "Correo", "Celular", "Google", "Canciones", "Sonaron",
                     "Último pedido", "Registrado"])
    fmt = lambda d: timezone.localtime(d).strftime("%Y-%m-%d %H:%M") if d else ""
    for g in people:
        writer.writerow([g.first_name, g.last_name, g.alias, g.email, g.phone, "sí" if g.google_sub else "no",
                         g.n, g.played, fmt(g.last), fmt(g.created_at)])
    return response


@admin_required
def person_detail(request, guest_id):
    guest = get_object_or_404(Guest, pk=guest_id)
    scopes = []
    for event in [None, *Event.objects.filter(is_open=True).select_related("venue")]:
        per_person, _ = limits_for(event)
        used = requests_counted_for_limit(guest, event)
        if used or event is not None:
            scopes.append({"event": event, "used": used, "max": per_person, "remaining": max(per_person - used, 0)})
    songs = guest.requests.select_related("venue", "event", "handled_by").order_by("-created_at")
    return render(request, "control/person_detail.html", _ctx(
        "people", guest=guest, scopes=scopes, songs=songs, resets=guest.limit_resets.select_related("event", "reset_by")[:10],
    ))


@require_POST
@admin_required
def person_reset(request, guest_id):
    guest = get_object_or_404(Guest, pk=guest_id)
    code = request.POST.get("evento", "")
    event = Event.objects.filter(code=code).first() if code else None
    released = reset_limit(guest, request.user, event)
    messages.success(request, f"Cupo restablecido ({released} pedido{'s' if released != 1 else ''} liberado{'s' if released != 1 else ''}).")
    return redirect("control:person", guest_id=guest.pk)


@require_POST
@admin_required
def person_delete(request, guest_id):
    guest = get_object_or_404(Guest, pk=guest_id)
    if request.POST.get("confirmar") != guest.email:
        messages.error(request, "Para eliminar, escribe el correo exacto de la persona.")
        return redirect("control:person", guest_id=guest.pk)
    name, songs = guest.display_name, guest.requests.count()
    guest.delete()  # elimina también sus canciones y restablecimientos
    messages.success(request, f"Se eliminó a {name} y sus {songs} {songs_word(songs)}.")
    return redirect("control:people")


# --- Eventos: reiniciar playlist --------------------------------------------

@admin_required
def events(request):
    form = EventForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.dj = request.user
        event.save()
        messages.success(request, f"Evento «{event.name}» creado. Código {event.code}.")
        return redirect("control:events")
    rows = Event.objects.select_related("venue", "dj").annotate(
        songs=Count("requests", distinct=True),
        pending=Count("requests", filter=Q(requests__status=SongRequest.Status.PENDING), distinct=True),
        people=Count("requests__guest", distinct=True),
        rating=Avg("experience_ratings__event_stars"), rating_n=Count("experience_ratings__event_stars", distinct=True),
    ).order_by("-is_open", "-created_at")
    selected = request.GET.get("evento", "")
    return render(request, "control/events.html", _ctx("events", rows=rows, selected=selected, form=form))


@admin_required
def event_edit(request, code):
    event = get_object_or_404(Event.objects.select_related("venue"), code=code.upper())
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Evento «{event.name}» actualizado.")
        return redirect("control:events")
    stats = event.requests.aggregate(total=Count("id"), people=Count("guest", distinct=True))
    return render(request, "control/event_edit.html", _ctx("events", event=event, form=form, stats=stats))


@require_POST
@admin_required
def event_toggle(request, code):
    event = get_object_or_404(Event, code=code.upper())
    event.is_open = not event.is_open
    event.closed_at = None if event.is_open else timezone.now()
    event.save(update_fields=["is_open", "closed_at"])
    messages.success(request, f"Evento «{event.name}» {'abierto' if event.is_open else 'cerrado'}.")
    back = request.POST.get("volver", "")
    if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        return redirect(back)
    return redirect("control:events")


@require_POST
@admin_required
def event_delete(request, code):
    """Elimina el evento y sus canciones (no quedan como "pedidos sin evento" sumando cupos)."""
    event = get_object_or_404(Event, code=code.upper())
    if request.POST.get("confirmar", "").strip().upper() != event.code:
        messages.error(request, f"Para eliminar «{event.name}» escribe su código exacto: {event.code}.")
        return redirect("control:event_edit", code=event.code)
    with transaction.atomic():
        songs = event.requests.count()
        event.requests.all().delete()
        event.delete()
    messages.success(request, f"Evento «{event.name}» eliminado junto con sus {songs} {songs_word(songs)}.")
    return redirect("control:events")


@require_POST
@admin_required
def event_reset(request):
    """
    Reinicia la playlist de un evento: borra todas sus canciones (y con ellas sus votos)
    y los restablecimientos de cupo del evento. El evento, su link y su QR se conservan.
    """
    event = Event.objects.filter(code=request.POST.get("evento", "").upper()).first()
    if event is None:
        messages.error(request, "Elige el evento que quieres reiniciar.")
        return redirect("control:events")
    if request.POST.get("confirmar", "").strip().upper() != event.code:
        messages.error(request, f"Para reiniciar «{event.name}» escribe su código exacto: {event.code}.")
        return redirect(f"{reverse('control:events')}?evento={event.code}")
    with transaction.atomic():
        songs = SongRequest.objects.filter(event=event)
        votes = SongRating.objects.filter(song__event=event).count()
        total, people = songs.count(), songs.values("guest").distinct().count()
        songs.delete()  # los votos se borran en cascada
        LimitReset.objects.filter(event=event).delete()
    messages.success(
        request,
        f"Playlist de «{event.name}» reiniciada: {total} {songs_word(total)} y {votes} voto{'s' if votes != 1 else ''} "
        f"eliminados. {people} persona{'s' if people != 1 else ''} vuelve{'n' if people != 1 else ''} a tener su cupo completo.",
    )
    return redirect("control:events")


# --- Discotecas ------------------------------------------------------------

@admin_required
def venues(request):
    form = VenueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        venue = form.save()
        messages.success(request, f"Discoteca «{venue.name}» creada.")
        return redirect("control:venues")
    rows = Venue.objects.annotate(songs=Count("requests", distinct=True), events_n=Count("events", distinct=True)).order_by("-is_active", "name")
    return render(request, "control/venues.html", _ctx("venues", form=form, rows=rows))


@require_POST
@admin_required
def venue_toggle(request, venue_id):
    venue = get_object_or_404(Venue, pk=venue_id)
    venue.is_active = not venue.is_active
    venue.save(update_fields=["is_active"])
    messages.success(request, f"«{venue.name}» {'activada' if venue.is_active else 'desactivada'}.")
    return redirect("control:venues")
