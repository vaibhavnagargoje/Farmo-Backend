/* Reusable address search + map picker. Markup lives in includes/location_picker.html
   (and the Quick Book panel). Pickers marked data-lp-lazy are started by their owner
   through window.FarmoLocationPicker.init(root) once they are visible. */
(function () {
  'use strict';

  // The script can be included more than once on a page (base.html + a page include).
  if (window.FarmoLocationPicker) return;

  var INDIA_CENTER = { lat: 20.5937, lng: 78.9629 };
  var pending = [];
  var loadState = 'idle';

  function placesReady() {
    return window.google && google.maps && google.maps.places;
  }

  function flush() {
    loadState = 'ready';
    pending.splice(0).forEach(function (fn) { fn(); });
  }

  function whenMapsReady(key, callback) {
    if (placesReady()) { callback(); return; }
    pending.push(callback);
    if (loadState !== 'idle') return;
    loadState = 'loading';

    function inject() {
      window.__farmoLocationPickerReady = flush;
      var script = document.createElement('script');
      script.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key) +
        '&libraries=places&callback=__farmoLocationPickerReady';
      script.async = true;
      document.head.appendChild(script);
    }

    // Another page script (e.g. Map View) may already be loading Maps with Places:
    // wait for it instead of loading the API twice.
    if (document.querySelector('script[src*="maps.googleapis.com/maps/api/js"]')) {
      var tries = 0;
      var timer = setInterval(function () {
        if (placesReady()) { clearInterval(timer); flush(); }
        else if (++tries > 150) { clearInterval(timer); inject(); }
      }, 100);
      return;
    }
    inject();
  }

  function setupPicker(root) {
    function part(name) { return root.querySelector('[data-lp="' + name + '"]'); }

    var search = part('search');
    var addressEl = part('address');
    var latEl = part('lat');
    var lngEl = part('lng');
    var mapEl = part('map');
    var gpsBtn = part('gps-btn');
    var gpsLabel = part('gps-label');
    var statusEl = part('status');
    var map = null;
    var marker = null;
    var geocoder = null;

    function showStatus(type, message) {
      if (!statusEl) return;
      statusEl.className = 'text-xs px-3 py-2 rounded-xl ' + (type === 'success'
        ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
        : 'bg-rose-50 text-rose-800 border border-rose-200');
      statusEl.textContent = message;
    }

    function changed() {
      root.dispatchEvent(new CustomEvent('lp:change', { bubbles: true }));
    }

    function setCoords(lat, lng) {
      latEl.value = lat.toFixed(6);
      lngEl.value = lng.toFixed(6);
      changed();
    }

    function moveMap(latLng, zoom) {
      if (!map) return;
      marker.setPosition(latLng);
      map.setCenter(latLng);
      map.setZoom(zoom || 16);
    }

    function reverseGeocode(lat, lng) {
      if (!geocoder) return;
      geocoder.geocode({ location: { lat: lat, lng: lng } }, function (results, status) {
        if (status === 'OK' && results[0]) {
          addressEl.value = results[0].formatted_address;
          changed();
        }
      });
    }

    function applyPlace(latLng, address) {
      if (address) addressEl.value = address;
      setCoords(latLng.lat(), latLng.lng());
      moveMap(latLng, 16);
    }

    function currentCoords() {
      var lat = parseFloat(latEl.value);
      var lng = parseFloat(lngEl.value);
      if (isFinite(lat) && isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
        return { lat: lat, lng: lng };
      }
      return null;
    }

    function syncMarkerFromInputs() {
      var coords = currentCoords();
      if (map && coords) moveMap(new google.maps.LatLng(coords.lat, coords.lng), 15);
    }

    function initMaps() {
      geocoder = new google.maps.Geocoder();
      var coords = currentCoords();

      if (mapEl) {
        var center = coords || INDIA_CENTER;
        map = new google.maps.Map(mapEl, {
          center: center,
          zoom: coords ? 15 : 5,
          streetViewControl: false,
          fullscreenControl: true,
          styles: [{ featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] }]
        });
        marker = new google.maps.Marker({ position: center, map: map, draggable: true, title: 'Drag to set location' });

        marker.addListener('dragend', function () {
          var pos = marker.getPosition();
          setCoords(pos.lat(), pos.lng());
          reverseGeocode(pos.lat(), pos.lng());
        });
        map.addListener('click', function (e) {
          marker.setPosition(e.latLng);
          setCoords(e.latLng.lat(), e.latLng.lng());
          reverseGeocode(e.latLng.lat(), e.latLng.lng());
        });
      }

      var autocomplete = new google.maps.places.Autocomplete(search, {
        types: ['geocode', 'establishment'],
        componentRestrictions: { country: 'in' },
        fields: ['geometry', 'formatted_address', 'name']
      });
      if (map) autocomplete.bindTo('bounds', map);

      autocomplete.addListener('place_changed', function () {
        var place = autocomplete.getPlace();
        if (place.geometry && place.geometry.location) {
          applyPlace(place.geometry.location, place.formatted_address || place.name);
          return;
        }
        // Enter pressed without picking a suggestion: geocode the typed text.
        if (!place.name) return;
        geocoder.geocode({ address: place.name, region: 'in' }, function (results, status) {
          if (status === 'OK' && results[0]) {
            applyPlace(results[0].geometry.location, results[0].formatted_address);
          } else {
            showStatus('error', 'No places found. Try another term.');
          }
        });
      });
    }

    latEl.addEventListener('input', function () { syncMarkerFromInputs(); changed(); });
    lngEl.addEventListener('input', function () { syncMarkerFromInputs(); changed(); });

    // Stop Enter in the search box from submitting the surrounding form.
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') e.preventDefault();
    });

    if (gpsBtn) {
      gpsBtn.addEventListener('click', function () {
        if (!navigator.geolocation) { showStatus('error', 'Geolocation not supported by browser.'); return; }
        gpsBtn.disabled = true;
        gpsLabel.textContent = 'Detecting GPS...';
        navigator.geolocation.getCurrentPosition(
          function (p) {
            var lat = p.coords.latitude;
            var lng = p.coords.longitude;
            setCoords(lat, lng);
            if (map) moveMap(new google.maps.LatLng(lat, lng), 16);
            reverseGeocode(lat, lng);
            gpsBtn.disabled = false;
            gpsLabel.textContent = 'Detect from Device GPS';
            showStatus('success', 'Detected: ' + lat.toFixed(6) + ', ' + lng.toFixed(6) +
              ' (~' + Math.round(p.coords.accuracy) + 'm accuracy)');
          },
          function (err) {
            gpsBtn.disabled = false;
            gpsLabel.textContent = 'Detect from Device GPS';
            showStatus('error', err.code === 1 ? 'Location permission denied in browser.' : 'GPS signal unavailable.');
          },
          { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
      });
    }

    var api = {
      /** Fill the fields (and move the pin) from known values; blanks clear them. */
      setValue: function (lat, lng, address) {
        latEl.value = lat == null ? '' : Number(lat).toFixed(6);
        lngEl.value = lng == null ? '' : Number(lng).toFixed(6);
        addressEl.value = address || '';
        search.value = '';
        var coords = currentCoords();
        if (map) {
          if (coords) moveMap(new google.maps.LatLng(coords.lat, coords.lng), 15);
          else { marker.setPosition(INDIA_CENTER); map.setCenter(INDIA_CENTER); map.setZoom(5); }
        }
        changed();
      },
      /** Re-centre after the picker becomes visible (e.g. a panel step opens). */
      refresh: function () {
        if (!map) return;
        var coords = currentCoords();
        map.setCenter(coords || INDIA_CENTER);
      },
      focusSearch: function () { search.focus(); }
    };

    var key = root.getAttribute('data-maps-key');
    if (!key) {
      showStatus('error', 'Google Maps API key is not configured. Enter coordinates manually.');
      return api;
    }
    whenMapsReady(key, initMaps);
    return api;
  }

  window.FarmoLocationPicker = {
    init: function (root) {
      if (!root._farmoPicker) root._farmoPicker = setupPicker(root);
      return root._farmoPicker;
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.farmo-location-picker:not([data-lp-lazy])').forEach(function (root) {
      window.FarmoLocationPicker.init(root);
    });
  });
})();
