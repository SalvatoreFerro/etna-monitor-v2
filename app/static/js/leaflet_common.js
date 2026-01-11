(function (global) {
  const DEFAULT_CENTER = [37.751, 14.995];
  const DEFAULT_ZOOM = 10;
  const DEFAULT_TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
  const DEFAULT_TILE_ATTRIBUTION = '&copy; OpenStreetMap &copy; CARTO';

  const defaultMapOptions = {
    scrollWheelZoom: false,
    zoomControl: true,
    minZoom: 9,
    maxZoom: 16,
    attributionControl: true,
  };

  const getBrightness = (item) =>
    item?.intensity?.brightness ?? item?.bright_ti4 ?? item?.brightness ?? item?.bright_ti5 ?? null;

  const getMarkerColor = (brightness) => {
    if (brightness == null) {
      return '#facc15';
    }
    if (brightness >= 340) {
      return '#ef4444';
    }
    if (brightness >= 325) {
      return '#f97316';
    }
    return '#facc15';
  };

  const getMarkerClass = (brightness) => {
    if (brightness == null) {
      return 'hotspots-marker';
    }
    if (brightness >= 340) {
      return 'hotspots-marker hotspots-marker--high';
    }
    if (brightness >= 325) {
      return 'hotspots-marker hotspots-marker--mid';
    }
    return 'hotspots-marker';
  };

  const createEtnaMap = (containerOrId, options = {}) => {
    if (!global.L) {
      return null;
    }
    const container =
      typeof containerOrId === 'string' ? document.getElementById(containerOrId) : containerOrId;
    if (!container) {
      return null;
    }
    const mapOptions = {
      ...defaultMapOptions,
      ...(options.mapOptions || {}),
    };
    const map = global.L.map(container, mapOptions);
    global.L.tileLayer(options.tileUrl || DEFAULT_TILE_URL, {
      attribution: options.tileAttribution || DEFAULT_TILE_ATTRIBUTION,
      maxZoom: mapOptions.maxZoom ?? defaultMapOptions.maxZoom,
    }).addTo(map);

    const center = options.center || DEFAULT_CENTER;
    const zoom = options.zoom ?? DEFAULT_ZOOM;
    map.setView(center, zoom, { animate: false });

    if (options.addFirmsBadge) {
      const firmsControl = global.L.control({ position: 'topleft' });
      firmsControl.onAdd = () => {
        const badge = global.L.DomUtil.create('div', 'etna-firms-control');
        badge.innerHTML = `
          <a
            class="etna-firms-badge"
            href="https://firms.modaps.eosdis.nasa.gov/"
            target="_blank"
            rel="noopener"
            title="Fonte dati: NASA FIRMS"
          >
            <img src="https://upload.wikimedia.org/wikipedia/commons/e/e5/NASA_logo.svg" alt="NASA" />
            NASA FIRMS
          </a>
        `;
        global.L.DomEvent.disableClickPropagation(badge);
        return badge;
      };
      firmsControl.addTo(map);
    }

    return map;
  };

  const createHotspotMarker = (item, options = {}) => {
    if (!global.L || !item || item.lat == null || item.lon == null) {
      return null;
    }
    const brightness = getBrightness(item);
    return global.L.circleMarker([item.lat, item.lon], {
      radius: options.radius ?? 8,
      color: options.color ?? '#f8fafc',
      fillColor: options.fillColor ?? getMarkerColor(brightness),
      weight: options.weight ?? 2.2,
      fillOpacity: options.fillOpacity ?? 0.85,
      className: options.className ?? getMarkerClass(brightness),
    });
  };

  const addHotspotsLayer = (map, items = [], options = {}) => {
    if (!global.L || !map) {
      return { layer: null, markerMap: new Map(), bounds: null, hasPoints: false };
    }
    const layer = options.layer || global.L.layerGroup().addTo(map);
    layer.clearLayers();

    const markerMap = new Map();
    const bounds = global.L.latLngBounds([]);
    let hasPoints = false;

    const markerFactory = options.markerFactory || ((item) => createHotspotMarker(item, options.markerOptions));

    items.forEach((item, index) => {
      if (!item || item.lat == null || item.lon == null) {
        return;
      }
      const marker = markerFactory(item, index);
      if (!marker) {
        return;
      }
      marker.addTo(layer);
      markerMap.set(index, marker);
      bounds.extend([item.lat, item.lon]);
      hasPoints = true;
      if (options.onMarker) {
        options.onMarker(marker, item, index);
      }
    });

    if (hasPoints && options.fitBounds) {
      map.fitBounds(bounds, {
        padding: options.boundsPadding || [28, 28],
        maxZoom: options.maxZoom ?? 13,
        animate: false,
      });
    }

    return { layer, markerMap, bounds, hasPoints };
  };

  const normalizeBbox = (bbox) => {
    if (Array.isArray(bbox) && bbox.length === 4) {
      return bbox.map((value) => Number(value));
    }
    if (bbox && typeof bbox === 'object') {
      if (Array.isArray(bbox.bbox) && bbox.bbox.length === 4) {
        return bbox.bbox.map((value) => Number(value));
      }
      if (
        bbox.west != null &&
        bbox.south != null &&
        bbox.east != null &&
        bbox.north != null
      ) {
        return [bbox.west, bbox.south, bbox.east, bbox.north].map((value) => Number(value));
      }
    }
    return null;
  };

  const addCopernicusFootprint = (map, bbox, options = {}) => {
    if (!global.L || !map) {
      return null;
    }
    const normalized = normalizeBbox(bbox);
    if (!normalized) {
      return null;
    }
    const [minLon, minLat, maxLon, maxLat] = normalized;
    const bounds = global.L.latLngBounds(
      [minLat, minLon],
      [maxLat, maxLon]
    );
    const rectangle = global.L.rectangle(bounds, {
      color: options.color ?? '#facc15',
      fillColor: options.fillColor ?? '#facc15',
      weight: options.weight ?? 1.6,
      fillOpacity: options.fillOpacity ?? 0.12,
      dashArray: options.dashArray ?? '6 6',
      className: options.className ?? 'etna-footprint',
    }).addTo(map);

    if (options.fitBounds) {
      map.fitBounds(bounds, {
        padding: options.boundsPadding || [24, 24],
        maxZoom: options.maxZoom ?? 12,
        animate: false,
      });
    }

    return rectangle;
  };

  const addEtnaMarker = (map, options = {}) => {
    if (!global.L || !map) {
      return null;
    }
    const center = options.center || DEFAULT_CENTER;
    const marker = global.L.circleMarker(center, {
      radius: options.radius ?? 5,
      color: options.color ?? '#f8fafc',
      fillColor: options.fillColor ?? '#facc15',
      fillOpacity: options.fillOpacity ?? 0.9,
      weight: options.weight ?? 1.5,
      className: options.className ?? 'etna-marker',
    }).addTo(map);

    const label = options.label ?? 'Etna';
    if (label) {
      marker
        .bindTooltip(label, {
          permanent: true,
          direction: 'top',
          opacity: 0.9,
          offset: options.tooltipOffset || [0, -8],
          className: options.tooltipClassName || 'etna-map-marker-label',
        })
        .openTooltip();
    }

    return marker;
  };

  global.EtnaLeaflet = {
    createEtnaMap,
    addHotspotsLayer,
    createHotspotMarker,
    getHotspotBrightness: getBrightness,
    getHotspotMarkerColor: getMarkerColor,
    getHotspotMarkerClass: getMarkerClass,
    addCopernicusFootprint,
    addEtnaMarker,
  };
})(window);
