import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
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
  /** rank of the place's best lead: the marker opens it */
  rank?: number;
  /** the tooltip: the best lead's company, its label word, and why now */
  tip?: { company: string; word?: string; why?: string };
}

export const placeId = (p: Place) =>
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

/** Atlas spellings of a few countries Intl names differently. */
const REGION_ALIAS: Record<string, string> = {
  "United States": "United States of America",
  "T\u00fcrkiye": "Turkey",
  "Bosnia & Herzegovina": "Bosnia and Herz.",
  "Myanmar (Burma)": "Myanmar",
  "Congo - Kinshasa": "Dem. Rep. Congo",
  "Dominican Republic": "Dominican Rep.",
  "Equatorial Guinea": "Eq. Guinea",
  "South Sudan": "S. Sudan",
  "Central African Republic": "Central African Rep.",
};

/** The atlas name of an ISO-2 country code, or null when it cannot be named. */
export function regionName(iso: string): string | null {
  try {
    const n = new Intl.DisplayNames(["en"], { type: "region" }).of(
      iso.trim().toUpperCase(),
    );
    return n ? (REGION_ALIAS[n] ?? n) : null;
  } catch {
    return null;
  }
}

/** Atlas names of the market countries that hold at least one lead to act on or develop. */
export function laneCountries(
  places: Place[],
  markets: string[] | undefined,
  home: string | null | undefined,
): string[] {
  if (!home || !markets?.length) return [];
  const homeName = regionName(home);
  const names = new Set(
    markets.map(regionName).filter((n): n is string => !!n && n !== homeName),
  );
  const out = new Set<string>();
  for (const p of places) {
    const n = ALIAS[p.country] ?? p.country;
    if (
      names.has(n) &&
      (p.kind === "act" || p.kind === "developing" || p.toDecide > 0)
    )
      out.add(n);
  }
  return [...out];
}

const PITCH = 5;

const KIND_ORDER = { act: 0, developing: 1, watching: 2 } as const;

/** One marker per country: totals added up, the best kind kept, and the best lead (most to decide,
 * then the place listed first) named and opened. Used when the view is too wide for districts. */
function byCountry(places: Place[]): Place[] {
  const out = new Map<string, Place>();
  for (const p of places) {
    const { lat: _lat, lon: _lon, label: _label, ...flat } = p;
    const q = out.get(p.country);
    if (!q) {
      out.set(p.country, { ...flat });
      continue;
    }
    const best = p.toDecide > q.toDecide ? flat : q;
    const kind =
      KIND_ORDER[p.kind ?? "watching"] < KIND_ORDER[q.kind ?? "watching"] ? p.kind : q.kind;
    out.set(p.country, {
      ...best,
      kind,
      total: q.total + p.total,
      toDecide: q.toDecide + p.toDecide,
      account: !!(q.account || p.account),
    });
  }
  return [...out.values()];
}


export function TerritoryMap(props: {
  places: Place[];
  /** open the place's best lead */
  onOpen?: (rank: number) => void;
  /** the client's markets (ISO-2) and base country: both optional */
  markets?: string[];
  home?: string | null;
}) {
  const { onOpen, markets, home } = props;
  const [tip, setTip] = useState<string | null>(null);
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
  // With the base known the view spans continents, too wide for districts: one marker a country.
  const homeCountry = home ? byName.get(regionName(home) ?? "") : undefined;
  const places = homeCountry ? byCountry(props.places) : props.places;
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
    // With the client's base known, frame the story: the base and every country with leads,
    // fitted on projected bounds (a span such as Europe to India never wraps the globe).
    if (homeCountry && found.length) {
      proj = geoEqualEarth().fitExtent(pad, {
        type: "FeatureCollection",
        features: [homeCountry, ...found.map((f) => f.c)].map((c) => mainland(c)),
      });
    } else if (found.length) {
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
    const marketFeatures = (markets ?? [])
      .map((iso) => regionName(iso))
      .map((n) => (n ? byName.get(n) : undefined))
      .filter((c): c is Country => !!c);
    m.fillStyle = "#00f"; // the client's markets
    m.beginPath();
    path({ type: "FeatureCollection", features: marketFeatures });
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
        const hasLeads = px[i + 1] > px[i] && px[i + 1] >= px[i + 2];
        const market = !hasLeads && px[i + 2] > px[i] && px[i + 2] > px[i + 1];
        ctx.globalAlpha = hasLeads ? 0.75 : market ? 0.5 : 1;
        ctx.fillStyle = hasLeads || market ? lit : dot;
        ctx.beginPath();
        ctx.arc(x, y, hasLeads ? 1.15 : market ? 1.1 : 1.05, 0, Math.PI * 2);
        ctx.fill();
      }
    // the projection is rebuilt each render from these same inputs
  }, [countries, size.w, size.h, theme, props.places, markets]);

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

  // trade lanes: from the base to the best marker in each market that has something to act on
  const homeName = home ? regionName(home) : null;
  const homeC = homeName ? byName.get(homeName) : undefined;
  let base: { x: number; y: number } | null = null;
  if (proj && homeC) {
    const xy = proj(geoCentroid(mainland(homeC)));
    if (xy)
      base = {
        x: Math.min(Math.max(xy[0], 24), size.w - 24),
        y: Math.min(Math.max(xy[1], 64), size.h - 48),
      };
  }
  const laneSet = new Set(laneCountries(places, markets, home));
  const lanes: { id: string; d: string }[] = [];
  if (base) {
    const seen = new Set<string>();
    for (const m of [...markers].sort((a, b) => b.p.toDecide - a.p.toDecide)) {
      const n = ALIAS[m.p.country] ?? m.p.country;
      if (!laneSet.has(n) || seen.has(n)) continue;
      if (m.p.kind === "watching" && m.p.toDecide === 0) continue;
      seen.add(n);
      const dx = m.x - base.x;
      const dy = m.y - base.y;
      const len = Math.hypot(dx, dy);
      if (len < 30) continue;
      const cx = (base.x + m.x) / 2 + (dy / len) * len * 0.18;
      const cy = (base.y + m.y) / 2 - (dx / len) * len * 0.18;
      lanes.push({
        id: n,
        d: `M${base.x},${base.y} Q${cx},${cy} ${m.x},${m.y}`,
      });
    }
  }
  const tipMark = markers.find((m) => placeId(m.p) === tip);
  // Only the most urgent marker keeps a written label; the rest show theirs on hover or focus,
  // so a crowded region never turns into overlapping text.
  const labelled = [...markers].sort((a, b) => b.p.toDecide - a.p.toDecide)[0];
  const labelledId = labelled ? placeId(labelled.p) : null;
  const tipUp = tipMark ? tipMark.y + 24 > size.h - 90 : false;

  return (
    <div className="tmap" ref={box}>
      <canvas ref={canvas} className="dots" aria-hidden="true" />
      <svg width={size.w} height={size.h} role="group" aria-label="Leads by country">
        {lanes.map((l) => (
          <path key={l.id} className="lane" d={l.d} />
        ))}
        {base && homeName && (
          <g className="home" transform={`translate(${base.x},${base.y})`}>
            <rect x={-4} y={-4} width={8} height={8} transform="rotate(45)" />
            <text
              x={base.x > size.w * 0.72 ? -12 : 12}
              y={3}
              textAnchor={base.x > size.w * 0.72 ? "end" : "start"}
            >
              {homeName === "United States of America" ? "United States" : homeName}{" "}
              · your base
            </text>
          </g>
        )}
        {markers.map(({ p, x, y }, i) => {
          const hot = p.toDecide > 0;
          const kind = hot ? "act" : (p.kind ?? "watching");
          const left = x > size.w * 0.72;
          const k = 1 + Math.min(3, p.total - 1) * 0.12;
          const id = placeId(p);
          const open =
            onOpen && p.rank != null ? () => onOpen(p.rank as number) : undefined;
          return (
            <g
              key={id}
              className={`mk${hot ? " hot" : ""}${open ? " go" : ""}`}
              style={{ animationDelay: `${300 + i * 90}ms` }}
              transform={`translate(${x},${y})`}
              onClick={open}
              onMouseEnter={() => setTip(id)}
              onMouseLeave={() => setTip((t) => (t === id ? null : t))}
              onFocus={() => setTip(id)}
              onBlur={() => setTip((t) => (t === id ? null : t))}
              {...(open
                ? {
                    tabIndex: 0,
                    role: "button",
                    "aria-label": `${p.note ?? p.country}, open the lead`,
                    onKeyDown: (e: ReactKeyboardEvent) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        open();
                      }
                    },
                  }
                : {})}
            >
              <circle className="hit" r={22} />
              <g transform={`scale(${k})`}>
                {hot ? (
                  <>
                    <circle className="wash" r={22} />
                    <circle className="ring" r={12} />
                    <circle className="core" r={4.2} />
                  </>
                ) : kind === "act" ? (
                  <circle className="core calm" r={4.2} />
                ) : (
                  <rect
                    className={kind === "developing" ? "sq dev" : "sq"}
                    x={-3.5}
                    y={-3.5}
                    width={7}
                    height={7}
                  />
                )}
              </g>
              {p.account && <circle className="acc" r={hot ? 7.5 : 7} />}
              {id === labelledId && (
              <>
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
              </>
              )}
            </g>
          );
        })}
      </svg>
      {tipMark?.p.tip && (
        <div
          className="tip"
          role="tooltip"
          style={{
            left: Math.min(Math.max(tipMark.x, 120), Math.max(120, size.w - 120)),
            top: tipUp ? tipMark.y - 20 : tipMark.y + 24,
            transform: tipUp ? "translate(-50%,-100%)" : "translateX(-50%)",
          }}
        >
          <b>{tipMark.p.tip.company}</b>
          {tipMark.p.tip.word && <span className="w">{tipMark.p.tip.word}</span>}
          {tipMark.p.tip.why && <span className="y">{tipMark.p.tip.why}</span>}
        </div>
      )}
      {failed && <p className="tfail">The map could not load. The leads are all listed.</p>}
    </div>
  );
}
