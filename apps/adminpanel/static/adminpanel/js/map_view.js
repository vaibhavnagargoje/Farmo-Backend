/** Farmo dispatch map: server candidates and fresh message drafts are authoritative. */
let map = null, PARTNERS = [], BOOKINGS = [], CSRF_TOKEN = '';
let partnerMarkers = [], partnerCircles = [], bookingMarkers = [], bookingBeacons = [];
let circlesVisible = true, bookingsVisible = true, offlinePartnersVisible = true, queueSidebarVisible = true;
let currentQueueTab = 'pending', queueSearchQuery = '', selectedBookingId = null, selectedPartnerId = null;
let comparisonLine = null, activeHighlightedCircle = null, hoverWindow = null;
let BeaconOverlay, refreshInFlight = false, draftSequence = 0, lastDialogFocus = null, otherPartnersOpen = false;
const visiblePartnerCounts = { matched: 8, other: 8 };
const selectedServices = new Map();

function openStatsModal() {
    const dialog = document.getElementById('statsModalDialog');
    if (dialog && !dialog.open) {
        lastDialogFocus = document.activeElement;
        dialog.showModal();
    }
}
function closeStatsModal() {
    const dialog = document.getElementById('statsModalDialog');
    if (dialog && dialog.open) {
        dialog.close();
        if (lastDialogFocus?.isConnected) lastDialogFocus.focus({ preventScroll: true });
    }
}
window.openStatsModal = openStatsModal;
window.closeStatsModal = closeStatsModal;

function updateCategoryBadgesAndSorting(counts, totalActive) {
    const allBadge = document.getElementById('allActiveBadge');
    if (allBadge) {
        allBadge.textContent = String(totalActive || 0);
        allBadge.hidden = !totalActive;
    }
    const bar = document.getElementById('categoryBar');
    if (!bar) return;
    const categoryCards = Array.from(bar.querySelectorAll('.category-card'));
    categoryCards.forEach(card => {
        const id = card.dataset.categoryId;
        const count = (counts && id && counts[id]) ? Number(counts[id]) : 0;
        card.dataset.count = String(count);
        let badge = card.querySelector('.category-count-badge');
        if (count > 0) {
            if (!badge) {
                badge = node('span', 'category-count-badge absolute -top-1 -right-1 min-w-[18px] h-[18px] flex items-center justify-center bg-amber-500 text-white text-[10px] font-bold rounded-full px-1 shadow-sm ring-2 ring-white z-10 pulse-badge');
                card.appendChild(badge);
            }
            badge.textContent = String(count);
            badge.hidden = false;
            card.classList.add('bg-amber-50/40', 'border-amber-200/80');
        } else {
            if (badge) badge.hidden = true;
            if (!card.classList.contains('ring-1')) {
                card.classList.remove('bg-amber-50/40', 'border-amber-200/80');
            }
        }
    });
    categoryCards.sort((a, b) => {
        const countA = Number(a.dataset.count || 0);
        const countB = Number(b.dataset.count || 0);
        if (countB !== countA) return countB - countA;
        return (a.dataset.name || '').localeCompare(b.dataset.name || '');
    });
    categoryCards.forEach(card => bar.appendChild(card));
    const allCard = document.getElementById('allCategoryCard');
    if (allCard) bar.appendChild(allCard);
}

function renderOtpCard(label, code, hint, isPrimary = false) {
    const card = node('div', `map-otp-card ${isPrimary ? 'is-primary' : ''}`);
    const top = node('div', 'flex items-center justify-between');
    top.append(node('span', 'map-otp-label', label));
    const copyBtn = node('button', 'map-otp-copy-btn', 'Copy');
    copyBtn.type = 'button';
    copyBtn.title = 'Copy OTP code';
    copyBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(code);
            } else {
                const ta = document.createElement('textarea');
                ta.value = code;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                ta.remove();
            }
            copyBtn.textContent = 'Copied ✓';
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
        } catch (_) {
            copyBtn.textContent = code;
        }
    });
    top.append(copyBtn);
    card.append(top);
    const codeEl = node('div', 'map-otp-code', code);
    card.append(codeEl);
    if (hint) {
        card.append(node('span', 'map-otp-hint', hint));
    }
    return card;
}

let cancelTargetBooking = null;
function openCancelDialog(booking) {
    cancelTargetBooking = booking;
    const dialog = document.getElementById('cancelBookingDialog');
    if (!dialog) return;
    document.getElementById('cancelBookingTargetId').value = booking.booking_id;
    setText('cancelBookingIdLabel', '#' + booking.booking_id);
    setText('cancelBookingCustomerLabel', booking.customer_name || 'Customer');
    setText('cancelBookingServiceLabel', booking.service_name || booking.category_name || 'Order');
    const select = document.getElementById('cancelReasonPreset');
    if (select) select.selectedIndex = 0;
    const customWrap = document.getElementById('cancelCustomReasonWrap');
    if (customWrap) customWrap.hidden = true;
    const customInput = document.getElementById('cancelCustomReason');
    if (customInput) customInput.value = '';
    dialog.showModal();
}
function closeCancelDialog() {
    document.getElementById('cancelBookingDialog')?.close();
    cancelTargetBooking = null;
}
function handleCancelReasonPresetChange(val) {
    const customWrap = document.getElementById('cancelCustomReasonWrap');
    if (customWrap) customWrap.hidden = (val !== 'custom');
    if (val === 'custom') document.getElementById('cancelCustomReason')?.focus();
}
async function submitCancelBooking() {
    const btn = document.getElementById('cancelConfirmSubmitBtn');
    const bookingId = document.getElementById('cancelBookingTargetId')?.value;
    if (!bookingId) return;
    const preset = document.getElementById('cancelReasonPreset')?.value;
    const customText = document.getElementById('cancelCustomReason')?.value?.trim();
    const reason = (preset === 'custom' ? customText : preset) || 'Cancelled by admin from dispatch map';
    if (preset === 'custom' && !customText) {
        alert('Please specify the cancellation reason.');
        return;
    }
    btn.disabled = true;
    btn.textContent = 'Cancelling…';
    const form = new FormData();
    form.append('booking_id', bookingId);
    form.append('reason', reason);
    try {
        const data = await readJson(await fetch(endpoint('cancelUrl', '/api/v1/admin/bookings/actions/cancel/'), {
            method: 'POST',
            headers: { 'X-CSRFToken': CSRF_TOKEN, Accept: 'application/json' },
            body: form,
            credentials: 'same-origin',
        }));
        announce(data.message || 'Booking cancelled.');
        closeCancelDialog();
        closeDrawer();
        await refreshMapData(true);
    } catch (err) {
        alert(err.message || 'Failed to cancel booking.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Confirm Cancellation';
    }
}
window.openCancelDialog = openCancelDialog;
window.closeCancelDialog = closeCancelDialog;
window.handleCancelReasonPresetChange = handleCancelReasonPresetChange;
window.submitCancelBooking = submitCancelBooking;

let completeTargetBooking = null;
function openCompleteDialog(booking) {
    completeTargetBooking = booking;
    const dialog = document.getElementById('completeBookingDialog');
    if (!dialog) return;
    document.getElementById('completeBookingTargetId').value = booking.booking_id;
    setText('completeBookingIdLabel', '#' + booking.booking_id);
    setText('completeBookingProviderLabel', booking.provider_name ? 'Provider: ' + booking.provider_name : 'Assigned Provider');
    setText('completeBookingAmountLabel', money(booking.total_amount));
    const reqOtp = booking.completion_otp || booking.end_job_otp || booking.job_otp || '';
    setText('completeRequiredOtpDisplay', reqOtp || 'None Required');
    const input = document.getElementById('completeInputOtp');
    if (input) {
        input.value = reqOtp;
    }
    dialog.showModal();
}
function closeCompleteDialog() {
    document.getElementById('completeBookingDialog')?.close();
    completeTargetBooking = null;
}
function fillCompleteOtp() {
    const reqOtp = completeTargetBooking?.completion_otp || completeTargetBooking?.end_job_otp || completeTargetBooking?.job_otp || '';
    const input = document.getElementById('completeInputOtp');
    if (input && reqOtp) {
        input.value = reqOtp;
        input.focus();
    }
}
async function submitCompleteBooking() {
    const btn = document.getElementById('completeConfirmSubmitBtn');
    const bookingId = document.getElementById('completeBookingTargetId')?.value;
    const otp = document.getElementById('completeInputOtp')?.value?.trim();
    if (!bookingId) return;
    btn.disabled = true;
    btn.textContent = 'Completing…';
    const form = new FormData();
    form.append('booking_id', bookingId);
    if (otp) form.append('otp', otp);
    try {
        const data = await readJson(await fetch(endpoint('completeUrl', '/api/v1/admin/bookings/actions/complete/'), {
            method: 'POST',
            headers: { 'X-CSRFToken': CSRF_TOKEN, Accept: 'application/json' },
            body: form,
            credentials: 'same-origin',
        }));
        announce(data.message || 'Booking marked as completed!');
        closeCompleteDialog();
        closeDrawer();
        await refreshMapData(true);
    } catch (err) {
        alert(err.message || 'Failed to complete booking.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Mark as Completed ✓';
    }
}
window.openCompleteDialog = openCompleteDialog;
window.closeCompleteDialog = closeCompleteDialog;
window.fillCompleteOtp = fillCompleteOtp;
window.submitCompleteBooking = submitCompleteBooking;

let reassignTargetBooking = null;
function openReassignDialog(booking) {
    reassignTargetBooking = booking;
    const dialog = document.getElementById('reassignProviderDialog');
    if (!dialog) return;
    setText('reassignBookingIdLabel', '#' + booking.booking_id);
    setText('reassignCurrentProviderLabel', booking.provider_name ? 'Current: ' + booking.provider_name : 'No provider assigned');
    setText('reassignBookingServiceLabel', booking.service_name || booking.category_name || 'Order');

    const container = document.getElementById('reassignCandidatesContainer');
    if (container) {
        container.replaceChildren();
        const candidates = (booking.candidates || []).map(candidate => ({
            candidate, partner: getPartner(candidate.provider_id)
        })).filter(item => item.partner && Number(item.partner.id) !== Number(booking.provider_id));
        candidates.sort((a, b) => (a.candidate.distance_km ?? Infinity) - (b.candidate.distance_km ?? Infinity));

        if (!candidates.length) {
            container.append(node('p', 'map-empty', 'No other eligible providers found in the current filter.'));
        } else {
            candidates.forEach(({ partner, candidate }) => {
                const card = node('div', 'p-3 rounded-xl border border-slate-200 bg-white hover:border-blue-300 transition flex items-center justify-between gap-3 shadow-xs');
                const info = node('div', 'flex-1 min-w-0');
                const nameRow = node('div', 'flex items-center gap-2');
                nameRow.append(node('strong', 'text-xs text-slate-800 font-bold truncate', partner.name));
                nameRow.append(badge(partner.is_available ? 'Online' : 'Offline', partner.is_available));
                info.append(nameRow);
                info.append(node('p', 'text-[11px] text-slate-500 mt-0.5', `${distanceLabel(distanceBetween(booking, partner))} · ★ ${partner.rating || '0.0'} · ${partner.jobs_completed || 0} jobs`));

                const actions = node('div', 'shrink-0');
                const assignBtn = action('Assign This Provider', async (e) => {
                    closeReassignDialog();
                    await dispatchPartnerToBooking(booking, partner, candidate.service_id, e.currentTarget, true);
                }, 'map-action map-action-primary text-xs');
                actions.append(assignBtn);
                card.append(info, actions);
                container.append(card);
            });
        }
    }
    dialog.showModal();
}
function closeReassignDialog() {
    document.getElementById('reassignProviderDialog')?.close();
    reassignTargetBooking = null;
}
window.openReassignDialog = openReassignDialog;
window.closeReassignDialog = closeReassignDialog;

function node(tag, className = '', text = null) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== null && text !== undefined) element.textContent = String(text);
    return element;
}
function action(label, callback, className = 'map-action') {
    const button = node('button', className, label);
    button.type = 'button'; button.addEventListener('click', callback); return button;
}
function safeUrl(value) {
    if (!value) return null;
    const text = String(value);
    if (/^tel:\+?[\d]+$/.test(text) || /^sms:\+?[\d]+(?:\?body=|&body=|$)/.test(text)) return text;
    try {
        const url = new URL(text, window.location.origin);
        if (url.origin === window.location.origin || (url.protocol === 'https:' && ['wa.me', 'www.google.com', 'maps.google.com'].includes(url.hostname))) return url.href;
    } catch (_) { /* Omit invalid links. */ }
    return null;
}
function link(label, href, className = 'map-action') {
    const url = safeUrl(href);
    if (!url) return node('span', 'map-muted', label + ' unavailable');
    const anchor = node('a', className, label); anchor.href = url;
    if (!/^(tel|sms):/.test(url)) { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; }
    return anchor;
}
function phoneUrl(phone) {
    const number = String(phone || '').replace(/[^\d+]/g, '');
    return /^\+?\d+$/.test(number) ? 'tel:' + number : null;
}
function hasCoordinates(item) {
    return !!item && item.lat !== null && item.lng !== null && item.lat !== '' && item.lng !== '' && Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lng)) && Math.abs(Number(item.lat)) <= 90 && Math.abs(Number(item.lng)) <= 180;
}
function groundPosition(item) { return { lat: Number(item.lat), lng: Number(item.lng) }; }
function displayPosition(item) { return { lat: Number(item.displayLat ?? item.lat), lng: Number(item.displayLng ?? item.lng) }; }
function isPending(booking) { return !!booking && booking.status === 'SEARCHING'; }
function isAssigned(booking, partner) {
    return !!booking && !!partner && ['CONFIRMED', 'IN_PROGRESS'].includes(booking.status) && Number(booking.accepted_provider_id || booking.provider_id) === Number(partner.id);
}
function getBooking() { return BOOKINGS.find(b => b.booking_id === selectedBookingId); }
function getPartner(id) {
    return PARTNERS.find(p => Number(p.id) === Number(id)) || BOOKINGS.map(b => b.assigned_provider).find(p => p && Number(p.id) === Number(id));
}
function getCandidate(booking, partner) { return (booking.candidates || []).find(c => Number(c.provider_id) === Number(partner.id)); }
function money(value) { return value !== null && value !== undefined && Number.isFinite(Number(value)) ? '₹' + Number(value).toLocaleString('en-IN') : 'Price unavailable'; }
function endpoint(key, fallback) { return document.getElementById('mapConfig')?.dataset[key] || fallback; }
function setText(id, value) { const element = document.getElementById(id); if (element) element.textContent = value; }
function announce(text, error = false) {
    const element = document.getElementById('mapNotice');
    if (element) { element.textContent = text; element.classList.toggle('map-error', error); element.hidden = !text; }
}
function badge(text, positive = false) { return node('span', positive ? 'map-badge positive' : 'map-badge', text); }
function row(label, value) { const el = node('div', 'map-detail-row'); el.append(node('dt', '', label), node('dd', '', value || '—')); return el; }
function section(title) { const el = node('section', 'map-section'); el.append(node('h4', 'map-section-heading', title)); return el; }
function actionRow() { return node('div', 'map-actions'); }

function resolveCoincidentCoordinates(items) {
    const groups = new Map();
    items.filter(hasCoordinates).forEach(item => {
        const key = `${Number(item.lat).toFixed(6)},${Number(item.lng).toFixed(6)}`;
        if (!groups.has(key)) groups.set(key, []); groups.get(key).push(item);
    });
    groups.forEach(group => group.forEach((item, index) => {
        const angle = 2 * Math.PI * index / group.length;
        item.displayLat = Number(item.lat) + (group.length > 1 ? 0.00022 * Math.cos(angle) : 0);
        item.displayLng = Number(item.lng) + (group.length > 1 ? 0.00022 * Math.sin(angle) : 0);
    }));
}
function calculateDistanceKm(lat1, lng1, lat2, lng2) {
    const rad = degrees => Number(degrees) * Math.PI / 180;
    const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
    return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a)));
}
function distanceBetween(booking, partner) { return hasCoordinates(booking) && hasCoordinates(partner) ? calculateDistanceKm(partner.lat, partner.lng, booking.lat, booking.lng) : null; }
function distanceLabel(distance) { return distance === null ? 'Distance unavailable (GPS missing)' : `≈ ${distance.toFixed(1)} km straight-line`; }
function markerIcon(color, booking = false) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 36 44"><path d="M18 2C10.3 2 5 7.5 5 15c0 10 13 26 13 26S31 25 31 15C31 7.5 25.7 2 18 2z" fill="${color}" stroke="#fff" stroke-width="2"/><circle cx="18" cy="15" r="6" fill="#fff"/>${booking ? '<path d="M15 15h6m-3-3v6" stroke="' + color + '" stroke-width="2"/>' : ''}</svg>`;
    return { url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg), scaledSize: new google.maps.Size(32, 40), anchor: new google.maps.Point(16, 40) };
}
function defineOverlays() {
    BeaconOverlay = class extends google.maps.OverlayView {
        constructor(position) { super(); this.position = position; }
        onAdd() { this.div = node('div', 'booking-beacon-overlay'); this.div.append(node('div', 'beacon-ring'), node('div', 'beacon-dot')); this.getPanes().mapPane.appendChild(this.div); }
        draw() { const p = this.getProjection()?.fromLatLngToDivPixel(this.position); if (p && this.div) { this.div.style.left = `${p.x - 18}px`; this.div.style.top = `${p.y - 18}px`; } }
        onRemove() { this.div?.remove(); }
    };
}
const MAP_WHITE_STYLE = [
    { elementType: 'geometry', stylers: [{ color: '#ffffff' }] },
    { elementType: 'labels.icon', stylers: [{ visibility: 'off' }] },
    { elementType: 'labels.text.fill', stylers: [{ color: '#616161' }] },
    { elementType: 'labels.text.stroke', stylers: [{ color: '#ffffff' }] },
    { featureType: 'poi', stylers: [{ visibility: 'off' }] },
    { featureType: 'transit', stylers: [{ visibility: 'off' }] },
    { featureType: 'landscape', elementType: 'geometry', stylers: [{ color: '#fbfbfb' }] },
    { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#f3f4f6' }] },
    { featureType: 'road', elementType: 'labels.text.fill', stylers: [{ color: '#71717a' }] },
    { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#e5e7eb' }] },
    { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#e2e8f0' }] },
    { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#94a3b8' }] },
    { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#e2e8f0' }] }
];

function initFarmoMap() {
    try { PARTNERS = JSON.parse(document.getElementById('partners-data')?.textContent || '[]'); BOOKINGS = JSON.parse(document.getElementById('bookings-data')?.textContent || '[]'); }
    catch (_) { announce('Map data could not be loaded. Refresh the page.', true); return; }
    CSRF_TOKEN = document.getElementById('mapCsrfToken')?.value || ''; defineOverlays();
    const first = BOOKINGS.find(hasCoordinates) || PARTNERS.find(hasCoordinates);
    map = new google.maps.Map(document.getElementById('map'), {
        center: first ? groundPosition(first) : { lat: 18.5204, lng: 73.8567 }, zoom: 11,
        mapTypeControl: true, mapTypeControlOptions: { position: google.maps.ControlPosition.TOP_LEFT, style: google.maps.MapTypeControlStyle.DROPDOWN_MENU },
        streetViewControl: false, fullscreenControl: false, zoomControl: true,
        zoomControlOptions: { position: google.maps.ControlPosition.RIGHT_BOTTOM },
        styles: MAP_WHITE_STYLE,
    });
    hoverWindow = new google.maps.InfoWindow({ disableAutoPan: true });
    map.addListener('click', () => hoverWindow.close());
    renderMapEntities(); renderQueueSidebar(); fitAllMarkers(); setUpdatedTime(new Date().toISOString());
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if (document.getElementById('cancelBookingDialog')?.open) closeCancelDialog();
        else if (document.getElementById('completeBookingDialog')?.open) closeCompleteDialog();
        else if (document.getElementById('reassignProviderDialog')?.open) closeReassignDialog();
        else if (document.getElementById('statsModalDialog')?.open) closeStatsModal();
        else if (document.getElementById('messageDraftDialog')?.open) closeMessageDraft();
        else closeDrawer();
    });
    ['cancelBookingDialog', 'completeBookingDialog', 'reassignProviderDialog', 'statsModalDialog', 'messageDraftDialog'].forEach(id => {
        const dlg = document.getElementById(id);
        dlg?.addEventListener('cancel', event => { event.preventDefault(); dlg.close(); });
        dlg?.addEventListener('click', event => { if (event.target === dlg) dlg.close(); });
    });
}
function renderMapEntities() {
    hoverWindow?.close();
    [...partnerMarkers, ...bookingMarkers, ...partnerCircles, ...bookingBeacons].forEach(item => item.setMap(null));
    partnerMarkers = []; bookingMarkers = []; partnerCircles = []; bookingBeacons = []; activeHighlightedCircle = null;
    resolveCoincidentCoordinates([...PARTNERS, ...BOOKINGS]);
    PARTNERS.filter(hasCoordinates).forEach(partner => {
        const online = partner.is_available && partner.is_active !== false, visible = online || offlinePartnersVisible;
        const circle = new google.maps.Circle({ map, center: groundPosition(partner), radius: Math.max(0, Number(partner.radius_km) || 0) * 1000,
            fillColor: online ? '#10b981' : '#94a3b8', fillOpacity: 0.05, strokeColor: online ? '#10b981' : '#94a3b8', strokeOpacity: 0.35, strokeWeight: 1, clickable: false, visible: circlesVisible && visible });
        const marker = new google.maps.Marker({ map, position: displayPosition(partner), icon: markerIcon(online ? '#10b981' : '#94a3b8'), title: `${partner.name} · ${online ? 'Online' : 'Offline'}`, zIndex: online ? 20 : 10, visible });
        marker.addListener('click', () => focusPartnerById(partner.id, false));
        marker.addListener('mouseover', () => showPartnerHover(partner)); marker.addListener('mouseout', () => hoverWindow.close());
        partner._marker = marker; partner._circle = circle; partnerMarkers.push(marker); partnerCircles.push(circle);
    });
    BOOKINGS.filter(hasCoordinates).forEach(booking => {
        const pending = isPending(booking);
        const marker = new google.maps.Marker({ map, position: displayPosition(booking), icon: markerIcon(pending ? '#f59e0b' : '#2563eb', true), title: `#${booking.booking_id} · ${booking.service_name || booking.category_name} · ${booking.status_label}`, zIndex: pending ? 60 : 40, visible: bookingsVisible });
        marker.addListener('click', () => openBookingDrawer(booking)); booking._marker = marker; bookingMarkers.push(marker);
        if (pending) { const beacon = new BeaconOverlay(new google.maps.LatLng(displayPosition(booking))); beacon.setMap(bookingsVisible ? map : null); bookingBeacons.push(beacon); }
    }); updateComparison();
}
function setQueueTab(tab) {
    currentQueueTab = tab;
    document.querySelectorAll('.queue-tab-btn').forEach(button => {
        const active = button.dataset.tab === tab;
        button.setAttribute('aria-pressed', String(active));
        if (active) {
            button.classList.add('bg-emerald-600', 'text-white', 'shadow-sm', 'font-bold');
            button.classList.remove('text-slate-600', 'hover:bg-slate-100');
        } else {
            button.classList.remove('bg-emerald-600', 'text-white', 'shadow-sm', 'font-bold');
            button.classList.add('text-slate-600', 'hover:bg-slate-100');
        }
    });
    renderQueueSidebar();
}
function handleQueueSearch(value) { queueSearchQuery = (value || '').toLowerCase().trim(); renderQueueSidebar(); }
function searchText(item, isPartner) {
    const fields = isPartner
        ? [item.name, item.phone, item.type_label, ...(item.services || [])]
        : [item.booking_id, item.order_number, item.customer_name, item.customer_phone, item.service_name, item.category_name, item.status_label, item.address];
    return fields.filter(Boolean).join(' ').toLowerCase();
}
function renderQueueSidebar() {
    const container = document.getElementById('queueListContainer'); if (!container) return; container.replaceChildren();
    const pendingList = BOOKINGS.filter(isPending);
    const activeList = BOOKINGS.filter(b => ['CONFIRMED', 'IN_PROGRESS'].includes(b.status));
    setText('tabPendingCount', pendingList.length);
    setText('tabActiveCount', activeList.length);
    setText('tabAllCount', BOOKINGS.length);
    const items = currentQueueTab === 'partners'
        ? PARTNERS
        : BOOKINGS.filter(b => currentQueueTab === 'pending' ? isPending(b) : currentQueueTab === 'in_progress' ? ['CONFIRMED', 'IN_PROGRESS'].includes(b.status) : true);

    items.filter(item => !queueSearchQuery || searchText(item, currentQueueTab === 'partners').includes(queueSearchQuery)).forEach(item => {
        const isPartner = currentQueueTab === 'partners';
        const selected = isPartner ? Number(item.id) === Number(selectedPartnerId) : item.booking_id === selectedBookingId;

        let cardTypeClass = '';
        if (isPartner) {
            const online = item.is_available && item.is_active !== false;
            cardTypeClass = online ? 'is-partner-online' : 'is-partner-offline';
        } else {
            if (isPending(item)) {
                cardTypeClass = 'is-pending';
            } else if (item.status === 'CONFIRMED') {
                cardTypeClass = 'is-confirmed';
            } else if (item.status === 'IN_PROGRESS') {
                cardTypeClass = 'is-in-progress';
            }
        }

        const card = action('', () => isPartner ? focusPartnerById(item.id) : focusBookingById(item.booking_id), `map-queue-card ${cardTypeClass}` + (selected ? ' is-selected' : ''));
        card.setAttribute('aria-pressed', String(selected));

        // Heading: Title + Status Badge
        const heading = node('div', 'map-card-heading');
        const titleText = isPartner ? item.name : (item.service_name || item.category_name || 'Booking');
        heading.append(node('strong', 'truncate', titleText));

        if (isPartner) {
            const online = item.is_available && item.is_active !== false;
            const badgeEl = node('span', `map-badge ${online ? 'badge-online' : 'badge-offline'}`);
            badgeEl.append(node('span', `badge-dot ${online ? 'badge-dot-green' : 'badge-dot-slate'}`), document.createTextNode(online ? 'Online' : 'Offline'));
            heading.append(badgeEl);
        } else {
            const pending = isPending(item);
            const confirmed = item.status === 'CONFIRMED';
            const inProgress = item.status === 'IN_PROGRESS';
            const badgeClass = pending ? 'badge-pending' : (confirmed ? 'badge-confirmed' : (inProgress ? 'badge-in-progress' : ''));
            const dotClass = pending ? 'badge-dot-amber' : (confirmed ? 'badge-dot-blue' : (inProgress ? 'badge-dot-green' : 'badge-dot-slate'));
            const badgeEl = node('span', `map-badge ${badgeClass}`);
            badgeEl.append(node('span', `badge-dot ${dotClass}`), document.createTextNode(item.status_label || item.status));
            heading.append(badgeEl);
        }
        card.append(heading);

        // Middle Row: Meta information
        const metaRow = node('div', 'map-queue-meta');
        if (isPartner) {
            metaRow.append(node('span', 'map-muted', `${item.type_label} · ★ ${item.rating} · ${item.jobs_completed} jobs`));
        } else {
            metaRow.append(node('span', 'map-booking-id', `#${item.booking_id}`));
            if (item.is_phone) {
                metaRow.append(node('span', 'map-type-chip phone', '📞 Phone'));
            }
            if (item.customer_name) {
                metaRow.append(node('span', 'map-customer-name truncate', item.customer_name));
            }
        }
        card.append(metaRow);

        // Footer Row: Date/Time + Amount or Details
        if (!isPartner) {
            const footerRow = node('div', 'map-queue-footer');
            const timeText = `${item.scheduled_date || 'Today'} ${item.scheduled_time || ''}`.trim();
            footerRow.append(
                node('span', 'text-slate-500 font-medium truncate', timeText || 'Immediate'),
                node('span', 'map-price-tag', money(item.total_amount))
            );
            card.append(footerRow);

            if (!hasCoordinates(item)) {
                card.append(node('span', 'map-warning-text', '⚠️ No GPS location — details available'));
            }
        } else {
            if (item.phone) {
                card.append(node('span', 'text-[10px] text-slate-500 mt-0.5', `📞 ${item.phone}`));
            }
        }

        container.append(card);
    });
    if (!container.childElementCount) container.append(node('p', 'map-empty', 'No items match this filter.'));
}
function openDrawer() {
    const drawer = document.getElementById('dispatchDrawer'); drawer?.classList.replace('drawer-collapsed', 'drawer-open'); if (drawer) drawer.inert = false;
    if (window.matchMedia('(max-width: 1050px)').matches && queueSidebarVisible) toggleQueueSidebar();
}
function closeDrawer() { const drawer = document.getElementById('dispatchDrawer'); drawer?.classList.replace('drawer-open', 'drawer-collapsed'); if (drawer) drawer.inert = true; }
function toggleQueueSidebar() {
    queueSidebarVisible = !queueSidebarVisible; const sidebar = document.getElementById('queueSidebar'); sidebar?.classList.toggle('sidebar-open', queueSidebarVisible); sidebar?.classList.toggle('sidebar-collapsed', !queueSidebarVisible); if (sidebar) sidebar.inert = !queueSidebarVisible;
    document.getElementById('toggleQueueBtn')?.setAttribute('aria-expanded', String(queueSidebarVisible));
}
function focusBookingById(id) {
    const booking = BOOKINGS.find(item => item.booking_id === id); if (!booking) return;
    if (hasCoordinates(booking)) { map.panTo(displayPosition(booking)); if (map.getZoom() < 13) map.setZoom(13); } openBookingDrawer(booking);
}
function focusPartnerById(id, pan = true) {
    const partner = getPartner(id); if (!partner) return;
    if (pan && hasCoordinates(partner)) { map.panTo(displayPosition(partner)); if (map.getZoom() < 13) map.setZoom(13); }
    selectedPartnerId = partner.id; updateComparison();
    if (getBooking()) renderBookingDrawer(getBooking()); else renderPartnerDrawer(partner); renderQueueSidebar(); openDrawer();
}
function openBookingDrawer(booking) {
    if (selectedBookingId !== booking.booking_id) { selectedPartnerId = null; visiblePartnerCounts.matched = 8; visiblePartnerCounts.other = 8; otherPartnersOpen = false; }
    selectedBookingId = booking.booking_id; renderBookingDrawer(booking); renderQueueSidebar(); updateComparison(); openDrawer();
}


function renderBookingDrawer(booking) {
    setText('drawerIconWrap', booking.is_phone ? '📞' : '📋');setText('drawerTitle', booking.service_name || booking.category_name || 'Order details'); setText('drawerSubtitle', `#${booking.booking_id} · ${booking.status_label || booking.status}`);
    const body = document.getElementById('drawerBody'); body.replaceChildren();
    const overview = section('Order details'), details = node('dl', 'map-detail-list');
    details.append(row('Customer', booking.customer_name), row('Work', `${booking.quantity ?? '—'} ${booking.price_unit_label || booking.price_unit || ''}`), row('Date & time', `${booking.scheduled_date || 'Today'} ${booking.scheduled_time || ''}`), row('Agreed total', money(booking.total_amount)), row('Location', booking.address || 'Address unavailable'));
    if (booking.note) details.append(row('Instructions', booking.note));
    if (isPending(booking) && booking.provider_name) details.append(row('Requested provider', booking.provider_name + ' (not yet confirmed)'));
    overview.append(details); const customerActions = actionRow();
    if (phoneUrl(booking.customer_phone)) customerActions.append(link('Call customer', phoneUrl(booking.customer_phone)));
    if (booking.customer_profile_url) customerActions.append(link('Open profile ↗', booking.customer_profile_url)); overview.append(customerActions); body.append(overview);

    // ── Work Security & OTPs Block ──
    const hasOtp = Boolean(booking.start_job_otp || booking.end_job_otp || booking.job_otp);
    if (hasOtp || ['CONFIRMED', 'IN_PROGRESS'].includes(booking.status)) {
        const otpSection = section('Work Security & Verification OTPs');
        otpSection.classList.add('map-otp-section');
        const otpGrid = node('div', 'map-otp-grid');
        if (booking.start_job_otp) {
            otpGrid.append(renderOtpCard('Start Job OTP', booking.start_job_otp, 'Given to start work'));
        }
        if (booking.end_job_otp) {
            otpGrid.append(renderOtpCard('Completion OTP', booking.end_job_otp, 'Customer PIN to finish', true));
        } else if (booking.job_otp) {
            otpGrid.append(renderOtpCard('Work OTP', booking.job_otp, 'Single PIN for completion', true));
        } else {
            const pendingOtpNote = node('div', 'map-otp-pending-box');
            pendingOtpNote.append(node('span', '', '🔒 Work OTPs will be generated once assigned provider confirms.'));
            otpGrid.append(pendingOtpNote);
        }
        otpSection.append(otpGrid);
        body.append(otpSection);
    }

    // ── Dispatch Management Action Buttons ──
    if (['SEARCHING', 'CONFIRMED', 'IN_PROGRESS'].includes(booking.status)) {
        const actionSection = section('Dispatch Actions');
        actionSection.classList.add('map-manage-section');
        const actionsWrap = node('div', 'map-actions map-booking-actions');

        if (['CONFIRMED', 'IN_PROGRESS'].includes(booking.status)) {
            const completeBtn = action('✓ Complete Work', () => openCompleteDialog(booking), 'map-action map-action-success');
            completeBtn.title = 'Complete this booking work with OTP verification';
            actionsWrap.append(completeBtn);
        }

        const reassignBtn = action('⇄ Assign Another Provider', () => openReassignDialog(booking), 'map-action map-action-reassign');
        reassignBtn.title = 'Switch or assign a different provider for this order';
        actionsWrap.append(reassignBtn);

        const cancelBtn = action('🚫 Cancel Booking', () => openCancelDialog(booking), 'map-action map-action-danger');
        cancelBtn.title = 'Cancel this booking order';
        actionsWrap.append(cancelBtn);

        actionSection.append(actionsWrap);
        body.append(actionSection);
    } else if (booking.status === 'CANCELLED' && booking.cancellation_reason) {
        const cancelInfo = section('Cancellation Details');
        cancelInfo.append(node('p', 'map-warning-text', `Reason: ${booking.cancellation_reason}`));
        body.append(cancelInfo);
    }

    if (selectedPartnerId) { const partner = getPartner(selectedPartnerId); if (partner) body.append(comparisonCard(booking, partner)); }
    const assigned = booking.assigned_provider || getPartner(booking.provider_id);
    if (assigned && isAssigned(booking, assigned)) { const assignedSection = section('Assigned provider'); assignedSection.append(providerCard(assigned, booking, getCandidate(booking, assigned), true)); body.append(assignedSection); }
    const alert = node('div'); alert.id = 'assignAlertWrap'; alert.setAttribute('role', 'status'); body.append(alert);
    const candidates = (booking.candidates || []).map(candidate => ({ candidate, partner: getPartner(candidate.provider_id) })).filter(item => item.partner && !isAssigned(booking, item.partner));
    candidates.sort((a, b) => (a.candidate.distance_km ?? Infinity) - (b.candidate.distance_km ?? Infinity));
    const matched = candidates.filter(item => item.candidate.is_eligible), others = candidates.filter(item => !item.candidate.is_eligible);
    const matches = section(`Matching providers (${matched.length})`); matches.id = 'matchedProviders'; appendProviderPage(matches, matched, booking, 'matched');
    if (!matched.length) matches.append(node('p', 'map-empty', 'No eligible providers for this booking in the current map filter.')); body.append(matches);
    if (others.length) {
        const other = node('details', 'map-other-providers'); other.open = otherPartnersOpen; other.append(node('summary', '', `Other providers (${others.length})`));
        other.addEventListener('toggle', () => { otherPartnersOpen = other.open; }); const list = node('div', 'map-provider-list'); appendProviderPage(list, others, booking, 'other'); other.append(list); body.append(other);
    }
}
function appendProviderPage(container, items, booking, group) {
    const list = node('div', 'map-provider-list'); items.slice(0, visiblePartnerCounts[group]).forEach(({ partner, candidate }) => list.append(providerCard(partner, booking, candidate))); container.append(list);
    if (items.length > visiblePartnerCounts[group]) container.append(action(`Show more (${items.length - visiblePartnerCounts[group]} remaining)`, () => { const body = document.getElementById('drawerBody'), scroll = body.scrollTop; visiblePartnerCounts[group] += 8; renderBookingDrawer(booking); body.scrollTop = scroll; }, 'map-action map-show-more'));
}
function relevantServices(partner, booking) {
    return [...(partner.service_details || [])].sort((a, b) => { const score = service => booking && Number(service.id) === Number(booking.service_id) ? 2 : booking && Number(service.category_id) === Number(booking.category_id) ? 1 : 0; return score(b) - score(a); });
}
function serviceSummary(service) { return `${service.title || service.name || 'Service'} · ${money(service.price)} / ${service.price_unit_label || service.price_unit || 'unit'}`; }
function serviceCard(service, partner, booking) {
    const card = node('div', 'map-service-card'); card.append(node('strong', '', service.title || service.name || 'Service'), node('span', '', `${money(service.price)} / ${service.price_unit_label || service.price_unit || 'unit'} · Min. ${service.min_order_qty ?? '—'} ${service.price_unit_label || service.price_unit || ''}`));
    const date = booking?.scheduled_date, busy = date ? (partner.busy_dates || []).includes(date) || (service.busy_dates || []).includes(date) : service.is_busy_today || partner.is_busy_today;
    const available = service.is_available && partner.is_available && partner.is_active !== false && !busy;
    card.append(node('span', available ? 'map-positive-text' : 'map-warning-text', `${available ? 'Available' : busy ? 'Busy' : 'Unavailable'}${date ? ' on ' + date : ''} · ${service.radius_km ?? '—'} km coverage`)); return card;
}
function providerCard(partner, booking, candidate, assigned = false) {
    const card = node('article', 'map-provider-card' + (assigned ? ' is-assigned' : '') + (Number(partner.id) === Number(selectedPartnerId) ? ' is-selected' : ''));
    const header = node('div', 'map-card-heading'); header.append(action(partner.name, () => focusPartnerById(partner.id), 'map-provider-name'), badge(assigned ? 'Assigned ✓' : candidate?.is_eligible ? 'Match' : partner.is_available ? 'Online' : 'Offline', assigned || candidate?.is_eligible));
    card.append(header, node('p', 'map-muted', `${distanceLabel(distanceBetween(booking, partner))} · ★ ${partner.rating || '0.0'}`));
    const request = (booking.requests || []).filter(item => Number(item.provider_id) === Number(partner.id)).sort((a, b) => Number(b.id) - Number(a.id))[0];
    if (request) card.append(node('p', 'map-request-status', `Provider response: ${request.status_label || request.status}${request.is_winner ? ' · confirmed recipient' : ''}`));
    if (!assigned && candidate?.reasons?.length) card.append(node('p', 'map-warning-text', candidate.reasons.join(' · ')));
    const services = relevantServices(partner, booking);
    if (services.length) { const details = node('details', 'map-services'); details.append(node('summary', '', serviceSummary(services[0]) + (services.length > 1 ? ` (+${services.length - 1})` : ''))); services.forEach(service => details.append(serviceCard(service, partner, booking))); card.append(details); }
    const actions = actionRow(); if (phoneUrl(partner.phone)) actions.append(link('Call', phoneUrl(partner.phone))); if (partner.profile_url) actions.append(link('Profile ↗', partner.profile_url)); card.append(actions);
    if (['SEARCHING', 'CONFIRMED', 'IN_PROGRESS'].includes(booking.status)) {
        const messages = actionRow(); [['WhatsApp', 'whatsapp'], ['SMS', 'sms']].forEach(([label, channel]) => {
            const button = action(label, () => openMessageDraft(booking, partner, channel), 'map-action' + (channel === 'whatsapp' ? ' map-action-whatsapp' : ''));
            button.title = assigned ? 'Send full work details to the assigned provider' : 'Send a short enquiry without customer contact or exact location'; messages.append(button);
        }); card.append(messages);
    }
    if (isPending(booking) && candidate?.is_eligible) {
        const serviceIds = candidate.service_ids || (candidate.service_id ? [candidate.service_id] : []), key = `${booking.booking_id}:${partner.id}`;
        if (serviceIds.length > 1) {
            const label = node('label', 'map-select-label', 'Machine / service to assign'), select = node('select', 'map-service-select'); select.setAttribute('aria-label', 'Machine or service to assign for ' + partner.name);
            serviceIds.forEach(id => { const service = services.find(item => Number(item.id) === Number(id)), option = node('option', '', service ? serviceSummary(service) : `Service #${id}`); option.value = String(id); select.append(option); });
            if (serviceIds.map(String).includes(String(selectedServices.get(key)))) select.value = String(selectedServices.get(key)); selectedServices.set(key, select.value); select.addEventListener('change', () => selectedServices.set(key, select.value)); label.append(select); card.append(label);
        }
        card.append(action('Assign provider', event => dispatchPartnerToBooking(booking, partner, selectedServices.get(key) || candidate.service_id || serviceIds[0], event.currentTarget), 'map-action map-action-primary'));
    } return card;
}
function renderPartnerDrawer(partner) {
    setText('drawerIconWrap', '🚜'); setText('drawerTitle', partner.name); setText('drawerSubtitle', `${partner.type_label} · ${partner.is_available ? 'Online' : 'Offline'}`);
    const body = document.getElementById('drawerBody'); body.replaceChildren(); const overview = section('Provider details'), details = node('dl', 'map-detail-list');
    details.append(row('Rating', `★ ${partner.rating} · ${partner.jobs_completed} jobs`), row('Verification', partner.is_verified ? 'Verified' : 'Pending verification'), row('Location', hasCoordinates(partner) ? 'Saved provider location' : 'GPS missing')); overview.append(details);
    const actions = actionRow(); if (phoneUrl(partner.phone)) actions.append(link('Call provider', phoneUrl(partner.phone))); if (partner.profile_url) actions.append(link('Open profile ↗', partner.profile_url)); overview.append(actions); body.append(overview);
    const services = section('Machinery & services'); relevantServices(partner).forEach(service => services.append(serviceCard(service, partner))); (partner.labor_offerings || []).forEach(offering => services.append(node('p', 'map-muted', offering.name || offering.title || offering.service_name || 'Labor service')));
    if (services.childElementCount === 1) services.append(node('p', 'map-empty', 'No active services.'));
    body.append(services);
    const nearby = section('Matching bookings'), bookings = BOOKINGS.filter(booking => getCandidate(booking, partner)?.is_eligible);
    bookings.forEach(booking => nearby.append(action(`#${booking.booking_id} · ${booking.service_name || booking.category_name} · ${distanceLabel(distanceBetween(booking, partner))}`, () => focusBookingById(booking.booking_id), 'map-queue-card')));
    if (!bookings.length) nearby.append(node('p', 'map-empty', 'No eligible bookings in the current map filter.')); body.append(nearby);
}
function comparisonCard(booking, partner) {
    const card = section('Provider comparison'); card.classList.add('map-comparison'); card.append(node('strong', '', partner.name), node('p', 'map-distance', distanceLabel(distanceBetween(booking, partner))));
    const candidate = getCandidate(booking, partner); if (candidate) card.append(node('p', candidate.in_coverage ? 'map-positive-text' : 'map-warning-text', candidate.in_coverage ? 'Within matching service coverage' : 'Outside matching service coverage / no matching service'));
    const actions = actionRow();
    if (hasCoordinates(booking) && hasCoordinates(partner)) { const url = new URL('https://www.google.com/maps/dir/'); url.searchParams.set('api', '1'); url.searchParams.set('origin', `${partner.lat},${partner.lng}`); url.searchParams.set('destination', `${booking.lat},${booking.lng}`); url.searchParams.set('travelmode', 'driving'); actions.append(link('Directions ↗', url.href)); }
    if (partner.profile_url) actions.append(link('Open profile ↗', partner.profile_url)); actions.append(action('Clear comparison', () => { selectedPartnerId = null; updateComparison(); renderBookingDrawer(booking); renderQueueSidebar(); })); card.append(actions); return card;
}
function updateComparison() {
    comparisonLine?.setMap(null); comparisonLine = null; if (activeHighlightedCircle) activeHighlightedCircle.setOptions({ strokeWeight: 1, fillOpacity: 0.05 }); activeHighlightedCircle = null;
    PARTNERS.forEach(partner => { if (partner._circle) partner._circle.setRadius(Math.max(0, Number(partner.radius_km) || 0) * 1000); });
    const booking = getBooking(), partner = selectedPartnerId ? getPartner(selectedPartnerId) : null; if (!partner) return;
    if (partner._circle) { const candidate = booking ? getCandidate(booking, partner) : null, service = (partner.service_details || []).find(item => Number(item.id) === Number(candidate?.service_id)); const radius = service ? Number(service.radius_km) : booking ? 0 : Number(partner.radius_km); partner._circle.setRadius(Math.max(0, radius || 0) * 1000); partner._circle.setOptions({ strokeWeight: 3, fillOpacity: 0.13 }); activeHighlightedCircle = partner._circle; }
    if (!map || !hasCoordinates(booking) || !hasCoordinates(partner)) return;
    comparisonLine = new google.maps.Polyline({ map, path: [groundPosition(booking), groundPosition(partner)], geodesic: true, strokeColor: '#2563eb', strokeWeight: 3, strokeOpacity: 0.85, zIndex: 5, icons: [{ icon: { path: google.maps.SymbolPath.CIRCLE, scale: 4, fillOpacity: 1 }, offset: '0%' }, { icon: { path: google.maps.SymbolPath.CIRCLE, scale: 4, fillOpacity: 1 }, offset: '100%' }] });
}
function showPartnerHover(partner) {
    const content = node('div', 'map-hover-card'); content.append(node('strong', '', partner.name)); const booking = getBooking();
    if (booking) content.append(node('p', 'map-muted', distanceLabel(distanceBetween(booking, partner)))); const services = relevantServices(partner, booking); services.slice(0, 3).forEach(service => content.append(serviceCard(service, partner, booking)));
    if (services.length > 3) content.append(node('p', 'map-muted', `+${services.length - 3} services · click pin to inspect`)); if (!services.length) content.append(node('p', 'map-muted', (partner.services || []).join(' · ') || 'No active machinery')); hoverWindow.setContent(content); hoverWindow.open({ map, anchor: partner._marker, shouldFocus: false });
}
async function readJson(response) {
    if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Your session may have expired. Reload the page and sign in again.');
    const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.error || 'The request could not be completed.'); return data;
}
async function openMessageDraft(booking, partner, channel) {
    const dialog = document.getElementById('messageDraftDialog'); if (!dialog) return;
    const sequence = ++draftSequence; lastDialogFocus = document.activeElement; setText('messageDraftRecipient', `To ${partner.name} · ${partner.phone || 'Phone unavailable'}`);
    const body = document.getElementById('messageDraftBody'); body.replaceChildren(node('p', 'map-muted', 'Checking the latest booking status and preparing your Marathi message…')); document.getElementById('messageDraftActions').replaceChildren(); if (!dialog.open) dialog.showModal();
    const form = new FormData(); form.append('booking_id', booking.booking_id); form.append('partner_id', partner.id);
    try {
        const draft = await readJson(await fetch(booking.message_url || endpoint('messageUrl', '/api/v1/admin/map/message-draft/'), { method: 'POST', headers: { 'X-CSRFToken': CSRF_TOKEN, Accept: 'application/json' }, body: form, credentials: 'same-origin', cache: 'no-store' }));
        if (sequence !== draftSequence || !dialog.open) return;
        body.replaceChildren(badge(draft.detail_level === 'full' ? 'Assigned provider · full work details' : 'Work enquiry · customer details hidden', draft.detail_level === 'full'));
        if (draft.detail_level !== 'full' && !draft.area_available) body.append(node('p', 'map-warning-text', 'A village/area label is unavailable. This draft omits the exact address to protect customer details.'));
        const text = node('textarea', 'map-draft-text'); text.value = draft.text; text.readOnly = true; text.lang = 'mr'; text.setAttribute('aria-label', 'Marathi message draft'); body.append(text, node('p', 'map-muted', 'Review the message, then open your signed-in WhatsApp session or SMS app. You press Send there.'));
        const actions = document.getElementById('messageDraftActions'), whatsapp = link('Open WhatsApp ↗', draft.whatsapp_url, 'map-action map-action-whatsapp'), sms = link('Open SMS', draft.sms_url);
        const copy = action('Copy message', async () => {
            try { if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(draft.text); else { text.focus(); text.select(); if (!document.execCommand('copy')) throw new Error('Unavailable'); } copy.textContent = 'Copied ✓'; }
            catch (_) { text.focus(); text.select(); copy.textContent = 'Select text and copy'; }
        }); actions.append(whatsapp, sms, copy); const primary = channel === 'whatsapp' ? whatsapp : channel === 'sms' ? sms : copy; primary.classList.add('map-action-primary'); primary.focus();
        window.setTimeout(() => { if (sequence === draftSequence && dialog.open) { actions.replaceChildren(action('Refresh message draft', () => openMessageDraft(booking, partner, channel), 'map-action map-action-primary')); text.value = ''; body.prepend(node('p', 'map-warning-text', 'This draft has expired. Refresh it before opening a messaging app.')); } }, 60000);
    } catch (error) {
        if (sequence !== draftSequence || !dialog.open) return; body.replaceChildren(node('p', 'map-error', error.message)); document.getElementById('messageDraftActions').append(action('Refresh map', () => { closeMessageDraft(); refreshMapData(true); }));
    }
}
function closeMessageDraft() { draftSequence++; document.getElementById('messageDraftDialog')?.close(); if (lastDialogFocus?.isConnected) lastDialogFocus.focus({ preventScroll: true }); }
async function dispatchPartnerToBooking(booking, partner, serviceId, button, isReassign = false) {
    if (!window.confirm(`Assign ${partner.name} to booking #${booking.booking_id}? This confirms the booking and reserves availability.`)) return;
    button.disabled = true; button.textContent = 'Assigning…'; const form = new FormData(); form.append('booking_id', booking.booking_id); form.append('partner_id', partner.id); if (serviceId) form.append('service_id', serviceId);
    if (isReassign || booking.status === 'CONFIRMED') form.append('reassign', '1');
    try { const data = await readJson(await fetch(endpoint('assignUrl', '/api/v1/admin/bookings/actions/assign/'), { method: 'POST', headers: { 'X-CSRFToken': CSRF_TOKEN, Accept: 'application/json' }, body: form, credentials: 'same-origin' })); announce(data.message || 'Provider assigned.'); await refreshMapData(true); }
    catch (error) { const alert = document.getElementById('assignAlertWrap'); if (alert) { alert.textContent = error.message; alert.className = 'map-error'; } button.disabled = false; button.textContent = 'Assign provider'; }
}
function setUpdatedTime(value) {
    const date = new Date(value);
    const timeStr = Number.isNaN(date.getTime()) ? 'just now' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    setText('mapUpdatedAt', 'Updated ' + timeStr);
    setText('statsModalUpdatedAt', 'Synced ' + timeStr);
}
async function refreshMapData(manual = false) {
    if (!map || refreshInFlight) return; refreshInFlight = true; const button = document.getElementById('mapRefreshBtn'); if (button) button.disabled = true;
    try {
        const url = new URL(endpoint('dataUrl', '/api/v1/admin/map/data/'), window.location.origin), current = new URLSearchParams(window.location.search); ['category', 'status'].forEach(key => { if (current.has(key)) url.searchParams.set(key, current.get(key)); });
        const data = await readJson(await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } }));
        const drawer = document.getElementById('dispatchDrawer'), wasOpen = drawer.classList.contains('drawer-open'), body = document.getElementById('drawerBody'), scroll = body.scrollTop;
        PARTNERS = data.partners; BOOKINGS = data.bookings;
        if (selectedBookingId && !getBooking()) { selectedBookingId = null; selectedPartnerId = null; closeDrawer(); announce('The selected booking left this filter or is no longer active.'); }
        if (selectedPartnerId && !getPartner(selectedPartnerId)) selectedPartnerId = null;
        renderMapEntities(); renderQueueSidebar(); if (getBooking()) renderBookingDrawer(getBooking()); else if (selectedPartnerId) renderPartnerDrawer(getPartner(selectedPartnerId)); else if (wasOpen) closeDrawer(); body.scrollTop = scroll;
        const stats = data.stats || {};
        const pendingCount = stats.pending_bookings_count ?? BOOKINGS.filter(isPending).length;
        setText('mapOnlineCount', `${stats.partners_online_count ?? PARTNERS.filter(p => p.is_available).length}/${stats.total_partners_on_map ?? PARTNERS.filter(hasCoordinates).length}`);
        setText('mapPendingCount', pendingCount);
        setText('mapBookingCount', stats.total_bookings_on_map ?? BOOKINGS.filter(hasCoordinates).length);
        setText('mapNoGpsCount', stats.partners_without_location ?? '—');
        setText('statsButtonPendingBadge', `${pendingCount} pending`);
        setUpdatedTime(data.updated_at);
        if (stats.booking_counts_by_category !== undefined) {
            updateCategoryBadgesAndSorting(stats.booking_counts_by_category, stats.total_active_bookings);
        }
        if (manual && !document.getElementById('mapNotice')?.textContent) announce('Map updated.');
    } catch (error) { setText('mapUpdatedAt', 'Refresh failed · showing last loaded data'); if (manual) announce(error.message, true); }
    finally { refreshInFlight = false; if (button) button.disabled = false; }
}
function fitAllMarkers() {
    if (!map) return; const bounds = new google.maps.LatLngBounds(); let count = 0; [...partnerMarkers, ...bookingMarkers].forEach(marker => { if (marker.getVisible()) { bounds.extend(marker.getPosition()); count++; } });
    if (count) { map.fitBounds(bounds, 50); google.maps.event.addListenerOnce(map, 'idle', () => { if (map.getZoom() > 14) map.setZoom(14); }); }
}
function toggleCircles() { circlesVisible = !circlesVisible; PARTNERS.forEach(partner => partner._circle?.setVisible(circlesVisible && (partner.is_available || offlinePartnersVisible))); setText('toggleCirclesLabel', circlesVisible ? 'Hide Circles' : 'Show Circles'); document.getElementById('toggleCirclesBtn')?.setAttribute('aria-pressed', String(circlesVisible)); }
function toggleBookings() { bookingsVisible = !bookingsVisible; bookingMarkers.forEach(marker => marker.setVisible(bookingsVisible)); bookingBeacons.forEach(beacon => beacon.setMap(bookingsVisible ? map : null)); setText('toggleBookingsLabel', bookingsVisible ? 'Hide Bookings' : 'Show Bookings'); document.getElementById('toggleBookingsBtn')?.setAttribute('aria-pressed', String(bookingsVisible)); }
function toggleOfflinePartners() { offlinePartnersVisible = !offlinePartnersVisible; PARTNERS.forEach(partner => { const visible = (partner.is_available && partner.is_active !== false) || offlinePartnersVisible; partner._marker?.setVisible(visible); partner._circle?.setVisible(visible && circlesVisible); }); setText('toggleOfflineLabel', offlinePartnersVisible ? 'Hide Offline' : 'Show Offline'); document.getElementById('toggleOfflineBtn')?.setAttribute('aria-pressed', String(offlinePartnersVisible)); }

