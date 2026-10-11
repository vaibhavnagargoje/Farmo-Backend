"""App control pages: app status (maintenance + versions), announcements, broadcasts.

Anyone with panel access can view these pages. Only Admin and Super Admin
can change anything (see permissions.can_manage_app_control).
"""

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from appcontrol import broadcast as broadcasts
from appcontrol.models import Announcement, AppControl, AppRelease, Audience, Broadcast
from notifications.models import DeviceToken

from ..forms.app_control import AnnouncementForm, BroadcastForm, MaintenanceForm, ReleaseForm
from ..permissions import can_manage_app_control, is_agent

LOGIN_URL = "/api/v1/admin/login/"
PAGE_SIZE = 25
NOT_ALLOWED = "Only Admin and Super Admin can change App control settings."
AUDIENCE_NOUNS = {Audience.ALL: 'people', Audience.FARMERS: 'farmers', Audience.PROVIDERS: 'providers'}


def _page_context(request, **extra):
    return {"can_manage": can_manage_app_control(request.user), **extra}


def release_summary(release):
    """One line describing what each build of this platform sees."""
    if not release.latest_build:
        return "Not set up yet. Nobody sees an update prompt."
    parts = []
    if release.min_supported_build:
        parts.append(f"Builds below {release.min_supported_build} must update.")
    else:
        parts.append("Nobody is forced to update.")
    soft_from = release.min_supported_build or 0
    if release.soft_update_enabled and release.latest_build > soft_from:
        lowest = max(soft_from, 1)
        if lowest == release.latest_build - 1:
            parts.append(f"Build {lowest} is offered the update.")
        elif lowest < release.latest_build:
            parts.append(f"Builds {lowest} to {release.latest_build - 1} are offered the update.")
    return " ".join(parts)


# ── App status: maintenance and versions ────────────────────────────────────

@user_passes_test(is_agent, login_url=LOGIN_URL)
def app_status(request):
    control = AppControl.get()
    releases = {platform: AppRelease.for_platform(platform) for platform in AppRelease.Platform.values}
    forms = {
        'maintenance': MaintenanceForm(instance=control),
        **{p: ReleaseForm(instance=r, prefix=p) for p, r in releases.items()},
    }

    if request.method == 'POST':
        if not can_manage_app_control(request.user):
            return HttpResponseForbidden(NOT_ALLOWED)
        section = request.POST.get('section')
        if section == 'maintenance':
            form = MaintenanceForm(request.POST, instance=control)
        elif section in releases:
            form = ReleaseForm(request.POST, instance=releases[section], prefix=section)
        else:
            return HttpResponseBadRequest("Unknown section.")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            if section == 'maintenance':
                if obj.maintenance_on:
                    messages.warning(request, "Maintenance is ON. The app shows the maintenance screen to everyone.")
                else:
                    messages.success(request, "Maintenance is off. The app works normally.")
            else:
                messages.success(request, f"{obj.get_platform_display()} versions saved. {release_summary(obj)}")
            return redirect('adminpanel:app-control')
        forms[section] = form
        messages.error(request, "Please fix the highlighted fields.")

    return render(request, 'adminpanel/app_control/status.html', _page_context(
        request,
        page_title="App control",
        control=control,
        maintenance_form=forms['maintenance'],
        release_cards=[
            {'release': r, 'form': forms[p], 'summary': release_summary(r)} for p, r in releases.items()
        ],
    ))


# ── Announcements ───────────────────────────────────────────────────────────

ANNOUNCEMENT_FILTERS = [('', 'All'), ('live', 'Live'), ('scheduled', 'Scheduled'), ('ended', 'Ended'), ('off', 'Off')]


@user_passes_test(is_agent, login_url=LOGIN_URL)
def announcements_list(request):
    now = timezone.now()
    state = request.GET.get('state', '')
    qs = Announcement.objects.select_related('created_by').order_by('-created_at')
    if state == 'live':
        qs = qs.filter(is_active=True, starts_at__lte=now).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
    elif state == 'scheduled':
        qs = qs.filter(is_active=True, starts_at__gt=now)
    elif state == 'ended':
        qs = qs.filter(is_active=True, ends_at__lte=now)
    elif state == 'off':
        qs = qs.filter(is_active=False)
    else:
        state = ''
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    rows = [{'item': a, 'state': a.state(now)} for a in page_obj]
    return render(request, 'adminpanel/app_control/announcements_list.html', _page_context(
        request, page_title="Announcements", page_obj=page_obj, rows=rows,
        filters=ANNOUNCEMENT_FILTERS, state=state,
    ))


@user_passes_test(is_agent, login_url=LOGIN_URL)
def announcement_edit(request, pk=None):
    announcement = get_object_or_404(Announcement, pk=pk) if pk else None
    if request.method == 'POST':
        if not can_manage_app_control(request.user):
            return HttpResponseForbidden(NOT_ALLOWED)
        form = AnnouncementForm(request.POST, request.FILES, instance=announcement)
        if form.is_valid():
            obj = form.save(commit=False)
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            messages.success(request, f'Announcement "{obj.title}" saved. It is {obj.state()} now.')
            return redirect('adminpanel:app-announcements')
        messages.error(request, "Please fix the highlighted fields.")
    else:
        form = AnnouncementForm(instance=announcement)
    return render(request, 'adminpanel/app_control/announcement_form.html', _page_context(
        request, page_title="Edit announcement" if announcement else "New announcement",
        form=form, announcement=announcement,
    ))


@require_POST
@user_passes_test(is_agent, login_url=LOGIN_URL)
def announcement_toggle(request, pk):
    if not can_manage_app_control(request.user):
        return HttpResponseForbidden(NOT_ALLOWED)
    announcement = get_object_or_404(Announcement, pk=pk)
    announcement.is_active = not announcement.is_active
    announcement.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'"{announcement.title}" is now {"on" if announcement.is_active else "off"}.')
    return redirect(request.POST.get('next') or 'adminpanel:app-announcements')


@require_POST
@user_passes_test(is_agent, login_url=LOGIN_URL)
def announcement_delete(request, pk):
    if not can_manage_app_control(request.user):
        return HttpResponseForbidden(NOT_ALLOWED)
    announcement = get_object_or_404(Announcement, pk=pk)
    title = announcement.title
    announcement.delete()
    messages.success(request, f'Announcement "{title}" deleted.')
    return redirect('adminpanel:app-announcements')


# ── Broadcasts ──────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url=LOGIN_URL)
def broadcasts_list(request):
    qs = Broadcast.objects.select_related('created_by').order_by('-created_at')
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'adminpanel/app_control/broadcasts_list.html', _page_context(
        request, page_title="Broadcasts", page_obj=page_obj,
    ))


@user_passes_test(is_agent, login_url=LOGIN_URL)
def broadcast_edit(request, pk=None):
    item = get_object_or_404(Broadcast, pk=pk) if pk else None
    if item and item.status != Broadcast.Status.DRAFT:
        messages.info(request, "This broadcast has been sent and can no longer be edited.")
        return redirect('adminpanel:app-broadcast-detail', pk=item.pk)
    if request.method == 'POST':
        if not can_manage_app_control(request.user):
            return HttpResponseForbidden(NOT_ALLOWED)
        form = BroadcastForm(request.POST, instance=item)
        if form.is_valid():
            obj = form.save(commit=False)
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            return redirect('adminpanel:app-broadcast-detail', pk=obj.pk)
        messages.error(request, "Please fix the highlighted fields.")
    else:
        form = BroadcastForm(instance=item)
    return render(request, 'adminpanel/app_control/broadcast_form.html', _page_context(
        request, page_title="Edit broadcast" if item else "New broadcast", form=form, broadcast=item,
    ))


@user_passes_test(is_agent, login_url=LOGIN_URL)
def broadcast_detail(request, pk):
    item = get_object_or_404(Broadcast.objects.select_related('created_by'), pk=pk)
    audience = broadcasts.recipients(item.audience)
    translations = [
        (language, item.title_translations.get(code, ''), item.message_translations.get(code, ''))
        for code, language in (('hi', 'Hindi'), ('mr', 'Marathi'))
    ]
    return render(request, 'adminpanel/app_control/broadcast_detail.html', _page_context(
        request, page_title=f"Broadcast: {item.title}", broadcast=item,
        recipient_count=audience.count(),
        device_count=DeviceToken.objects.filter(user__in=audience).count(),
        audience_noun=AUDIENCE_NOUNS.get(item.audience, 'people'),
        translations=translations,
        refresh=item.status == Broadcast.Status.SENDING,
    ))


@require_POST
@user_passes_test(is_agent, login_url=LOGIN_URL)
def broadcast_send(request, pk):
    if not can_manage_app_control(request.user):
        return HttpResponseForbidden(NOT_ALLOWED)
    item = get_object_or_404(Broadcast, pk=pk)
    try:
        broadcasts.start(item)
    except broadcasts.BroadcastError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Sending started. This page updates until it is done.")
    return redirect('adminpanel:app-broadcast-detail', pk=item.pk)
