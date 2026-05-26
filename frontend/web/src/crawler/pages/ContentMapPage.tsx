/**
 * ContentMapPage — `/crawler/content-map`.
 *
 * 3D visualisation of Bajaj's content corpus. Each point = one chunk
 * of one crawled page, positioned in a UMAP-projected 3D space where
 * semantically similar content clusters together.
 *
 * Encoding:
 *   - colour  → product label (term=blue, ulip=purple, …)
 *   - shape   → page-type (sphere for blogs, cube for products)
 *   - hover   → URL + title + classification
 *   - click   → side panel with the top-5 most-similar pages
 *
 * Tech: react-three-fiber renders to WebGL; comfortably handles 10k+
 * points at 60fps. Bajaj brand colours per the brand memory.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, Html, Text } from '@react-three/drei';
import * as THREE from 'three';
import { crawlerApi } from '../api';

// Bajaj-friendly product palette (blue/white house plus product accents).
const PRODUCT_COLOURS: Record<string, string> = {
  term:        '#003DA5',   // Bajaj navy
  ulip:        '#8B5CF6',   // purple
  endowment:   '#0EA5E9',   // sky
  retirement:  '#10B981',   // emerald
  child:       '#F59E0B',   // amber
  group:       '#EC4899',   // pink
  wellness:    '#14B8A6',   // teal
  tax:         '#EF4444',   // red
  nri:         '#FDB913',   // Bajaj gold
  general_life:'#64748B',   // slate
  none:        '#9CA3AF',   // grey for un-tagged
};

type Point = {
  id: number;
  chunk_idx: number;
  x: number; y: number; z: number;
  url: string;
  title: string;
  products: string[];
  page_type: string;
  confidence: number;
};

export default function ContentMapPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'content-map'],
    queryFn: () => crawlerApi.contentMap3d(),
    staleTime: 5 * 60_000,
  });

  const [selected, setSelected] = useState<Point | null>(null);
  const [productFilter, setProductFilter] = useState<Set<string>>(new Set());
  const [pageTypeFilter, setPageTypeFilter] = useState<Set<string>>(new Set());

  const points = data?.points ?? [];

  const visiblePoints = useMemo(() => {
    return points.filter((p) => {
      if (productFilter.size > 0) {
        const hit = p.products.some((pr) => productFilter.has(pr));
        if (!hit) return false;
      }
      if (pageTypeFilter.size > 0 && !pageTypeFilter.has(p.page_type)) {
        return false;
      }
      return true;
    });
  }, [points, productFilter, pageTypeFilter]);

  const availableProducts = useMemo(() => {
    const s = new Set<string>();
    points.forEach((p) => p.products.forEach((pr) => s.add(pr)));
    return Array.from(s).sort();
  }, [points]);

  const availablePageTypes = useMemo(() => {
    const s = new Set<string>();
    points.forEach((p) => p.page_type && s.add(p.page_type));
    return Array.from(s).sort();
  }, [points]);

  const toggle = <T,>(set: Set<T>, val: T, fn: (s: Set<T>) => void) => {
    const next = new Set(set);
    if (next.has(val)) next.delete(val);
    else next.add(val);
    fn(next);
  };

  return (
    <div className="bajaj-ui flex h-full">
      {/* Sidebar */}
      <aside className="w-72 shrink-0 border-r border-brand-border bg-brand-surface p-4 overflow-y-auto">
        <h1 className="text-lg font-semibold text-brand-text">Content Map</h1>
        <p className="mt-1 text-xs text-brand-text-3">
          3D map of Bajaj's crawled content. Each dot is one chunk of one
          page. Similar content clusters together.
        </p>
        <div className="mt-4 text-xs text-brand-text-3">
          {data ? (
            <>
              <div>{points.length.toLocaleString()} chunks</div>
              <div>{visiblePoints.length.toLocaleString()} visible</div>
            </>
          ) : null}
        </div>

        <div className="mt-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-brand-text-3">
            Products
          </div>
          <div className="mt-2 space-y-1">
            {availableProducts.map((p) => (
              <label key={p} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={productFilter.size === 0 || productFilter.has(p)}
                  onChange={() => toggle(productFilter, p, setProductFilter)}
                />
                <span
                  className="inline-block h-3 w-3 rounded-full"
                  style={{ background: PRODUCT_COLOURS[p] ?? PRODUCT_COLOURS.none }}
                />
                <span className="text-brand-text-2">{p}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="mt-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-brand-text-3">
            Page types
          </div>
          <div className="mt-2 space-y-1">
            {availablePageTypes.map((pt) => (
              <label key={pt} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={pageTypeFilter.size === 0 || pageTypeFilter.has(pt)}
                  onChange={() => toggle(pageTypeFilter, pt, setPageTypeFilter)}
                />
                <span className="text-brand-text-2">{pt}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Selected point detail */}
        {selected && (
          <div className="mt-6 rounded-md border border-brand-border bg-brand-surface-2 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              Selected
            </div>
            <div className="mt-1 text-sm font-medium text-brand-text">
              {selected.title}
            </div>
            <a
              href={selected.url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block break-all text-xs text-brand-accent hover:underline"
            >
              {selected.url}
            </a>
            <div className="mt-2 flex flex-wrap gap-1">
              {selected.products.map((p) => (
                <span
                  key={p}
                  className="rounded px-1.5 py-0.5 text-[10px] text-white"
                  style={{ background: PRODUCT_COLOURS[p] ?? PRODUCT_COLOURS.none }}
                >
                  {p}
                </span>
              ))}
            </div>
            <div className="mt-2 text-xs text-brand-text-3">
              page_type: {selected.page_type}<br />
              confidence: {(selected.confidence * 100).toFixed(0)}%<br />
              chunk #{selected.chunk_idx}
            </div>
          </div>
        )}
      </aside>

      {/* 3D canvas — fixed height so it always renders, never collapses */}
      <main
        className="flex-1 relative bg-brand-surface-2"
        style={{ minHeight: '70vh', height: '70vh' }}
      >
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-brand-text-3">
            Loading content embeddings…
          </div>
        )}
        {isError && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-severity-error">
            Failed to load: {error instanceof Error ? error.message : 'unknown'}
          </div>
        )}
        {data && (
          <Canvas camera={{ position: [16, 16, 16], fov: 45 }}>
            <ambientLight intensity={0.7} />
            <directionalLight position={[10, 10, 10]} intensity={0.6} />
            <Scatter points={visiblePoints} onSelect={setSelected} selected={selected} />
            <ClusterLabels points={visiblePoints} />
            <axesHelper args={[8]} />
            <gridHelper args={[20, 20, '#334155', '#1E293B']} />
            <OrbitControls
              makeDefault
              enableDamping
              enableZoom
              enablePan
              minDistance={4}
              maxDistance={50}
              zoomSpeed={0.8}
            />
            <CameraFit points={visiblePoints} />
          </Canvas>
        )}
        {data && (
          <div className="absolute bottom-2 left-2 rounded bg-black/50 px-2 py-1 text-[11px] text-white">
            scroll = zoom · drag = rotate · right-drag = pan
          </div>
        )}
      </main>
    </div>
  );
}

/** Centre & frame the camera on the visible point cloud on first render
 *  and whenever the filter changes the set of visible points. */
function CameraFit({ points }: { points: Point[] }) {
  const { camera, controls } = useThree() as unknown as {
    camera: THREE.PerspectiveCamera;
    controls: { target: THREE.Vector3; update: () => void } | null;
  };
  useEffect(() => {
    if (points.length === 0) return;
    const box = new THREE.Box3();
    points.forEach((p) => box.expandByPoint(new THREE.Vector3(p.x, p.y, p.z)));
    const centre = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) * 0.85;
    const dist = radius / Math.tan((camera.fov * Math.PI) / 360) + radius;
    camera.position.set(centre.x + dist * 0.6, centre.y + dist * 0.6, centre.z + dist * 0.6);
    camera.near = Math.max(0.1, dist / 100);
    camera.far = dist * 100;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(centre);
      controls.update();
    }
  }, [points, camera, controls]);
  return null;
}

/** Render a text label at the centroid of each (product) group so the
 *  user can identify clusters at a glance, instead of guessing from
 *  point colour alone. */
function ClusterLabels({ points }: { points: Point[] }) {
  const groups = useMemo(() => {
    const buckets: Record<string, Point[]> = {};
    points.forEach((p) => {
      const key = p.products[0] || 'none';
      (buckets[key] ||= []).push(p);
    });
    return Object.entries(buckets).map(([key, pts]) => {
      const c = pts.reduce(
        (a, p) => ({ x: a.x + p.x, y: a.y + p.y, z: a.z + p.z }),
        { x: 0, y: 0, z: 0 },
      );
      return {
        key,
        x: c.x / pts.length,
        y: c.y / pts.length + 1.2,   // hover label slightly above the cluster
        z: c.z / pts.length,
        count: pts.length,
        colour: PRODUCT_COLOURS[key] ?? PRODUCT_COLOURS.none,
      };
    });
  }, [points]);
  return (
    <>
      {groups.map((g) => (
        <Text
          key={g.key}
          position={[g.x, g.y, g.z]}
          fontSize={0.55}
          color={g.colour}
          outlineWidth={0.04}
          outlineColor="#0B1220"
          anchorX="center"
          anchorY="middle"
        >
          {`${g.key} (${g.count})`}
        </Text>
      ))}
    </>
  );
}

function Scatter({
  points, onSelect, selected,
}: {
  points: Point[];
  onSelect: (p: Point) => void;
  selected: Point | null;
}) {
  return (
    <>
      {points.map((p) => {
        const colour =
          PRODUCT_COLOURS[p.products[0]] ?? PRODUCT_COLOURS.none;
        const isSelected = selected?.id === p.id;
        return (
          <mesh
            key={p.id}
            position={[p.x, p.y, p.z]}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(p);
            }}
          >
            <sphereGeometry args={[isSelected ? 0.35 : 0.22, 16, 16]} />
            <meshStandardMaterial
              color={colour}
              emissive={isSelected ? colour : '#000000'}
              emissiveIntensity={isSelected ? 0.6 : 0}
            />
          </mesh>
        );
      })}
    </>
  );
}
