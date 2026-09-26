/**
 * Farmo Admin Panel — Map View & Real-Time Dispatch System
 * Features:
 * - Spiderfier / Coordinate resolver for coincident markers (fixes overlapping pins)
 * - Safe Google Maps OverlayView initialization (prevents script crashes)
 * - High z-index & non-blocking beacon pulse for Pending bookings
 * - Availability check (BusyDay calendar integration)
 * - Collapsible Live Dispatch Queue sidebar with instant search & filter
 * - Quick partner assignment with AJAX & auto calendar sync
 */

// ── State variables ──
let map = null;
let PARTNERS = [];
let BOOKINGS = [];
let CSRF_TOKEN = '';

let partnerMarkers = [];
let partnerCircles = [];
let bookingMarkers = [];
let bookingBeacons = [];

let circlesVisible = true;
let bookingsVisible = true;
let offlinePartnersVisible = true;
let activeHighlightedCircle = null;
let activeFocusedMarker = null;

// ── Coincident Coordinate Resolver (Micro-Jitter) ──
// When multiple partners / bookings have the exact same lat/lng (e.g. Pune test data),
// distribute them in a subtle circle so every marker is separate and 100% clickable.
function resolveCoincidentCoordinates(items) {
    const coordMap = new Map();

    items.forEach((item, index) => {
        const key = `${Number(item.lat).toFixed(6)},${Number(item.lng).toFixed(6)}`;
        if (!coordMap.has(key)) {
            coordMap.set(key, []);
        }
        coordMap.get(key).push({ item, index });
    });

    coordMap.forEach((group) => {
        if (group.length > 1) {
            const count = group.length;
            // Distribute in a small radius (~25 meters = ~0.00022 degrees)
            const radius = 0.00022;
            group.forEach((entry, i) => {
                const angle = (2 * Math.PI * i) / count;
                entry.item.displayLat = Number(entry.item.lat) + radius * Math.cos(angle);
                entry.item.displayLng = Number(entry.item.lng) + radius * Math.sin(angle);
                entry.item.isJittered = true;
                entry.item.originalLat = Number(entry.item.lat);
                entry.item.originalLng = Number(entry.item.lng);
            });
        } else {
            group[0].item.displayLat = Number(group[0].item.lat);
            group[0].item.displayLng = Number(group[0].item.lng);
            group[0].item.isJittered = false;
        }
    });
}

// ── Distance Calculation (Haversine km) ──
function calculateDistanceKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = ((Number(lat2) - Number(lat1)) * Math.PI) / 180;
    const dLon = ((Number(lon2) - Number(lon1)) * Math.PI) / 180;
    const a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos((Number(lat1) * Math.PI) / 180) *
            Math.cos((Number(lat2) * Math.PI) / 180) *
            Math.sin(dLon / 2) *
            Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return Math.round(R * c * 10) / 10;
}

// ── HTML Escape Helper ──
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ── SVG Vector Marker Generator ──
function createPartnerMarkerIcon(isOnline) {
    const fillColor = isOnline ? '#10B981' : '#64748B';
    const strokeColor = isOnline ? '#047857' : '#334155';
    const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">
            <defs>
                <filter id="pShadow" x="-20%" y="-10%" width="140%" height="140%">
                    <feDropShadow dx="0" dy="2.5" stdDeviation="1.8" flood-opacity="0.28"/>
                </filter>
            </defs>
            <g filter="url(#pShadow)">
                <path d="M16 2C9.373 2 4 7.373 4 14c0 9 12 22 12 22s12-13 12-22c0-6.627-5.373-12-12-12z" fill="${fillColor}" stroke="${strokeColor}" stroke-width="1.3"/>
                <circle cx="16" cy="14" r="5.5" fill="#FFFFFF"/>
                <circle cx="16" cy="14" r="3" fill="${fillColor}"/>
            </g>
        </svg>`;
    return 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg);
}

function createBookingMarkerIcon(status) {
    const isNew = status === 'PENDING' || status === 'SEARCHING';
    const isConfirmed = status === 'CONFIRMED' || status === 'IN_PROGRESS';

    const fillColor = isNew ? '#F59E0B' : (isConfirmed ? '#2563EB' : '#7C3AED');
    const strokeColor = isNew ? '#B45309' : (isConfirmed ? '#1D4ED8' : '#6D28D9');

    const svg = `
        <svg xmlns="http://www.w3.org/2000/svg" width="38" height="46" viewBox="0 0 38 46">
            <defs>
                <filter id="bShadow" x="-20%" y="-10%" width="140%" height="140%">
                    <feDropShadow dx="0" dy="3" stdDeviation="2" flood-opacity="0.32"/>
                </filter>
            </defs>
            <g filter="url(#bShadow)">
                <path d="M19 2C11.82 2 6 7.82 6 15c0 10.5 13 25 13 25s13-14.5 13-25c0-7.18-5.82-13-13-13z" fill="${fillColor}" stroke="${strokeColor}" stroke-width="1.5"/>
                <circle cx="19" cy="15" r="6" fill="#FFFFFF"/>
                <circle cx="19" cy="15" r="3.2" fill="${fillColor}"/>
                ${isNew ? `
                <g transform="translate(20, 0)">
                    <rect width="17" height="9" rx="4.5" fill="#DC2626" stroke="#FFFFFF" stroke-width="1"/>
                    <text x="8.5" y="6.8" text-anchor="middle" font-size="6" font-weight="900" fill="#FFFFFF" font-family="system-ui,sans-serif">NEW</text>
                </g>
                ` : ''}
            </g>
        </svg>`;
    return 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg);
}

// ── Main Map Initialization ──
function initFarmoMap() {
    // 1. Parse JSON safely from DOM json_script tags
    try {
        const partnersEl = document.getElementById('partners-data');
        if (partnersEl && partnersEl.textContent) {
            PARTNERS = JSON.parse(partnersEl.textContent);
        }
        const bookingsEl = document.getElementById('bookings-data');
        if (bookingsEl && bookingsEl.textContent) {
            BOOKINGS = JSON.parse(bookingsEl.textContent);
        }
    } catch (e) {
        console.error('Error parsing map data JSON:', e);
    }

    const csrfInput = document.getElementById('mapCsrfToken');
    CSRF_TOKEN = csrfInput ? csrfInput.value : '';

    // 2. Resolve coincident coordinates to prevent stacked invisible pins
    const combinedEntities = [...PARTNERS, ...BOOKINGS];
    resolveCoincidentCoordinates(combinedEntities);

    // 3. Define Beacon Overlay safely (now that google.maps is loaded)
    class SafeBeaconOverlay extends google.maps.OverlayView {
        constructor(position) {
            super();
            this.position = position;
            this.div = null;
        }
        onAdd() {
            this.div = document.createElement('div');
            this.div.className = 'booking-beacon-overlay';
            this.div.innerHTML = `
                <div class="beacon-ring"></div>
                <div class="beacon-dot"></div>
            `;
            // Attach to mapPane (the lowest pane beneath markers and tiles)
            const panes = this.getPanes();
            if (panes && panes.mapPane) {
                panes.mapPane.appendChild(this.div);
            }
        }
        draw() {
            const projection = this.getProjection();
            if (!projection || !this.div) return;
            const pos = projection.fromLatLngToDivPixel(this.position);
            if (pos) {
                this.div.style.left = (pos.x - 18) + 'px';
                this.div.style.top = (pos.y - 18) + 'px';
            }
        }
        onRemove() {
            if (this.div && this.div.parentNode) {
                this.div.parentNode.removeChild(this.div);
                this.div = null;
            }
        }
        hide() { if (this.div) this.div.style.display = 'none'; }
        show() { if (this.div) this.div.style.display = ''; }
    }

    // 4. Default Center
    let defaultCenter = { lat: 18.5204, lng: 73.8567 }; // Maharashtra
    if (BOOKINGS.length > 0) {
        defaultCenter = { lat: Number(BOOKINGS[0].displayLat || BOOKINGS[0].lat), lng: Number(BOOKINGS[0].displayLng || BOOKINGS[0].lng) };
    } else if (PARTNERS.length > 0) {
        defaultCenter = { lat: Number(PARTNERS[0].displayLat || PARTNERS[0].lat), lng: Number(PARTNERS[0].displayLng || PARTNERS[0].lng) };
    }

    // 5. Initialize Google Map
    map = new google.maps.Map(document.getElementById('map'), {
        center: defaultCenter,
        zoom: 11,
        mapTypeControl: true,
        mapTypeControlOptions: {
            position: google.maps.ControlPosition.TOP_LEFT,
            style: google.maps.MapTypeControlStyle.DROPDOWN_MENU,
        },
        streetViewControl: false,
        fullscreenControl: false,
        zoomControl: true,
        zoomControlOptions: {
            position: google.maps.ControlPosition.RIGHT_BOTTOM,
        },
        styles: [
            { featureType: 'poi', stylers: [{ visibility: 'off' }] },
            { featureType: 'transit', stylers: [{ visibility: 'off' }] },
            { featureType: 'water', stylers: [{ color: '#dbeafe' }] },
            { featureType: 'landscape', stylers: [{ color: '#f8fafc' }] },
            { featureType: 'road.highway', stylers: [{ color: '#fed7aa', lightness: 35 }] },
        ],
    });

    // Close drawers when clicking empty map background
    map.addListener('click', function () {
        closeDrawer();
    });

    // 6. Render Partner Markers and Coverage Circles
    PARTNERS.forEach(function (partner) {
        const isOnline = Boolean(partner.is_available);
        const partnerLat = Number(partner.displayLat || partner.lat);
        const partnerLng = Number(partner.displayLng || partner.lng);
        const circleLat = Number(partner.originalLat || partner.lat);
        const circleLng = Number(partner.originalLng || partner.lng);
        const radiusKm = Number(partner.radius_km) || 10;
        const circleColor = isOnline ? '#10B981' : '#94A3B8';

        // Coverage circle (centered on ground location)
        const circle = new google.maps.Circle({
            map: map,
            center: { lat: circleLat, lng: circleLng },
            radius: radiusKm * 1000,
            fillColor: circleColor,
            fillOpacity: isOnline ? 0.08 : 0.03,
            strokeColor: circleColor,
            strokeOpacity: isOnline ? 0.45 : 0.22,
            strokeWeight: 1.2,
            clickable: false,
            zIndex: 1,
        });
        partnerCircles.push(circle);

        // Marker (placed at resolved coordinate)
        const marker = new google.maps.Marker({
            map: map,
            position: { lat: partnerLat, lng: partnerLng },
            icon: {
                url: createPartnerMarkerIcon(isOnline),
                scaledSize: new google.maps.Size(32, 40),
                anchor: new google.maps.Point(16, 40),
            },
            title: `${partner.name} (${partner.type_label}) · ${isOnline ? 'Online' : 'Offline'}`,
            zIndex: isOnline ? 20 : 10,
        });

        marker.addListener('click', function (e) {
            if (e && e.stop) e.stop();
            openPartnerDrawer(partner, circle);
        });

        partnerMarkers.push(marker);
        partner._marker = marker;
        partner._circle = circle;
    });

    // 7. Render Booking Markers and Beacons
    BOOKINGS.forEach(function (booking) {
        const isNew = booking.status === 'PENDING' || booking.status === 'SEARCHING';
        const bLat = Number(booking.displayLat || booking.lat);
        const bLng = Number(booking.displayLng || booking.lng);
        const groundLat = Number(booking.originalLat || booking.lat);
        const groundLng = Number(booking.originalLng || booking.lng);

        // Marker with high zIndex so it is ALWAYS on top of partner pins
        const marker = new google.maps.Marker({
            map: map,
            position: { lat: bLat, lng: bLng },
            icon: {
                url: createBookingMarkerIcon(booking.status),
                scaledSize: new google.maps.Size(38, 46),
                anchor: new google.maps.Point(19, 46),
            },
            title: `Booking #${booking.booking_id} — ${booking.service_name || booking.category_name || 'Service'} (${booking.status_label})`,
            zIndex: isNew ? 60 : 40,
        });

        // Pulsating beacon for pending bookings
        if (isNew) {
            const beacon = new SafeBeaconOverlay(new google.maps.LatLng(bLat, bLng));
            beacon.setMap(map);
            bookingBeacons.push(beacon);
            booking._beacon = beacon;
        }

        marker.addListener('click', function (e) {
            if (e && e.stop) e.stop();
            openBookingDrawer(booking);
        });

        bookingMarkers.push(marker);
        booking._marker = marker;
    });

    // 8. Render the Dispatch Queue Sidebar
    renderQueueSidebar();

    // 9. Initial Fit Bounds
    fitAllMarkers();
}

// ── Queue Sidebar Rendering & Filtering ──
let currentQueueTab = 'pending'; // 'pending' | 'in_progress' | 'all' | 'partners'
let queueSearchQuery = '';

function setQueueTab(tab) {
    currentQueueTab = tab;
    // Update tab button styles
    document.querySelectorAll('.queue-tab-btn').forEach(btn => {
        if (btn.dataset.tab === tab) {
            btn.className = 'queue-tab-btn px-2.5 py-1 text-xs font-bold rounded-lg bg-emerald-600 text-white shadow-sm transition';
        } else {
            btn.className = 'queue-tab-btn px-2.5 py-1 text-xs font-medium rounded-lg text-slate-600 hover:bg-slate-100 transition';
        }
    });
    renderQueueSidebar();
}

function handleQueueSearch(val) {
    queueSearchQuery = (val || '').toLowerCase().trim();
    renderQueueSidebar();
}

function renderQueueSidebar() {
    const listContainer = document.getElementById('queueListContainer');
    if (!listContainer) return;

    if (currentQueueTab === 'partners') {
        // Render Partners
        let filteredPartners = PARTNERS.filter(p => {
            if (!queueSearchQuery) return true;
            return (
                (p.name && p.name.toLowerCase().includes(queueSearchQuery)) ||
                (p.phone && p.phone.includes(queueSearchQuery)) ||
                (p.type_label && p.type_label.toLowerCase().includes(queueSearchQuery))
            );
        });

        if (filteredPartners.length === 0) {
            listContainer.innerHTML = `
                <div class="py-8 text-center text-slate-400">
                    <p class="text-xs">No partners found</p>
                </div>`;
            return;
        }

        listContainer.innerHTML = filteredPartners.map(p => `
            <div class="p-3 bg-white hover:bg-emerald-50/40 rounded-xl border border-slate-200/90 hover:border-emerald-300 shadow-sm transition cursor-pointer"
                 onclick="focusPartnerById(${p.id})">
                <div class="flex items-start justify-between gap-2">
                    <div>
                        <div class="flex items-center gap-1.5">
                            <span class="w-2 h-2 rounded-full ${p.is_available ? 'bg-emerald-500' : 'bg-slate-400'}"></span>
                            <p class="font-bold text-slate-800 text-xs">${escapeHtml(p.name)}</p>
                        </div>
                        <p class="text-[11px] text-slate-500 mt-0.5">${escapeHtml(p.type_label || 'Partner')} · ${p.radius_km} km radius</p>
                    </div>
                    <div class="text-right">
                        <span class="text-[10px] font-bold ${p.is_available ? 'text-emerald-700 bg-emerald-50' : 'text-slate-600 bg-slate-100'} px-2 py-0.5 rounded-full">
                            ${p.is_available ? (p.is_busy_today ? 'Busy Today' : 'Online') : 'Offline'}
                        </span>
                        <p class="text-[10px] text-slate-400 mt-1">★ ${p.rating} (${p.jobs_completed} jobs)</p>
                    </div>
                </div>
            </div>
        `).join('');
        return;
    }

    // Filter Bookings by Tab
    let filteredBookings = BOOKINGS.filter(b => {
        if (currentQueueTab === 'pending') {
            return b.status === 'PENDING' || b.status === 'SEARCHING';
        } else if (currentQueueTab === 'in_progress') {
            return b.status === 'CONFIRMED' || b.status === 'IN_PROGRESS';
        }
        return true;
    });

    // Apply Search
    if (queueSearchQuery) {
        filteredBookings = filteredBookings.filter(b => {
            return (
                (b.booking_id && b.booking_id.toLowerCase().includes(queueSearchQuery)) ||
                (b.order_number && b.order_number.toLowerCase().includes(queueSearchQuery)) ||
                (b.customer_name && b.customer_name.toLowerCase().includes(queueSearchQuery)) ||
                (b.customer_phone && b.customer_phone.includes(queueSearchQuery)) ||
                (b.service_name && b.service_name.toLowerCase().includes(queueSearchQuery)) ||
                (b.category_name && b.category_name.toLowerCase().includes(queueSearchQuery))
            );
        });
    }

    // Update Counts on tab badges
    const pendingCount = BOOKINGS.filter(b => b.status === 'PENDING' || b.status === 'SEARCHING').length;
    const activeCount = BOOKINGS.filter(b => b.status === 'CONFIRMED' || b.status === 'IN_PROGRESS').length;
    const tabPendingCountEl = document.getElementById('tabPendingCount');
    const tabActiveCountEl = document.getElementById('tabActiveCount');
    const tabAllCountEl = document.getElementById('tabAllCount');
    if (tabPendingCountEl) tabPendingCountEl.textContent = pendingCount;
    if (tabActiveCountEl) tabActiveCountEl.textContent = activeCount;
    if (tabAllCountEl) tabAllCountEl.textContent = BOOKINGS.length;

    if (filteredBookings.length === 0) {
        listContainer.innerHTML = `
            <div class="py-8 text-center text-slate-400">
                <p class="text-xs">No bookings in this filter</p>
            </div>`;
        return;
    }

    listContainer.innerHTML = filteredBookings.map(b => {
        const isNew = b.status === 'PENDING' || b.status === 'SEARCHING';
        const statusBadgeClass = isNew
            ? 'bg-amber-100 text-amber-800 border border-amber-300'
            : (b.status === 'CONFIRMED' ? 'bg-blue-100 text-blue-800' : 'bg-emerald-100 text-emerald-800');

        return `
            <div class="p-3 bg-white hover:bg-amber-50/30 rounded-xl border ${isNew ? 'border-amber-300 shadow-sm' : 'border-slate-200/90'} transition cursor-pointer group"
                 onclick="focusBookingById('${escapeHtml(b.booking_id)}')">
                <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                        <div class="flex items-center gap-1.5">
                            <span class="font-bold text-slate-900 text-xs truncate">${escapeHtml(b.service_name || b.category_name || 'Booking')}</span>
                            ${isNew ? '<span class="w-2 h-2 rounded-full bg-amber-500 shrink-0 animate-ping"></span>' : ''}
                        </div>
                        <p class="text-[11px] text-slate-500 font-mono mt-0.5 truncate">#${escapeHtml(b.booking_id)} · ${escapeHtml(b.customer_name)}</p>
                    </div>
                    <div class="text-right shrink-0">
                        <span class="text-[10px] font-extrabold ${statusBadgeClass} px-2 py-0.5 rounded-full inline-block">
                            ${escapeHtml(b.status_label || b.status)}
                        </span>
                        <p class="text-xs font-extrabold text-slate-800 mt-1">₹${(Number(b.total_amount) || 0).toLocaleString('en-IN')}</p>
                    </div>
                </div>
                ${b.scheduled_date ? `
                <div class="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[10px] text-slate-400">
                    <span>📅 ${escapeHtml(b.scheduled_date)} ${escapeHtml(b.scheduled_time)}</span>
                    <span class="text-emerald-700 font-semibold group-hover:underline">Dispatch →</span>
                </div>` : ''}
            </div>
        `;
    }).join('');
}

// ── Open / Close Right Dispatch Drawer ──
function openDrawer() {
    const drawer = document.getElementById('dispatchDrawer');
    if (!drawer) return;
    drawer.classList.remove('drawer-collapsed');
    drawer.classList.add('drawer-open');
}

function closeDrawer() {
    const drawer = document.getElementById('dispatchDrawer');
    if (!drawer) return;
    drawer.classList.remove('drawer-open');
    drawer.classList.add('drawer-collapsed');

    // Reset highlighted circle
    if (activeHighlightedCircle) {
        activeHighlightedCircle.setOptions({
            strokeWeight: 1.2,
            fillOpacity: 0.08,
        });
        activeHighlightedCircle = null;
    }
}

// ── Toggle Queue Sidebar ──
let queueSidebarVisible = true;
function toggleQueueSidebar() {
    const sidebar = document.getElementById('queueSidebar');
    const toggleBtn = document.getElementById('toggleQueueBtn');
    if (!sidebar) return;

    queueSidebarVisible = !queueSidebarVisible;
    if (queueSidebarVisible) {
        sidebar.classList.remove('sidebar-collapsed');
        sidebar.classList.add('sidebar-open');
        if (toggleBtn) toggleBtn.classList.add('bg-emerald-50', 'text-emerald-700', 'border-emerald-300');
    } else {
        sidebar.classList.remove('sidebar-open');
        sidebar.classList.add('sidebar-collapsed');
        if (toggleBtn) toggleBtn.classList.remove('bg-emerald-50', 'text-emerald-700', 'border-emerald-300');
    }
}

// ── Focus & Inspect a Booking by ID ──
function focusBookingById(bookingId) {
    const booking = BOOKINGS.find(b => b.booking_id === bookingId);
    if (!booking) return;

    const bLat = Number(booking.displayLat || booking.lat);
    const bLng = Number(booking.displayLng || booking.lng);

    map.panTo({ lat: bLat, lng: bLng });
    map.setZoom(14);

    // Bounce marker briefly
    if (booking._marker) {
        booking._marker.setAnimation(google.maps.Animation.BOUNCE);
        setTimeout(() => {
            booking._marker.setAnimation(null);
        }, 1400);
    }

    openBookingDrawer(booking);
}

// ── Focus & Inspect a Partner by ID ──
function focusPartnerById(partnerId) {
    const partner = PARTNERS.find(p => p.id === Number(partnerId));
    if (!partner) return;

    const pLat = Number(partner.displayLat || partner.lat);
    const pLng = Number(partner.displayLng || partner.lng);

    map.panTo({ lat: pLat, lng: pLng });
    map.setZoom(13);

    openPartnerDrawer(partner, partner._circle);
}

// ── Open Booking Dispatch Drawer ──
function openBookingDrawer(booking) {
    if (!booking) return;

    const isNew = booking.status === 'PENDING' || booking.status === 'SEARCHING';
    const bLat = Number(booking.originalLat || booking.lat);
    const bLng = Number(booking.originalLng || booking.lng);
    const scheduledDate = booking.scheduled_date || '';

    // Update Header
    const iconWrap = document.getElementById('drawerIconWrap');
    if (iconWrap) {
        iconWrap.innerHTML = booking.booking_type === 'INSTANT' ? '⚡' : '📅';
        iconWrap.className = `w-9 h-9 rounded-xl flex items-center justify-center ${isNew ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-800'} text-base font-bold`;
    }
    const titleEl = document.getElementById('drawerTitle');
    if (titleEl) {
        titleEl.textContent = booking.service_name || booking.category_name || 'Booking Details';
    }
    const subTitleEl = document.getElementById('drawerSubtitle');
    if (subTitleEl) {
        subTitleEl.textContent = `#${booking.booking_id} · ${booking.status_label || booking.status}`;
    }

    // Find and sort all nearby partners with availability check
    const partnerList = [];
    PARTNERS.forEach(p => {
        const pLat = Number(p.originalLat || p.lat);
        const pLng = Number(p.originalLng || p.lng);
        const pRadius = Number(p.radius_km) || 10;
        const dist = calculateDistanceKm(pLat, pLng, bLat, bLng);
        const inCoverage = dist <= pRadius;

        // Check if partner is marked busy on booking scheduled date
        let isBusyOnDate = false;
        if (scheduledDate && Array.isArray(p.busy_dates)) {
            isBusyOnDate = p.busy_dates.includes(scheduledDate);
        }

        partnerList.push({
            partner: p,
            distance: dist,
            inCoverage: inCoverage,
            isBusyOnDate: isBusyOnDate,
        });
    });

    // Sort: In Coverage first, then not busy on date first, then shortest distance
    partnerList.sort((a, b) => {
        if (a.inCoverage !== b.inCoverage) return a.inCoverage ? -1 : 1;
        if (a.isBusyOnDate !== b.isBusyOnDate) return a.isBusyOnDate ? 1 : -1;
        return a.distance - b.distance;
    });

    const inCoverageCount = partnerList.filter(item => item.inCoverage).length;
    const cleanCustomerPhone = String(booking.customer_phone || '').replace(/\s+/g, '');
    const cleanProviderPhone = String(booking.provider_phone || '').replace(/\s+/g, '');

    // Build Partner List HTML
    let partnerSectionHtml = '';
    if (partnerList.length > 0) {
        partnerSectionHtml = `
            <div class="mt-4 pt-4 border-t border-slate-200">
                <div class="flex items-center justify-between mb-2.5">
                    <p class="text-[11px] font-bold text-slate-600 uppercase tracking-wider">
                        Matched Partners (${inCoverageCount} In Range)
                    </p>
                    <span class="text-[10px] text-slate-400 font-medium">Sorted by distance</span>
                </div>
                <div class="space-y-2 max-h-64 overflow-y-auto pr-1 custom-scrollbar">
                    ${partnerList.slice(0, 12).map(item => {
                        const p = item.partner;
                        const isAssigned = booking.provider_id && Number(booking.provider_id) === Number(p.id);
                        const pName = p.name || `Partner #${p.id}`;
                        const isOnline = p.is_available;

                        return `
                            <div class="p-3 rounded-xl border ${isAssigned ? 'bg-emerald-50/80 border-emerald-300 ring-1 ring-emerald-400' : (item.inCoverage ? 'bg-white border-slate-200 hover:border-slate-300' : 'bg-slate-50 border-slate-200/60 opacity-60')} transition">
                                <div class="flex items-start justify-between gap-2">
                                    <div class="min-w-0">
                                        <div class="flex items-center gap-1.5">
                                            <p class="font-bold text-slate-800 text-xs truncate">${escapeHtml(pName)}</p>
                                            ${item.inCoverage ? '<span class="text-[9px] bg-emerald-100 text-emerald-800 font-bold px-1.5 py-0.2 rounded">In Range</span>' : '<span class="text-[9px] bg-slate-200 text-slate-600 font-medium px-1.5 py-0.2 rounded">Out of Range</span>'}
                                        </div>
                                        <p class="text-[10px] text-slate-500 mt-0.5">
                                            ${item.distance} km away · ${p.radius_km} km radius · ★ ${p.rating}
                                        </p>
                                        
                                        <!-- Availability status tag -->
                                        <div class="mt-1 flex items-center gap-1">
                                            ${!isOnline ? `
                                                <span class="text-[9px] font-semibold text-slate-500 bg-slate-100 px-1.5 py-0.2 rounded">Offline</span>
                                            ` : (item.isBusyOnDate ? `
                                                <span class="text-[9px] font-bold text-amber-700 bg-amber-100 px-1.5 py-0.2 rounded">⚠ Busy on ${scheduledDate}</span>
                                            ` : `
                                                <span class="text-[9px] font-bold text-emerald-700 bg-emerald-100 px-1.5 py-0.2 rounded">✓ Available ${scheduledDate ? 'on ' + scheduledDate : 'Now'}</span>
                                            `)}
                                        </div>
                                    </div>

                                    <div class="shrink-0">
                                        ${isAssigned ? `
                                            <span class="text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-1 rounded-lg inline-block">Assigned ✓</span>
                                        ` : `
                                            <button onclick="dispatchPartnerToBooking('${escapeHtml(booking.booking_id)}', ${p.id}, ${item.isBusyOnDate})"
                                                    class="px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-700 active:scale-95 text-white font-semibold text-[10px] transition flex items-center gap-1 shadow-sm">
                                                Assign
                                            </button>
                                        `}
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>`;
    }

    const drawerBody = document.getElementById('drawerBody');
    if (!drawerBody) return;

    drawerBody.innerHTML = `
        <!-- Booking Overview Card -->
        <div class="p-3.5 bg-slate-50 rounded-xl border border-slate-200/90 space-y-2.5">
            <div class="flex items-center justify-between">
                <span class="text-xs font-semibold text-slate-700">${escapeHtml(booking.service_name || booking.category_name || 'Service')}</span>
                <span class="text-sm font-extrabold text-slate-900">₹${(Number(booking.total_amount) || 0).toLocaleString('en-IN')}</span>
            </div>

            <div class="space-y-1 text-xs pt-2 border-t border-slate-200/70">
                <div class="flex items-center justify-between text-slate-500">
                    <span>Customer</span>
                    <span class="font-bold text-slate-800">${escapeHtml(booking.customer_name)}</span>
                </div>
                ${booking.scheduled_date ? `
                <div class="flex items-center justify-between text-slate-500">
                    <span>Scheduled Date</span>
                    <span class="font-semibold text-slate-800">${escapeHtml(booking.scheduled_date)} ${escapeHtml(booking.scheduled_time)}</span>
                </div>` : ''}
                ${booking.address ? `
                <div class="flex items-start justify-between text-slate-500 gap-2">
                    <span class="shrink-0">Address</span>
                    <span class="font-medium text-slate-700 text-right truncate max-w-[200px]">${escapeHtml(booking.address)}</span>
                </div>` : ''}
                <div class="flex items-center justify-between text-slate-500">
                    <span>Assigned Provider</span>
                    <span class="font-bold ${booking.provider_name ? 'text-emerald-700' : 'text-amber-700'}">
                        ${booking.provider_name ? `✓ ${escapeHtml(booking.provider_name)}` : '⚠ Unassigned (Open for Dispatch)'}
                    </span>
                </div>
            </div>
        </div>

        <!-- Quick Call Actions -->
        <div class="flex gap-2">
            ${cleanCustomerPhone ? `
            <a href="tel:${cleanCustomerPhone}"
               class="flex-1 py-2 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-center text-xs transition flex items-center justify-center gap-1.5 shadow-sm">
                📞 Call Customer (${escapeHtml(booking.customer_phone)})
            </a>` : ''}
            ${booking.provider_id && cleanProviderPhone ? `
            <a href="tel:${cleanProviderPhone}"
               class="py-2 px-3 rounded-xl border border-slate-300 hover:bg-slate-100 text-slate-700 font-semibold text-center text-xs transition flex items-center justify-center gap-1">
                📞 Provider
            </a>` : ''}
        </div>

        <div id="assignAlertWrap"></div>

        ${partnerSectionHtml}
    `;

    openDrawer();
}

// ── Open Partner Details Drawer ──
function openPartnerDrawer(partner, circle) {
    if (!partner) return;

    // Highlight Coverage Circle
    if (activeHighlightedCircle) {
        activeHighlightedCircle.setOptions({ strokeWeight: 1.2, fillOpacity: 0.08 });
    }
    if (circle) {
        circle.setOptions({ strokeWeight: 2.8, fillOpacity: 0.18 });
        activeHighlightedCircle = circle;
    }

    // Update Header
    const iconWrap = document.getElementById('drawerIconWrap');
    if (iconWrap) {
        iconWrap.innerHTML = '🚜';
        iconWrap.className = 'w-9 h-9 rounded-xl flex items-center justify-center bg-emerald-100 text-emerald-800 text-base font-bold';
    }
    const titleEl = document.getElementById('drawerTitle');
    if (titleEl) {
        titleEl.textContent = partner.name || 'Partner Details';
    }
    const subTitleEl = document.getElementById('drawerSubtitle');
    if (subTitleEl) {
        subTitleEl.textContent = `${partner.type_label || 'Partner'} · ${partner.is_available ? 'Online' : 'Offline'}`;
    }

    const pLat = Number(partner.originalLat || partner.lat);
    const pLng = Number(partner.originalLng || partner.lng);
    const radiusKm = Number(partner.radius_km) || 10;

    // Find all bookings within this partner's coverage circle
    const inRangeBookings = BOOKINGS.filter(b => {
        const d = calculateDistanceKm(pLat, pLng, Number(b.originalLat || b.lat), Number(b.originalLng || b.lng));
        return d <= radiusKm;
    });

    // Offered Services / Skills tags
    let servicesHtml = '';
    if (Array.isArray(partner.services) && partner.services.length > 0) {
        servicesHtml = `
            <div class="mt-2.5">
                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Offered Services & Skills</p>
                <div class="flex flex-wrap gap-1">
                    ${partner.services.map(s => `<span class="bg-slate-100 text-slate-700 px-2 py-0.5 rounded text-[11px] font-medium">${escapeHtml(s)}</span>`).join('')}
                </div>
            </div>`;
    }

    // In Range Bookings List
    let bookingsHtml = '';
    if (inRangeBookings.length > 0) {
        bookingsHtml = `
            <div class="mt-4 pt-4 border-t border-slate-200">
                <p class="text-[11px] font-bold text-slate-600 uppercase tracking-wider mb-2">Bookings in Coverage Area (${inRangeBookings.length})</p>
                <div class="space-y-1.5 max-h-52 overflow-y-auto pr-1 custom-scrollbar">
                    ${inRangeBookings.map(b => {
                        const d = calculateDistanceKm(pLat, pLng, Number(b.originalLat || b.lat), Number(b.originalLng || b.lng));
                        return `
                            <div class="p-2.5 rounded-xl bg-slate-50 hover:bg-emerald-50/50 border border-slate-200 transition cursor-pointer flex items-center justify-between"
                                 onclick="focusBookingById('${escapeHtml(b.booking_id)}')">
                                <div>
                                    <p class="font-bold text-slate-800 text-xs">${escapeHtml(b.service_name || b.category_name || 'Booking')}</p>
                                    <p class="text-[10px] text-slate-500 font-mono">#${escapeHtml(b.booking_id)} · ${d} km away</p>
                                </div>
                                <span class="text-xs font-bold text-emerald-700">₹${(Number(b.total_amount) || 0).toLocaleString('en-IN')}</span>
                            </div>`;
                    }).join('')}
                </div>
            </div>`;
    } else {
        bookingsHtml = `
            <div class="mt-4 pt-3 border-t border-slate-200 text-center py-4 text-slate-400 text-xs">
                No active bookings within this partner's ${radiusKm} km radius.
            </div>`;
    }

    const drawerBody = document.getElementById('drawerBody');
    if (!drawerBody) return;

    drawerBody.innerHTML = `
        <!-- Status & Stats Card -->
        <div class="p-3.5 bg-slate-50 rounded-xl border border-slate-200/90 space-y-2.5">
            <div class="flex items-center justify-between">
                <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold ${partner.is_available ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-700'}">
                    <span class="w-2 h-2 rounded-full ${partner.is_available ? 'bg-emerald-500' : 'bg-slate-500'}"></span>
                    ${partner.is_available ? (partner.is_busy_today ? 'Busy Today' : 'Online & Available') : 'Offline'}
                </span>
                ${partner.is_verified ? '<span class="text-[10px] font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded-full">✓ Verified</span>' : '<span class="text-[10px] font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">⚠ Pending KYC</span>'}
            </div>

            <div class="grid grid-cols-3 gap-2 pt-2 border-t border-slate-200/70 text-center">
                <div>
                    <p class="text-[9px] text-slate-400 font-bold uppercase">Coverage</p>
                    <p class="text-sm font-extrabold text-slate-800 mt-0.5">${radiusKm} km</p>
                </div>
                <div>
                    <p class="text-[9px] text-slate-400 font-bold uppercase">Jobs Done</p>
                    <p class="text-sm font-extrabold text-slate-800 mt-0.5">${partner.jobs_completed || 0}</p>
                </div>
                <div>
                    <p class="text-[9px] text-slate-400 font-bold uppercase">Rating</p>
                    <p class="text-sm font-extrabold text-slate-800 mt-0.5">★ ${partner.rating || '0.0'}</p>
                </div>
            </div>
        </div>

        ${servicesHtml}

        <!-- Quick Actions -->
        <div class="flex gap-2 pt-1">
            ${partner.phone ? `
            <a href="tel:${String(partner.phone).replace(/\s+/g, '')}"
               class="flex-1 py-2 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-center text-xs transition flex items-center justify-center gap-1.5 shadow-sm">
                📞 Call Partner
            </a>` : ''}
            ${partner.user_id ? `
            <a href="/api/v1/admin/manage/users/${partner.user_id}/" target="_blank"
               class="py-2 px-3 rounded-xl border border-slate-300 hover:bg-slate-100 text-slate-700 font-semibold text-center text-xs transition flex items-center justify-center">
                Profile ↗
            </a>
            <a href="/api/v1/admin/manage/users/${partner.user_id}/calendar/" target="_blank"
               class="py-2 px-3 rounded-xl border border-slate-300 hover:bg-slate-100 text-slate-700 font-semibold text-center text-xs transition flex items-center justify-center">
                Calendar 📅
            </a>` : ''}
        </div>

        ${bookingsHtml}
    `;

    openDrawer();
}

// ── Assign Partner via AJAX ──
function dispatchPartnerToBooking(bookingId, partnerId, isBusyOnDate) {
    const partner = PARTNERS.find(p => p.id === Number(partnerId));
    const partnerName = partner ? partner.name : `Partner #${partnerId}`;

    let confirmMsg = `Assign ${partnerName} to Booking #${bookingId}?`;
    if (isBusyOnDate) {
        confirmMsg = `⚠️ WARNING: ${partnerName} is marked BUSY on this booking's scheduled date in their calendar.\n\nDo you still want to assign them?`;
    }

    if (!confirm(confirmMsg)) return;

    const alertWrap = document.getElementById('assignAlertWrap');
    if (alertWrap) {
        alertWrap.innerHTML = '<div class="p-2 rounded-lg bg-blue-50 text-blue-700 text-xs font-medium">Assigning partner...</div>';
    }

    const formData = new FormData();
    formData.append('booking_id', bookingId);
    formData.append('partner_id', partnerId);

    fetch('/api/v1/admin/map/assign/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': CSRF_TOKEN,
        },
        body: formData,
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // Update local booking model
                const booking = BOOKINGS.find(b => b.booking_id === bookingId);
                if (booking) {
                    booking.provider_name = data.provider_name;
                    booking.provider_id = Number(partnerId);
                    booking.provider_phone = data.provider_phone;
                    booking.status = data.status;
                    booking.status_label = data.status_label;

                    // Update marker icon
                    if (booking._marker) {
                        booking._marker.setIcon({
                            url: createBookingMarkerIcon('CONFIRMED'),
                            scaledSize: new google.maps.Size(38, 46),
                            anchor: new google.maps.Point(19, 46),
                        });
                        booking._marker.setZIndex(40);
                    }

                    // Remove beacon overlay if any
                    if (booking._beacon) {
                        booking._beacon.setMap(null);
                    }

                    // Re-render drawer and queue
                    openBookingDrawer(booking);
                    renderQueueSidebar();
                }

                if (alertWrap) {
                    alertWrap.innerHTML = `<div class="p-2.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-bold mb-2">✓ ${escapeHtml(data.message)}</div>`;
                }
            } else {
                alert('Error: ' + (data.error || 'Could not assign partner.'));
                if (alertWrap) alertWrap.innerHTML = '';
            }
        })
        .catch(err => {
            console.error('Assign Partner error:', err);
            alert('Server error occurred while assigning partner.');
            if (alertWrap) alertWrap.innerHTML = '';
        });
}

// ── Map Controls ──
function fitAllMarkers() {
    if (!map) return;
    const bounds = new google.maps.LatLngBounds();
    let count = 0;

    partnerMarkers.forEach(m => {
        if (m.getVisible()) {
            bounds.extend(m.getPosition());
            count++;
        }
    });
    bookingMarkers.forEach(m => {
        if (m.getVisible()) {
            bounds.extend(m.getPosition());
            count++;
        }
    });

    if (count > 0) {
        map.fitBounds(bounds);
        google.maps.event.addListenerOnce(map, 'bounds_changed', function () {
            if (map.getZoom() > 14) map.setZoom(14);
        });
    }
}

function toggleCircles() {
    circlesVisible = !circlesVisible;
    partnerCircles.forEach(c => c.setVisible(circlesVisible));
    const label = document.getElementById('toggleCirclesLabel');
    if (label) label.textContent = circlesVisible ? 'Hide Circles' : 'Show Circles';
}

function toggleBookings() {
    bookingsVisible = !bookingsVisible;
    bookingMarkers.forEach(m => m.setVisible(bookingsVisible));
    bookingBeacons.forEach(b => (bookingsVisible ? b.show() : b.hide()));
    const label = document.getElementById('toggleBookingsLabel');
    if (label) label.textContent = bookingsVisible ? 'Hide Bookings' : 'Show Bookings';
}

function toggleOfflinePartners() {
    offlinePartnersVisible = !offlinePartnersVisible;
    PARTNERS.forEach(p => {
        if (!p.is_available && p._marker) {
            p._marker.setVisible(offlinePartnersVisible);
        }
        if (!p.is_available && p._circle) {
            p._circle.setVisible(offlinePartnersVisible && circlesVisible);
        }
    });
    const label = document.getElementById('toggleOfflineLabel');
    if (label) label.textContent = offlinePartnersVisible ? 'Hide Offline' : 'Show Offline';
}
