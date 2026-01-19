(() => {
  // Front-end controller for the Sentieri listing/map page.
  const listEl = document.getElementById('sentieri-list');
  const loader = document.getElementById('sentieri-loader');
  const kpiTrails = document.getElementById('sentieri-count');
  const kpiKm = document.getElementById('sentieri-km');
  const kpiPois = document.getElementById('sentieri-pois');
  const mapLabel = document.getElementById('sentieri-map-label');
  const mapPanel = document.querySelector('.sentieri-panel--map');
  const mapToggle = document.querySelector('[data-toggle-map]');

  if (!listEl) {
    return;
  }

  const state = {
    trails: true,
    point: true,
    cave: true,
    mount: true,
    hut: true,
  };

  const categoryLabels = {
    point: 'Punti',
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

  const toggleButtons = Array.from(document.querySelectorAll('.sentieri-toggle'));

  const map = window.EtnaLeaflet?.createEtnaMap('sentieri-map', {
    center: [37.751, 15.0],
    zoom: 10,
    mapOptions: { scrollWheelZoom: true },
  });

  let trailLayer = null;
  const poiLayers = {
    point: window.L?.layerGroup(),
    cave: window.L?.layerGroup(),
    mount: window.L?.layerGroup(),
    hut: window.L?.layerGroup(),
  };
  let selectedLayer = null;
  let popup = null;

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

  const setKpis = (stats) => {
    if (!stats) {
      return;
    }
    if (kpiTrails) {
      kpiTrails.textContent = stats.trails ?? '—';
    }
    if (kpiKm) {
      kpiKm.textContent = stats.total_km != null ? `${stats.total_km}` : '—';
    }
    if (kpiPois) {
      kpiPois.textContent = stats.pois ?? '—';
    }
  };

  const resetSelection = () => {
    if (selectedLayer && selectedLayer.defaultStyle) {
      selectedLayer.setStyle(selectedLayer.defaultStyle);
    }
    selectedLayer = null;
  };

  const highlightTrail = (layer) => {
    if (!layer) {
      return;
    }
    resetSelection();
    selectedLayer = layer;
    layer.setStyle({ color: '#fb7185', weight: 5, opacity: 0.95 });
  };

  const buildCountsByTrail = (pois) => {
    const counts = {};
    pois.forEach((feature) => {
      const props = feature.properties || {};
      const slug = props.trail_slug;
      if (!slug) {
        return;
      }
      if (!counts[slug]) {
        counts[slug] = { point: 0, cave: 0, mount: 0, hut: 0 };
      }
      if (counts[slug][props.category] != null) {
        counts[slug][props.category] += 1;
      }
    });
    return counts;
  };

  const buildTrailCard = (feature, counts) => {
    const props = feature.properties || {};
    const slug = props.slug || '';
    const card = document.createElement('article');
    card.className = 'sentieri-card';
    card.dataset.slug = slug;

    const count = counts[slug] || { point: 0, cave: 0, mount: 0, hut: 0 };
    const totalPois = count.point + count.cave + count.mount + count.hut;
    const difficulty = props.difficulty || '—';
    const difficultyValue = typeof difficulty === 'string' ? difficulty.toLowerCase() : '';
    const isExpert = difficultyValue.includes('esperti');
    let difficultyBadge = '⛰️ Media';
    if (difficultyValue.includes('facile')) {
      difficultyBadge = '🥾 Facile';
    } else if (difficultyValue.includes('esperti')) {
      difficultyBadge = '🧗 Esperti';
    } else if (difficultyValue.includes('media')) {
      difficultyBadge = '⛰️ Media';
    }
    const description = props.description || '';

    card.innerHTML = `
      <div class="sentieri-card-header">
        <h3 class="sentieri-card-title">${props.name || 'Sentiero'}</h3>
      </div>
      <div class="sentieri-card-meta">
        ${props.km ?? '—'} km · Difficoltà: ${difficulty}
      </div>
      <p class="sentieri-card-description">${description}</p>
      <div class="sentieri-card-badges">
        <span class="sentieri-card-pill">${difficultyBadge}</span>
        <span class="sentieri-card-pill">📍 ${totalPois} POI</span>
        ${isExpert ? '<span class="sentieri-card-pill sentieri-card-pill--guide">⚠️ Guida consigliata</span>' : ''}
      </div>
      <div class="sentieri-card-actions">
        <a href="/sentieri/${slug}">Esplora →</a>
      </div>
    `;

    return card;
  };

  const attachTrailCards = (features, counts, layerMap) => {
    listEl.innerHTML = '';
    if (!features.length) {
      listEl.innerHTML = '<div class="sentieri-note">Nessun sentiero disponibile.</div>';
      return;
    }

    features.forEach((feature) => {
      const card = buildTrailCard(feature, counts);
      const slug = card.dataset.slug;
      card.addEventListener('click', () => {
        const layer = layerMap.get(slug);
        if (!layer || !map) {
          return;
        }
        highlightTrail(layer);
        const props = feature.properties || {};
        const lat = Number(props.start_lat);
        const lng = Number(props.start_lng);
        const target = Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : null;
        if (target) {
          map.setView(target, 13, { animate: true });
        } else if (layer.getBounds) {
          map.fitBounds(layer.getBounds(), { padding: [24, 24], maxZoom: 14 });
        }
        if (!popup) {
          popup = window.L?.popup({ className: 'sentieri-popup' });
        }
        if (popup && map) {
          const content = `
            <div class="sentieri-popup">
              <strong>${props.name || 'Sentiero'}</strong>
              <div>${props.km ?? '—'} km · ${props.difficulty || '—'}</div>
              <a href="/sentieri/${slug}">Apri dettagli</a>
            </div>
          `;
          popup.setContent(content);
          if (target) {
            popup.setLatLng(target).openOn(map);
          }
        }
        document.querySelectorAll('.sentieri-card').forEach((el) => {
          el.classList.toggle('is-active', el.dataset.slug === slug);
        });
      });
      listEl.appendChild(card);
    });
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

  const updateTrailLayerVisibility = () => {
    if (!map || !trailLayer) {
      return;
    }
    if (state.trails) {
      trailLayer.addTo(map);
    } else {
      trailLayer.removeFrom(map);
    }
  };

  toggleButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const layer = button.dataset.layer;
      state[layer] = !state[layer];
      button.classList.toggle('is-active', state[layer]);
      if (layer === 'trails') {
        updateTrailLayerVisibility();
      } else {
        updatePoiLayersVisibility();
      }
    });
  });

  const toggleMapPanel = (collapsed) => {
    if (!mapPanel || !mapToggle) {
      return;
    }
    mapPanel.classList.toggle('is-collapsed', collapsed);
    mapToggle.setAttribute('aria-expanded', String(!collapsed));
    mapToggle.textContent = collapsed ? 'Mostra mappa' : 'Nascondi mappa';
    if (!collapsed && map) {
      setTimeout(() => {
        map.invalidateSize();
      }, 200);
    }
  };

  if (mapToggle && mapPanel) {
    const prefersCollapsed = window.matchMedia('(max-width: 900px)');
    toggleMapPanel(prefersCollapsed.matches);
    mapToggle.addEventListener('click', () => {
      toggleMapPanel(!mapPanel.classList.contains('is-collapsed'));
    });
    prefersCollapsed.addEventListener('change', (event) => {
      toggleMapPanel(event.matches);
    });
  }

  const loadData = async () => {
    setLoading(true);
    setMapLabel('Caricamento sentieri in corso...');

    try {
      const [trailsRes, poisRes, statsRes] = await Promise.all([
        fetch('/api/sentieri/trails', { headers: { Accept: 'application/json' } }),
        fetch('/api/sentieri/pois', { headers: { Accept: 'application/json' } }),
        fetch('/api/sentieri/stats', { headers: { Accept: 'application/json' } }),
      ]);

      if (!trailsRes.ok || !poisRes.ok) {
        throw new Error('GeoJSON non disponibile');
      }

      const trailsData = await trailsRes.json();
      const poisData = await poisRes.json();
      const statsData = statsRes.ok ? await statsRes.json() : null;

      if (!trailsData.features || !poisData.features) {
        throw new Error('GeoJSON non valido');
      }

      const statsPayload = statsData && statsData.ok ? statsData : null;
      setKpis(
        statsPayload || {
          trails: trailsData.features.length,
          pois: poisData.features.length,
          total_km: '—',
        }
      );

      if (map && window.L) {
        const layerMap = new Map();
        trailLayer = window.L.geoJSON(trailsData, {
          style: () => ({
            color: '#fb923c',
            weight: 3.5,
            opacity: 0.85,
            lineCap: 'round',
            lineJoin: 'round',
            className: 'sentieri-trail',
          }),
          onEachFeature: (feature, layer) => {
            layer.defaultStyle = {
              color: '#fb923c',
              weight: 3.5,
              opacity: 0.85,
              lineCap: 'round',
              lineJoin: 'round',
            };
            const slug = feature?.properties?.slug;
            if (slug) {
              layerMap.set(slug, layer);
            }
            layer.on('mouseover', () => {
              if (layer !== selectedLayer) {
                layer.setStyle({ weight: 5, opacity: 1, color: '#fdba74' });
              }
            });
            layer.on('mouseout', () => {
              if (layer !== selectedLayer) {
                layer.setStyle(layer.defaultStyle);
              }
            });
          },
        });

        if (state.trails) {
          trailLayer.addTo(map);
        }

        const bounds = trailLayer.getBounds();
        if (bounds && bounds.isValid()) {
          map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
        }

        poisData.features.forEach((feature) => {
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
            className: `sentieri-poi-marker sentieri-poi-marker--${category}`,
          });
          marker.bindPopup(`<strong>${props.name || 'POI'}</strong><br>${props.description || ''}`);
          poiLayers[category].addLayer(marker);
        });

        updatePoiLayersVisibility();
        updateTrailLayerVisibility();

        attachTrailCards(trailsData.features, buildCountsByTrail(poisData.features), layerMap);
      }

      setMapLabel('Sentieri e punti di interesse');
    } catch (error) {
      listEl.innerHTML = '<div class="sentieri-note">Dati sentieri non disponibili al momento.</div>';
      setMapLabel('Dati non disponibili');
    } finally {
      setLoading(false);
    }
  };

  loadData();
})();
