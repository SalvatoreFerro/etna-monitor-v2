(() => {
  // Front-end controller for the Sentiero detail view.
  const container = document.querySelector('.sentieri-detail');
  if (!container) {
    return;
  }

  const slug = container.dataset.trailSlug;
  const startLat = Number(container.dataset.startLat);
  const startLng = Number(container.dataset.startLng);
  const loader = document.getElementById('sentiero-loader');
  const mapLabel = document.getElementById('sentiero-map-label');
  const poiLists = document.getElementById('sentiero-poi-lists');

  const categoryLabels = {
    point: 'Punti di interesse',
    cave: 'Grotte',
    mount: 'Monti',
    hut: 'Rifugi',
  };

  const categoryColors = {
    point: '#38bdf8',
    cave: '#a78bfa',
    mount: '#f97316',
    hut: '#34d399',
  };

  const state = { point: true, cave: true, mount: true, hut: true };
  const toggleButtons = Array.from(document.querySelectorAll('.sentieri-toggle'));

  const map = window.EtnaLeaflet?.createEtnaMap('sentiero-map', {
    center: Number.isFinite(startLat) && Number.isFinite(startLng) ? [startLat, startLng] : [37.751, 15.0],
    zoom: 12,
    mapOptions: { scrollWheelZoom: true },
  });

  const poiLayers = {
    point: window.L?.layerGroup(),
    cave: window.L?.layerGroup(),
    mount: window.L?.layerGroup(),
    hut: window.L?.layerGroup(),
  };

  const setLoading = (value) => {
    if (loader) {
      loader.style.display = value ? 'flex' : 'none';
    }
  };

  const setMapLabel = (text) => {
    if (mapLabel) {
      mapLabel.textContent = text;
    }
  };

  const updatePoiLayersVisibility = () => {
    if (!map) {
      return;
    }
    Object.entries(poiLayers).forEach(([category, layer]) => {
      if (!layer) {
        return;
      }
      if (state[category]) {
        layer.addTo(map);
      } else {
        layer.removeFrom(map);
      }
    });
  };

  toggleButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const category = button.dataset.layer;
      state[category] = !state[category];
      button.classList.toggle('is-active', state[category]);
      updatePoiLayersVisibility();
    });
  });

  const buildPoiLists = (poiByCategory) => {
    if (!poiLists) {
      return;
    }
    poiLists.innerHTML = '';

    Object.entries(categoryLabels).forEach(([category, label]) => {
      const items = poiByCategory[category] || [];
      const wrapper = document.createElement('div');
      wrapper.className = 'sentieri-poi-category';
      wrapper.innerHTML = `<h3>${label} (${items.length})</h3>`;
      const list = document.createElement('div');
      list.className = 'sentieri-poi-list';

      if (!items.length) {
        list.innerHTML = '<span class="muted">Nessun punto disponibile.</span>';
      } else {
        items.forEach((poi) => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'sentieri-poi-item';
          item.textContent = poi.name || 'POI';
          item.addEventListener('click', () => {
            if (poi.marker && map) {
              map.setView(poi.marker.getLatLng(), 14, { animate: true });
              poi.marker.openPopup();
            }
          });
          list.appendChild(item);
        });
      }
      wrapper.appendChild(list);
      poiLists.appendChild(wrapper);
    });
  };

  const loadData = async () => {
    setLoading(true);
    setMapLabel('Caricamento sentiero...');

    try {
      const [trailsRes, poisRes] = await Promise.all([
        fetch('/api/sentieri/trails', { headers: { Accept: 'application/json' } }),
        fetch('/api/sentieri/pois', { headers: { Accept: 'application/json' } }),
      ]);

      if (!trailsRes.ok || !poisRes.ok) {
        throw new Error('GeoJSON non disponibile');
      }

      const trailsData = await trailsRes.json();
      const poisData = await poisRes.json();

      const trailFeature = trailsData.features?.find((feature) => feature?.properties?.slug === slug);
      if (!trailFeature) {
        throw new Error('Sentiero non trovato');
      }

      if (map && window.L) {
        const trailLayer = window.L.geoJSON(trailFeature, {
          style: () => ({ color: '#38bdf8', weight: 4, opacity: 0.85 }),
        }).addTo(map);

        const bounds = trailLayer.getBounds();
        if (bounds && bounds.isValid()) {
          map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
        }

        const poiByCategory = { point: [], cave: [], mount: [], hut: [] };
        poisData.features
          ?.filter((feature) => feature?.properties?.trail_slug === slug)
          .forEach((feature) => {
            const props = feature.properties || {};
            const category = props.category;
            const coords = feature.geometry?.coordinates;
            if (!category || !poiLayers[category] || !Array.isArray(coords)) {
              return;
            }
            const marker = window.L.circleMarker([coords[1], coords[0]], {
              radius: 6,
              color: '#0f172a',
              weight: 1,
              fillColor: categoryColors[category] || '#38bdf8',
              fillOpacity: 0.9,
            });
            marker.bindPopup(`<strong>${props.name || 'POI'}</strong><br>${props.description || ''}`);
            poiLayers[category].addLayer(marker);
            poiByCategory[category].push({ name: props.name, marker });
          });

        updatePoiLayersVisibility();
        buildPoiLists(poiByCategory);
      }

      setMapLabel('Sentiero e punti di interesse');
    } catch (error) {
      if (poiLists) {
        poiLists.innerHTML = '<div class="sentieri-note">POI non disponibili al momento.</div>';
      }
      setMapLabel('Dati non disponibili');
    } finally {
      setLoading(false);
    }
  };

  loadData();
})();
