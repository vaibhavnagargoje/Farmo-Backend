/* ══════════════════════════════════════════════════════════════════
   Quick Book: slide-over wizard for placing an instant booking from a call.
   Steps: 1 Customer → 2 Location → 3 Machinery & work → 4 Review.
   All server text is inserted with textContent (never innerHTML).
   ══════════════════════════════════════════════════════════════════ */

const QuickBook = (() => {
    const TOTAL_STEPS = 4;
    const $ = (id) => document.getElementById(id);

    const state = {
        step: 1,
        customer: null,        // search result {id, phone, name, address, lat, lng, active_bookings}
        isNew: false,
        results: [],
        category: null,        // categories API row
        categories: [],
        categoriesKey: '',     // lat|lng|customer the categories were priced for
        searchTimer: null,
        searchSeq: 0,
        submitting: false,
        locationFor: undefined, // customer id / 'new' the location fields were last filled for
    };

    // ── Small helpers ──────────────────────────────────────────────
    const panel = () => $('qb-panel');
    const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const rupees = (n) => '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
    const todayStr = () => {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };
    // Mirrors adminpanel.helpers.normalize_phone.
    const normalizePhone = (raw) => {
        let digits = String(raw || '').replace(/\D/g, '');
        if (digits.length === 12 && digits.startsWith('91')) digits = digits.slice(2);
        else if (digits.length === 11 && digits.startsWith('0')) digits = digits.slice(1);
        return /^[6-9]\d{9}$/.test(digits) ? digits : '';
    };

    function el(tag, attrs = {}, ...children) {
        const node = document.createElement(tag);
        Object.entries(attrs).forEach(([k, v]) => {
            if (k === 'class') node.className = v;
            else if (k === 'text') node.textContent = v;
            else node.setAttribute(k, v);
        });
        children.flat().forEach(c => c != null && node.append(c));
        return node;
    }

    function showError(step, message, link) {
        const box = $(`qb-step${step}-error`);
        const span = box.querySelector('span');
        span.replaceChildren(document.createTextNode(message));
        if (link) span.append(' ', el('a', { href: link.url, class: 'qb-link', target: '_blank', rel: 'noopener', text: link.text }));
        box.classList.add('active');
    }
    const clearErrors = () => document.querySelectorAll('#qb-panel .qb-error').forEach(e => e.classList.remove('active'));

    async function getJson(url) {
        const resp = await fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
        const data = await resp.json().catch(() => ({ error: 'Session expired. Reload the page.' }));
        if (!resp.ok || data.success === false) throw new Error(data.error || 'Request failed.');
        return data;
    }

    // ── Open / close / reset ───────────────────────────────────────
    function open() {
        reset();
        $('qb-overlay').classList.add('active');
        panel().classList.add('active');
        panel().setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        setTimeout(() => $('qb-search').focus(), 350);
    }

    function close() {
        if (state.submitting) return;
        $('qb-overlay').classList.remove('active');
        panel().classList.remove('active');
        panel().setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    }

    function reset() {
        Object.assign(state, {
            step: 1, customer: null, isNew: false, results: [], category: null, categoriesKey: '',
            submitting: false, locationFor: undefined,
        });
        $('qb-search').value = '';
        $('qb-search-results').replaceChildren();
        $('qb-search-loading').hidden = true;
        $('qb-new-toggle-wrap').hidden = true;
        $('qb-new-form').hidden = true;
        $('qb-new-phone').value = '';
        $('qb-new-name').value = '';
        $('qb-categories').replaceChildren();
        $('qb-job').hidden = true;
        $('qb-quantity').value = '1';
        $('qb-unit-price').value = '';
        $('qb-date').value = todayStr();
        $('qb-date').min = todayStr();
        $('qb-note').value = '';
        $('qb-save-location').checked = false;
        $('qb-submit-loading').hidden = true;
        $('qb-success').classList.remove('active');
        $('qb-footer').style.display = 'flex';
        $('qb-next-btn').disabled = false;
        const picker = locationPicker(false);
        if (picker) picker.setValue(null, null, '');
        else { $('qb-lat').value = ''; $('qb-lng').value = ''; $('qb-address').value = ''; }
        render();
    }

    // ── Navigation ─────────────────────────────────────────────────
    async function next() {
        if (state.submitting) return;
        clearErrors();
        if (!validate(state.step)) return;
        if (state.step === TOTAL_STEPS) { submit(); return; }
        state.step += 1;
        render();
        await enterStep(state.step);
    }

    function prev() {
        if (state.submitting || state.step <= 1) return;
        state.step -= 1;
        render();
        enterStep(state.step);
    }

    function render() {
        for (let i = 1; i <= TOTAL_STEPS; i++) $(`qb-step-${i}`).classList.toggle('active', i === state.step);
        $('qb-progress').style.width = (state.step / TOTAL_STEPS * 100) + '%';
        document.querySelectorAll('#qb-stepper li').forEach(li => {
            const n = Number(li.dataset.step);
            li.classList.toggle('active', n === state.step);
            li.classList.toggle('done', n < state.step);
        });
        $('qb-back-btn').style.visibility = state.step > 1 ? 'visible' : 'hidden';
        $('qb-next-btn').textContent = state.step === TOTAL_STEPS ? 'Confirm booking' : 'Next';
        $('qb-subtitle').textContent = state.customer
            ? `For ${state.customer.name || state.customer.phone}`
            : 'Instant booking from a phone call';
        clearErrors();
    }

    async function enterStep(step) {
        if (step === 2) enterLocation();
        if (step === 3) await loadCategories();
        if (step === 4) buildReview();
    }

    function validate(step) {
        if (step === 1) {
            if (state.isNew) {
                const phone = normalizePhone($('qb-new-phone').value);
                if (!phone) { showError(1, 'Enter a valid 10-digit mobile number.'); return false; }
                state.customer = { id: null, phone, name: $('qb-new-name').value.trim(), address: '', lat: null, lng: null, active_bookings: [] };
                return true;
            }
            if (!state.customer) { showError(1, 'Select the caller from the results, or add them as a new customer.'); return false; }
            if (!state.customer.is_active) { showError(1, 'This account is deactivated. Reactivate it from Users first.'); return false; }
            return true;
        }
        if (step === 2) {
            if (coords().lat === null) { showError(2, 'Pin the field on the map (or search for the village) so nearby providers can be found.'); return false; }
            if (!$('qb-address').value.trim()) { showError(2, 'Enter the service address.'); return false; }
            return true;
        }
        if (step === 3) {
            if (!state.category) { showError(3, 'Select the machinery category.'); return false; }
            if (state.category.open_booking) {
                showError(3, 'This customer already has an open order in this category.', { url: state.category.open_booking.url, text: 'Open it' });
                return false;
            }
            const qty = Number($('qb-quantity').value);
            if (!Number.isInteger(qty) || qty < 1) { showError(3, 'Quantity must be a whole number of at least 1.'); return false; }
            if (!(Number($('qb-unit-price').value) > 0)) { showError(3, 'Unit price must be greater than zero.'); return false; }
            const date = $('qb-date').value;
            if (date && date < todayStr()) { showError(3, 'Work date cannot be in the past.'); return false; }
            return true;
        }
        return true;
    }

    // ── Step 1: customer search ────────────────────────────────────
    function onSearchInput() {
        const query = $('qb-search').value.trim();
        state.customer = null;
        state.isNew = false;
        $('qb-new-form').hidden = true;
        clearErrors();
        render();
        clearTimeout(state.searchTimer);
        const digits = query.replace(/\D/g, '');
        const isPhone = digits && !/[^\d\s+\-()]/.test(query);
        if ((isPhone && digits.length < 3) || (!isPhone && query.length < 2)) {
            state.searchSeq++;  // drop any search still in flight
            $('qb-search-results').replaceChildren();
            $('qb-search-loading').hidden = true;
            $('qb-new-toggle-wrap').hidden = !query;
            return;
        }
        $('qb-search-loading').hidden = false;
        state.searchTimer = setTimeout(() => search(query), 300);
    }

    async function search(query) {
        const seq = ++state.searchSeq;
        const url = new URL(panel().dataset.searchUrl, window.location.origin);
        url.searchParams.set('q', query);
        try {
            const data = await getJson(url);
            if (seq !== state.searchSeq) return;  // a newer search replaced this one
            renderResults(data.users || [], query);
        } catch (err) {
            if (seq === state.searchSeq) showError(1, err.message);
        } finally {
            if (seq === state.searchSeq) $('qb-search-loading').hidden = true;
        }
    }

    function renderResults(users, query) {
        const list = $('qb-search-results');
        list.replaceChildren();
        state.results = users;
        if (!users.length) {
            list.append(el('div', { class: 'qb-empty' },
                el('p', { class: 'qb-empty-title', text: 'No account found' }),
                el('p', { text: 'Add the caller as a new customer.' })));
            if (normalizePhone(query)) toggleNew(true, normalizePhone(query));
        }
        users.forEach((u, index) => {
            const initials = (u.name || '').trim().slice(0, 2).toUpperCase() || u.phone.slice(-2);
            const open = u.active_bookings || [];
            const card = el('button', { type: 'button', class: 'qb-user-card', 'data-index': String(index), 'aria-pressed': 'false' },
                el('span', { class: 'qb-avatar', text: initials }),
                el('span', { class: 'qb-user-meta' },
                    el('span', { class: 'qb-user-name', text: u.name || 'No name' }),
                    el('span', { class: 'qb-user-line', text: `${u.phone} · ${u.role_label}` }),
                    u.address ? el('span', { class: 'qb-user-line qb-muted', text: '📍 ' + u.address }) : null,
                    open.length ? el('span', { class: 'qb-user-line qb-warn', text: 'Open: ' + open.map(b => `${b.category} (${b.status_label})`).join(', ') }) : null,
                    u.is_active ? null : el('span', { class: 'qb-user-line qb-warn', text: 'Account deactivated' })));
            list.append(card);
        });
        $('qb-new-toggle-wrap').hidden = false;
    }

    function selectUser(index) {
        const user = state.results[index];
        if (!user) return;
        state.customer = user;
        state.isNew = false;
        $('qb-new-form').hidden = true;
        document.querySelectorAll('#qb-search-results .qb-user-card').forEach(card => {
            const on = Number(card.dataset.index) === index;
            card.classList.toggle('selected', on);
            card.setAttribute('aria-pressed', String(on));
        });
        render();
    }

    function toggleNew(force, phone) {
        const show = typeof force === 'boolean' ? force : $('qb-new-form').hidden;
        $('qb-new-form').hidden = !show;
        state.isNew = show;
        if (!show) return;
        state.customer = null;
        document.querySelectorAll('#qb-search-results .qb-user-card').forEach(c => {
            c.classList.remove('selected');
            c.setAttribute('aria-pressed', 'false');
        });
        const typed = phone || normalizePhone($('qb-search').value);
        if (typed && !$('qb-new-phone').value) $('qb-new-phone').value = typed;
        if (force !== true) setTimeout(() => ($('qb-new-phone').value ? $('qb-new-name') : $('qb-new-phone')).focus(), 50);
        render();
    }

    // ── Step 2: location ───────────────────────────────────────────
    function locationPicker(start = true) {
        const root = $('qb-location');
        if (!window.FarmoLocationPicker) return null;
        if (!start && !root._farmoPicker) return null;
        return window.FarmoLocationPicker.init(root);
    }

    function coords() {
        const lat = parseFloat($('qb-lat').value);
        const lng = parseFloat($('qb-lng').value);
        const ok = isFinite(lat) && isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
        return ok ? { lat, lng } : { lat: null, lng: null };
    }

    function enterLocation() {
        const picker = locationPicker();
        const who = state.isNew ? 'new' : state.customer.id;
        if (state.locationFor !== who) {
            // Start from the caller's saved address; the agent confirms or moves the pin.
            const c = state.customer;
            if (picker) picker.setValue(c.lat, c.lng, c.address);
            else { $('qb-lat').value = c.lat ?? ''; $('qb-lng').value = c.lng ?? ''; $('qb-address').value = c.address || ''; }
            state.locationFor = who;
            $('qb-save-location-wrap').hidden = state.isNew;
            $('qb-save-location').checked = !state.isNew && (c.lat === null || c.lng === null);
        }
        if (picker) setTimeout(() => { picker.refresh(); if (coords().lat === null) picker.focusSearch(); }, 50);
    }

    // ── Step 3: categories & job ───────────────────────────────────
    async function loadCategories() {
        const { lat, lng } = coords();
        const customerId = state.customer && state.customer.id ? state.customer.id : '';
        const key = `${lat}|${lng}|${customerId}`;
        if (key === state.categoriesKey && state.categories.length) return;

        $('qb-categories').replaceChildren();
        $('qb-cat-loading').hidden = false;
        const url = new URL(panel().dataset.categoriesUrl, window.location.origin);
        url.searchParams.set('lat', lat);
        url.searchParams.set('lng', lng);
        if (customerId) url.searchParams.set('customer_id', customerId);
        try {
            const data = await getJson(url);
            state.categories = data.categories || [];
            state.categoriesKey = key;
            // Keep the selection when it is still offered; its price may differ at the new spot.
            const previous = state.category && state.categories.find(c => c.id === state.category.id);
            state.category = null;
            renderCategories();
            if (previous) selectCategory(previous.id);
            else $('qb-job').hidden = true;
        } catch (err) {
            showError(3, err.message);
        } finally {
            $('qb-cat-loading').hidden = true;
        }
    }

    function renderCategories() {
        const list = $('qb-categories');
        list.replaceChildren();
        if (!state.categories.length) {
            list.append(el('div', { class: 'qb-empty' },
                el('p', { class: 'qb-empty-title', text: 'No category takes instant bookings' }),
                el('p', { text: 'Turn on instant booking for a category in Django admin.' })));
            return;
        }
        state.categories.forEach(c => {
            const reach = c.providers_nearby === 0
                ? el('span', { class: 'qb-pill qb-pill-warn', text: `No providers within ${c.radius_km} km` })
                : el('span', { class: 'qb-pill', text: `${c.providers_nearby} provider${c.providers_nearby === 1 ? '' : 's'} nearby` });
            const card = el('button', { type: 'button', class: 'qb-cat-card' + (c.open_booking ? ' blocked' : ''), 'data-id': String(c.id), role: 'radio', 'aria-checked': 'false' },
                el('span', { class: 'qb-cat-main' },
                    el('span', { class: 'qb-cat-name', text: c.name }),
                    el('span', { class: 'qb-cat-meta' }, reach, c.zone_name ? el('span', { class: 'qb-muted', text: `${c.zone_name} price` }) : null),
                    c.open_booking ? el('span', { class: 'qb-cat-open', text: `Open order ${c.open_booking.booking_id} (${c.open_booking.status_label})` }) : null),
                el('span', { class: 'qb-cat-price' },
                    el('strong', { text: rupees(c.price) }),
                    el('span', { class: 'qb-muted', text: c.price_unit })));
            list.append(card);
        });
    }

    function selectCategory(id) {
        const category = state.categories.find(c => c.id === id);
        if (!category) return;
        const switched = !state.category || state.category.id !== id;
        state.category = category;
        document.querySelectorAll('#qb-categories .qb-cat-card').forEach(card => {
            const on = Number(card.dataset.id) === id;
            card.classList.toggle('selected', on);
            card.setAttribute('aria-checked', String(on));
        });
        clearErrors();
        if (category.open_booking) {
            showError(3, 'This customer already has an open order in this category.', { url: category.open_booking.url, text: 'Open it' });
        }
        $('qb-job').hidden = false;
        $('qb-unit-label').textContent = category.price_unit;
        if (switched || !$('qb-unit-price').value) $('qb-unit-price').value = category.price;
        updateTotal();
    }

    function updateTotal() {
        const qty = Number($('qb-quantity').value) || 0;
        const price = Number($('qb-unit-price').value) || 0;
        $('qb-total').textContent = rupees(qty * price);
        const hint = $('qb-price-hint');
        if (!state.category) { hint.textContent = ''; return; }
        const overridden = price > 0 && price !== Number(state.category.price);
        hint.textContent = overridden
            ? `Agent price · system ${rupees(state.category.price)}`
            : (state.category.zone_name ? `${state.category.zone_name} zone price` : 'Standard price');
        hint.classList.toggle('qb-override', overridden);
    }

    // ── Step 4: review ─────────────────────────────────────────────
    function buildReview() {
        const c = state.customer;
        const cat = state.category;
        const qty = Number($('qb-quantity').value);
        const price = Number($('qb-unit-price').value);
        const overridden = price !== Number(cat.price);
        const note = $('qb-note').value.trim();
        const rows = [
            ['Customer', `${c.name || 'No name'} · ${c.phone}`],
            state.isNew ? ['New account', 'Created when you confirm', 'qb-review-note'] : null,
            ['Machinery', cat.name],
            ['Address', $('qb-address').value.trim()],
            ['Quantity', `${qty} · ${cat.price_unit}`],
            ['Unit price', rupees(price) + (overridden ? ` (system ${rupees(cat.price)})` : '')],
            ['Work date', $('qb-date').value || todayStr()],
            note ? ['Work description', note] : null,
            !state.isNew && $('qb-save-location').checked ? ['Customer address', 'Will be updated to this location', 'qb-review-note'] : null,
        ].filter(Boolean);
        $('qb-review').replaceChildren(
            ...rows.map(([label, value, cls]) => el('div', { class: 'qb-review-row ' + (cls || '') },
                el('span', { class: 'qb-review-label', text: label }),
                el('span', { class: 'qb-review-value', text: value }))),
            el('div', { class: 'qb-review-row qb-review-total' },
                el('span', { class: 'qb-review-label', text: 'Total' }),
                el('span', { class: 'qb-review-value', text: rupees(qty * price) })));

        const reach = $('qb-reach');
        reach.className = 'qb-reach' + (cat.providers_nearby ? '' : ' warn');
        reach.textContent = cat.providers_nearby
            ? `⚡ Instant booking: ${cat.providers_nearby} provider${cat.providers_nearby === 1 ? '' : 's'} within ${cat.radius_km} km will be notified now.`
            : `⚡ Instant booking: no provider is within ${cat.radius_km} km right now. The order is still created; assign someone from the booking page.`;
    }

    // ── Submit ─────────────────────────────────────────────────────
    async function submit() {
        if (state.submitting) return;
        state.submitting = true;
        $('qb-next-btn').disabled = true;
        $('qb-submit-loading').hidden = false;
        const { lat, lng } = coords();
        const c = state.customer;
        const payload = {
            customer_id: c.id || '',
            phone: c.phone,
            name: c.name || '',
            category_id: state.category.id,
            address: $('qb-address').value.trim(),
            lat, lng,
            save_location: !state.isNew && $('qb-save-location').checked,
            quantity: Number($('qb-quantity').value),
            unit_price: $('qb-unit-price').value,
            scheduled_date: $('qb-date').value,
            note: $('qb-note').value.trim(),
        };
        try {
            const resp = await fetch(panel().dataset.createUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify(payload),
            });
            const data = await resp.json().catch(() => ({ error: 'Session expired. Reload the page.' }));
            if (!resp.ok || !data.success) {
                const link = data.booking ? { url: data.booking.url, text: 'Open it' } : null;
                throw Object.assign(new Error(data.error || 'Could not place the booking.'), { link });
            }
            state.submitting = false;
            showSuccess(data);
        } catch (err) {
            state.submitting = false;
            showError(4, err.message, err.link);
            $('qb-next-btn').disabled = false;
        } finally {
            $('qb-submit-loading').hidden = true;
        }
    }

    function showSuccess(data) {
        for (let i = 1; i <= TOTAL_STEPS; i++) $(`qb-step-${i}`).classList.remove('active');
        $('qb-footer').style.display = 'none';
        $('qb-progress').style.width = '100%';
        $('qb-success-id').textContent = `Booking ${data.booking_id} · ${rupees(data.total_amount)}`;
        $('qb-success-order').textContent = data.order_number || '—';
        $('qb-success-reach').textContent = data.providers_notified
            ? `${data.providers_notified} nearby provider${data.providers_notified === 1 ? '' : 's'} notified.`
            : 'No nearby provider was notified. Assign one from the booking page.';
        $('qb-success-link').href = data.detail_url;
        $('qb-success').classList.add('active');
    }

    // ── Wiring ─────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        if (!panel()) return;
        $('qb-search').addEventListener('input', onSearchInput);
        $('qb-search').addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            if (state.results.length === 1) selectUser(0);
        });
        $('qb-search-results').addEventListener('click', (e) => {
            const card = e.target.closest('.qb-user-card');
            if (card) selectUser(Number(card.dataset.index));
        });
        $('qb-new-toggle').addEventListener('click', () => toggleNew());
        $('qb-categories').addEventListener('click', (e) => {
            const card = e.target.closest('.qb-cat-card');
            if (card) selectCategory(Number(card.dataset.id));
        });
        $('qb-quantity').addEventListener('input', updateTotal);
        $('qb-unit-price').addEventListener('input', updateTotal);
        $('qb-location').addEventListener('lp:change', () => {
            if (coords().lat !== null) $('qb-step2-error').classList.remove('active');
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && panel().classList.contains('active')) close();
        });
    });

    return { open, close, reset, next, prev };
})();
