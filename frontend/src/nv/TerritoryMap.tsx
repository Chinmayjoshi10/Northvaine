import { useEffect, useRef, useState } from "react";
import {
  geoArea,
  geoBounds,
  geoCentroid,
  geoConicConformal,
  geoEqualEarth,
  geoPath,
} from "d3-geo";
import type { GeoProjection } from "d3-geo";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";
import type { Feature, FeatureCollection, Geometry, Polygon } from "geojson";
import atlasUrl from "world-atlas/countries-50m.json?url";

// The territory: land drawn as dots, one marker per country the run found leads in, or per
// registered-office district where the record gives one. Nothing is placed more precisely than
// its source allows.

export interface Place {
  country: string;
  total: number;
  toDecide: number;
  /** act: a decision here; developing: leads to qualify; watching: the rest */
  kind?: "act" | "developing" | "watching";
  /** one of the client's own accounts is here */
  account?: boolean;
  /** "Company · short fact" for the country's lead row */
  note?: string;
  /** a registered office, district level: the marker sits here, not on the country */
  lat?: number;
  lon?: number;
  /** the town (or postcode district) of that office */
  label?: string;
}

const placeId = (p: Place) =>
  p.lat != null && p.lon != null ? `${p.country}@${p.lat},${p.lon}` : p.country;

type Country = Feature<Geometry, { name: string }>;

// Names a run may use that the atlas spells differently.
const ALIAS: Record<string, string> = {
  "United States": "United States of America",
  USA: "United States of America",
  UK: "United Kingdom",
  "Czech Republic": "Czechia",
};

let atlas: Promise<Country[]> | null = null;
function loadAtlas(): Promise<Country[]> {
  atlas ??= fetch(atlasUrl)
    .then((r) => r.json())
    .then((t: Topology) => {
      const fc = feature(t, t.objects.countries) as FeatureCollection<
        Geometry,
        { name: string }
      >;
      return fc.features;
    });
  return atlas;
}

/** The country's largest landmass, so overseas territories do not pull its marker into the sea. */
function mainland(c: Country): Feature<Polygon> {
  const g = c.geometry;
  const polys: Polygon[] =
    g.type === "MultiPolygon"
      ? g.coordinates.map((coordinates) => ({ type: "Polygon", coordinates }))
      : [g as Polygon];
  let best = polys[0];
  for (const p of polys) if (geoArea(p) > geoArea(best)) best = p;
  return { type: "Feature", properties: {}, geometry: best };
}

const PITCH = 5;

export function TerritoryMap(props: {
  places: Place[];
  onPick?: (country: string) => void;
}) {
  const { places, onPick } = props;
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [countries, setCountries] = useState<Country[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [theme, setTheme] = useState("");

  // redraw when the frame's theme changes: the dot colours come from its tokens
  useEffect(() => {
    const frame = box.current?.closest<HTMLElement>(".nv");
    if (!frame) return;
    const read = () => setTheme(frame.dataset.theme ?? "");
    read();
    const mo = new MutationObserver(read);
    mo.observe(frame, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);

  useEffect(() => {
    loadAtlas().then(setCountries, () => setFailed(true));
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) =>
      setSize({
        w: Math.round(e.contentRect.width),
        h: Math.round(e.contentRect.height),
      }),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const byName = new Map((countries ?? []).map((c) => [c.properties.name, c]));
  const found = places
    .map((p) => ({ p, c: byName.get(ALIAS[p.country] ?? p.country) }))
    .filter((x): x is { p: Place; c: Country } => !!x.c);

  // Fit the view to the countries with leads, with room around them; the world when none.
  let proj: GeoProjection | null = null;
  if (countries && size.w > 0 && size.h > 0) {
    const pad: [[number, number], [number, number]] = [
      [36, 56],
      [size.w - 36, size.h - 40],
    ];
    if (found.length) {
      const [[x0, y0], [x1, y1]] = geoBounds({
        type: "FeatureCollection",
        features: found.map((f) => mainland(f.c)),
      });
      const m = 7; // degrees of context around the leads
      const lon = (x0 + x1) / 2;
      proj = geoConicConformal()
        .rotate([-lon, 0])
        .parallels([Math.max(y0, -60), Math.min(y1, 70)])
        .fitExtent(pad, {
          type: "MultiPoint",
          coordinates: [
            [x0 - m, y0 - m],
            [x1 + m, y1 + m],
            [x0 - m, y1 + m],
            [x1 + m, y0 - m],
          ],
        });
    } else {
      proj = geoEqualEarth().fitExtent(pad, { type: "Sphere" });
    }
  }

  // Draw the land as dots: rasterise once off screen, then sample on a grid.
  useEffect(() => {
    const cv = canvas.current;
    if (!cv || !proj || !countries) return;
    const { w, h } = size;
    const dpr = window.devicePixelRatio || 1;
    cv.width = w * dpr;
    cv.height = h * dpr;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const css = getComputedStyle(cv);
    const dot = css.getPropertyValue("--mapdot").trim();
    const lit = css.getPropertyValue("--maplit").trim();

    const mask = document.createElement("canvas");
    mask.width = w;
    mask.height = h;
    const m = mask.getContext("2d", { willReadFrequently: true });
    if (!m) return;
    const path = geoPath(proj, m);
    m.fillStyle = "#f00"; // all land
    m.beginPath();
    path({ type: "FeatureCollection", features: countries });
    m.fill();
    m.fillStyle = "#0f0"; // countries with leads
    m.beginPath();
    path({ type: "FeatureCollection", features: found.map((f) => f.c) });
    m.fill();
    const px = m.getImageData(0, 0, w, h).data;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    for (let y = PITCH; y < h; y += PITCH)
      for (let x = PITCH; x < w; x += PITCH) {
        const i = (y * w + x) * 4;
        if (px[i + 3] < 128) continue;
        const hasLeads = px[i + 1] > px[i];
        ctx.globalAlpha = hasLeads ? 0.75 : 1;
        ctx.fillStyle = hasLeads ? lit : dot;
        ctx.beginPath();
        ctx.arc(x, y, hasLeads ? 1.15 : 1.05, 0, Math.PI * 2);
        ctx.fill();
      }
    // the projection is rebuilt each render from these same inputs
  }, [countries, size.w, size.h, theme, places]);

  const markers = proj
    ? found
        .map(({ p, c }) => {
          const xy =
            p.lat != null && p.lon != null
              ? proj!([p.lon, p.lat])
              : proj!(geoCentroid(mainland(c)));
          return xy ? { p, x: xy[0], y: xy[1] } : null;
        })
        .filter((m): m is { p: Place; x: number; y: number } => !!m)
        .sort((a, b) => a.p.toDecide - b.p.toDecide)
    : [];

  return (
    <div className="tmap" ref={box}>
      <canvas ref={canvas} className="dots" aria-hidden="true" />
      <svg width={size.w} height={size.h} role="img" aria-label="Leads by country">
        {markers.map(({ p, x, y }, i) => {
          const hot = p.toDecide > 0;
          const kind = hot ? "act" : (p.kind ?? "watching");
          const left = x > size.w * 0.72;
          return (
            <g
              key={placeId(p)}
              className={`mk${hot ? " hot" : ""}`}
              style={{ animationDelay: `${300 + i * 90}ms` }}
              transform={`translate(${x},${y})`}
              onClick={onPick ? () => onPick(p.country) : undefined}
            >
              {hot ? (
                <>
                  <circle className="wash" r={22} />
                  <circle className="ring" r={12} />
                  <circle className="core" r={4.2} />
                </>
              ) : (
                <rect
                  className={kind === "developing" ? "sq dev" : "sq"}
                  x={-3.5}
                  y={-3.5}
                  width={7}
                  height={7}
                />
              )}
              {p.account && <circle className="acc" r={hot ? 7.5 : 7} />}
              <text x={left ? -14 : 14} y={3} textAnchor={left ? "end" : "start"}>
                {p.note ?? p.country}
              </text>
              <text
                className="sub"
                x={left ? -14 : 14}
                y={17}
                textAnchor={left ? "end" : "start"}
              >
                {p.label ? `${p.label}, ${p.country}` : p.country} · {p.total} on record{hot ? ` · ${p.toDecide} to decide` : ""}
              </text>
            </g>
          );
        })}
      </svg>
      {failed && <p className="tfail">The map could not load. The leads are all listed.</p>}
    </div>
  );
}
