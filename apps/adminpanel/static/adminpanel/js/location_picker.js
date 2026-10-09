/* Reusable address search + map picker. Markup lives in includes/location_picker.html. */
(function () {
  'use strict';

  var INDIA_CENTER = { lat: 20.5937, lng: 78.9629 };
  var pending = [];
  var loadState = 'idle';

  function whenMapsReady(key, callback) {
    if (window.google && google.maps && google.maps.places) { callback(); return; }
    pending.push(callback);
    if (loadState === 'loading') return;
    loadState = 'loading';
    window.__farmoLocationPickerReady = function () {
      loadState = 'ready';
      pending.splice(0).forEach(function (fn) { fn(); });
    };
    var script = document.createElement('script');
    script.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key) +
      '&libraries=places&callback=__farmoLocationPickerReady';
    script.async = true;
    document.head.appendChild(script);
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
      statusEl.className = 'text-xs px-3 py-2 rounded-xl ' + (type === 'success'
        ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
        : 'bg-rose-50 text-rose-800 border border-rose-200');
      statusEl.textContent = message;
    }

    function setCoords(lat, lng) {
      latEl.value = lat.toFixed(6);
      lngEl.value = lng.toFixed(6);
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
        if (status === 'OK' && results[0]) addressEl.value = results[0].formatted_address;
      });
    }

    function applyPlace(latLng, address) {
      setCoords(latLng.lat(), latLng.lng());
      moveMap(latLng, 16);
      if (address) addressEl.value = address;
    }

    function syncMarkerFromInputs() {
      var lat = parseFloat(latEl.value);
      var lng = parseFloat(lngEl.value);
      if (map && isFinite(lat) && isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
        moveMap(new google.maps.LatLng(lat, lng), 15);
      }
    }

    function initMaps() {
      geocoder = new google.maps.Geocoder();
      var lat = parseFloat(latEl.value);
      var lng = parseFloat(lngEl.value);
      var hasLocation = isFinite(lat) && isFinite(lng);

      if (mapEl) {
        var center = hasLocation ? { lat: lat, lng: lng } : INDIA_CENTER;
        map = new google.maps.Map(mapEl, {
          center: center,
          zoom: hasLocation ? 15 : 5,
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

    latEl.addEventListener('input', syncMarkerFromInputs);
    lngEl.addEventListener('input', syncMarkerFromInputs);

    // Stop Enter in the search box from submitting the surrounding form.
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') e.preventDefault();
    });

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

    var key = root.getAttribute('data-maps-key');
    if (!key) {
      showStatus('error', 'Google Maps API key is not configured. Enter coordinates manually.');
      return;
    }
    whenMapsReady(key, initMaps);
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.farmo-location-picker').forEach(setupPicker);
  });
})();
