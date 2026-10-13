import maplibregl, { type GeoJSONSource, type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { GeoFeature, GeoLayer } from "../api/client";
import { formatValue } from "../format";

// Free basemaps (no token). If they cannot load (offline), a plain background style is used.
const BASEMAP_LIGHT = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const BASEMAP_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const BLANK: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#dfe5ec" } }],
};
const UZ_BOUNDS: [number, number, number, number] = [55.9, 37.1, 73.2, 45.6];
// Sequential lapis → turquoise ramp from the design palette; missing data is grey.
const RAMP: [number, string][] = [
  [0, "#e6eef7"],
  [0.35, "#8fd0ca"],
  [0.7, "#3fb8af"],
  [1, "#1f3f7a"],
];
const FOCUS = "#e3a72f";

export interface MapViewProps {
  layer: GeoLayer | null;
  unit: string;
  extrude: boolean;
  focus?: string[];
  selected?: string | null;
  onSelect?: (f: GeoFeature["properties"]) => void;
  height?: number | string;
  interactive?: boolean;
}

function prefersDark(): boolean {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

/** Percentile position 0..1 from the rank, so one very large territory does not flatten the rest. */
function withT(layer: GeoLayer): GeoJSON.FeatureCollection {
  const ranked = layer.features.filter((f) => f.properties.rank != null);
  const n = Math.max(ranked.length - 1, 1);
  return {
    type: "FeatureCollection",
    features: layer.features.map((f) => ({
      ...f,
      properties: {
        ...f.properties,
        t: f.properties.rank != null ? 1 - (f.properties.rank - 1) / n : -1,
      },
    })) as GeoJSON.Feature[],
  };
}

function bbox(features: GeoFeature[]): [number, number, number, number] | null {
  let x0 = Infinity,
    y0 = Infinity,
    x1 = -Infinity,
    y1 = -Infinity;
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") {
      const [x, y] = c as [number, number];
      x0 = Math.min(x0, x);
      y0 = Math.min(y0, y);
      x1 = Math.max(x1, x);
      y1 = Math.max(y1, y);
    } else if (Array.isArray(c)) c.forEach(walk);
  };
  features.forEach((f) => walk(f.geometry.coordinates));
  return Number.isFinite(x0) ? [x0, y0, x1, y1] : null;
}

const colorExpr = [
  "case",
  ["<", ["get", "t"], 0],
  "#b9c1cc",
  ["interpolate", ["linear"], ["get", "t"], ...RAMP.flat()],
] as unknown as maplibregl.ExpressionSpecification;

export function MapView({
  layer,
  unit,
  extrude,
  focus = [],
  selected = null,
  onSelect,
  height = 520,
  interactive = true,
}: MapViewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [styleVersion, setStyleVersion] = useState(0); // bumps when the style (re)loads → layers re-added
  const handlersBound = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // create the map once
  useEffect(() => {
    if (!ref.current) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const map = new maplibregl.Map({
      container: ref.current,
      style: prefersDark() ? BASEMAP_DARK : BASEMAP_LIGHT,
      bounds: UZ_BOUNDS,
      pitch: extrude ? 45 : 0,
      attributionControl: { compact: true },
      interactive,
      fadeDuration: reduced ? 0 : 300,
    });
    let fellBack = false;
    map.on("error", (e) => {
      // basemap unreachable → plain background, our own layers still work
      if (!fellBack && !map.isStyleLoaded() && String(e.error?.message ?? "").length) {
        fellBack = true;
        map.setStyle(BLANK);
      }
    });
    if (interactive) map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.on("style.load", () => {
      setReady(true);
      setStyleVersion((v) => v + 1);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // data layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !layer) return;
    const data = withT(layer);
    const polys = { ...data, features: data.features.filter((f) => f.geometry.type !== "Point") };
    const points = { ...data, features: data.features.filter((f) => f.geometry.type === "Point") };
    const maxH = layer.level === "region" ? 90000 : 35000;

    const src = map.getSource("areas") as GeoJSONSource | undefined;
    if (src) {
      src.setData(polys);
      (map.getSource("approx") as GeoJSONSource).setData(points);
    } else {
      map.addSource("areas", { type: "geojson", data: polys, promoteId: "soato" });
      map.addSource("approx", { type: "geojson", data: points, promoteId: "soato" });
      map.addLayer({
        id: "areas-3d",
        type: "fill-extrusion",
        source: "areas",
        paint: {
          "fill-extrusion-color": colorExpr,
          "fill-extrusion-height": ["*", ["max", ["get", "t"], 0.02], maxH],
          "fill-extrusion-opacity": 0.88,
        },
      });
      map.addLayer({
        id: "areas-outline",
        type: "line",
        source: "areas",
        paint: { "line-color": "#ffffff", "line-width": 0.6, "line-opacity": 0.8 },
      });
      map.addLayer({
        id: "areas-focus",
        type: "line",
        source: "areas",
        filter: ["in", ["get", "soato"], ["literal", []]],
        paint: { "line-color": FOCUS, "line-width": 3 },
      });
      map.addLayer({
        id: "approx",
        type: "circle",
        source: "approx",
        paint: {
          "circle-color": colorExpr,
          "circle-radius": 7,
          "circle-opacity": 0.55,
          "circle-stroke-color": "#1f3f7a",
          "circle-stroke-width": 1,
          "circle-stroke-opacity": 0.6,
        },
      });

    }
    if (!handlersBound.current) {
      handlersBound.current = true;
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
      const show = (e: maplibregl.MapLayerMouseEvent) => {
        const f = e.features?.[0];
        if (!f) return;
        map.getCanvas().style.cursor = "pointer";
        const p = f.properties as Record<string, unknown>;
        const v = typeof p.value === "number" ? formatValue(p.value, unitRef.current) : "no data";
        const approx = p.geom_approx === true || p.geom_approx === "true";
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<strong>${escapeHtml(String(p.name_en))}</strong><br/>${v}` +
              (p.rank ? `<br/><span class="muted">Rank ${p.rank} · ${yearRef.current}</span>` : "") +
              `<br/><span class="muted">${escapeHtml(sourceRef.current)}</span>` +
              (approx ? `<br/><em class="muted">Approximate location</em>` : ""),
          )
          .addTo(map);
      };
      const hide = () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      };
      for (const id of ["areas-3d", "approx"]) {
        map.on("mousemove", id, show);
        map.on("mouseleave", id, hide);
        map.on("click", id, (e) => {
          const f = e.features?.[0];
          if (f) onSelectRef.current?.(f.properties as GeoFeature["properties"]);
        });
      }
    }
    map.setPaintProperty("areas-3d", "fill-extrusion-height", ["*", ["max", ["get", "t"], 0.02], extrude ? maxH : 0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer, ready, styleVersion]);

  // values the popup reads without re-binding handlers
  const unitRef = useRef(unit);
  unitRef.current = unit;
  const yearRef = useRef<number | string>(layer?.year ?? "");
  yearRef.current = layer?.year ?? "";
  const sourceRef = useRef("");
  const s = layer?.meta.sources[0];
  sourceRef.current = s ? `Source: SIAT dataset ${s.siat_dataset_id ?? ""}` : "Source: SIAT";

  // 2D / 3D
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("areas-3d") || !layer) return;
    const maxH = layer.level === "region" ? 90000 : 35000;
    map.setPaintProperty("areas-3d", "fill-extrusion-height", ["*", ["max", ["get", "t"], 0.02], extrude ? maxH : 0]);
    map.easeTo({ pitch: extrude ? 45 : 0, duration: 600 });
  }, [extrude, ready, layer]);

  // focus + selection highlight, and fit the view
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !layer || !map.getLayer("areas-focus")) return;
    const ids = [...new Set([...focus, ...(selected ? [selected] : [])])];
    map.setFilter("areas-focus", ["in", ["get", "soato"], ["literal", ids]]);
    const target = focus.length ? layer.features.filter((f) => focus.includes(f.properties.soato)) : layer.features;
    const b = bbox(target);
    if (b) {
      const pad = focus.length ? 0.4 : 0.1;
      map.fitBounds(
        [
          [b[0] - pad, b[1] - pad],
          [b[2] + pad, b[3] + pad],
        ],
        { padding: 40, duration: 900, pitch: extrude ? 45 : 0, maxZoom: 9 },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer, ready, styleVersion, focus.join(","), selected]);

  return <div ref={ref} className="map" style={{ height }} role="region" aria-label="Map of Uzbekistan" />;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export function Legend({ layer, unit }: { layer: GeoLayer | null; unit: string }) {
  if (!layer || layer.min == null || layer.max == null) return null;
  return (
    <div className="legend" aria-label="Legend">
      <span>{formatValue(layer.min, unit, true)}</span>
      <span className="ramp" style={{ background: `linear-gradient(90deg, ${RAMP.map(([, c]) => c).join(",")})` }} />
      <span>{formatValue(layer.max, unit, true)}</span>
      <span className="muted">· colour/height = rank · grey = no data · dots = approximate location</span>
    </div>
  );
}
