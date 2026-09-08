import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import TiltCard from "./TiltCard.jsx";
import { CheckIcon } from "./icons.jsx";

// Live turn-by-turn tree for the negotiate stage. One node per executed
// step (graph.py's role_turn/reflect), NOT one per unique role -- the same
// role can appear as several distinct nodes across the tree. A node's
// position is driven by depth (distance from the root turn along parent_id)
// and a leaf-ordered vertical slot -- a classic node-link tree layout, not
// a physics graph -- so branches reflect "who caused whom to run next",
// not literal chronological order (see graph.py's dispatch/queue_parents).
//
// Same visual mechanism as AgentPipeline.jsx (measured SVG edges off real
// card refs, TiltCard nodes, click-to-inspect detail panel below) but the
// layout itself grows as nodes arrive instead of being a fixed Prime->role
// fan-out.
function layoutTree(nodes) {
  const childrenOf = new Map();
  const roots = [];
  for (const n of nodes) {
    if (n.parent_id == null) {
      roots.push(n.id);
    } else {
      if (!childrenOf.has(n.parent_id)) childrenOf.set(n.parent_id, []);
      childrenOf.get(n.parent_id).push(n.id);
    }
  }

  const depth = new Map();
  const slot = new Map();
  let nextLeafSlot = 0;

  const assignDepth = (id, d) => {
    depth.set(id, d);
    for (const c of childrenOf.get(id) || []) assignDepth(c, d + 1);
  };
  roots.forEach((r) => assignDepth(r, 0));

  const assignSlot = (id) => {
    const kids = childrenOf.get(id) || [];
    if (kids.length === 0) {
      const s = nextLeafSlot++;
      slot.set(id, s);
      return s;
    }
    const kidSlots = kids.map(assignSlot);
    const avg = kidSlots.reduce((a, b) => a + b, 0) / kidSlots.length;
    slot.set(id, avg);
    return avg;
  };
  roots.forEach(assignSlot);

  const maxDepth = nodes.length ? Math.max(...nodes.map((n) => depth.get(n.id) ?? 0)) : 0;
  const maxSlot = Math.max(0, nextLeafSlot - 1);
  return nodes.map((n) => ({
    ...n,
    depth: depth.get(n.id) ?? 0,
    slot: slot.get(n.id) ?? 0,
    maxDepth,
    maxSlot,
  }));
}

// Backend nodes merge every consecutive same-role turn into one node with
// several accumulated `entries` (graph.py's role_turn_node `merge` check) --
// for a multi-role tree that's the right unit ("this role's whole
// uninterrupted stretch"), but for a single-agent task EVERY turn merges
// into the same node, collapsing the entire run into one circle. Flatten
// each backend node's entries into its own chained virtual node (one per
// real turn/reflection/close_review), linked in sequence, so the tree
// always shows real turn-by-turn structure regardless of how much the
// backend happened to merge. tool_results are only ever recorded at the
// backend-node level (not per-entry), so they're attached to the LAST
// entry of that node -- the closest honest approximation to "what these
// results belong to" the data actually supports.
function flattenToTurns(nodes) {
  const lastVirtualIdOf = new Map(); // backend node id -> its last entry's virtual id
  const virtual = [];
  for (const n of nodes) {
    let prevVid = null;
    n.entries.forEach((entry, i) => {
      const vid = `${n.id}:${i}`;
      const isFirst = i === 0;
      const parentVid = isFirst
        ? (n.parent_id != null ? lastVirtualIdOf.get(n.parent_id) ?? null : null)
        : prevVid;
      virtual.push({
        id: vid,
        parent_id: parentVid,
        role_name: n.role_name,
        model_tier: n.model_tier,
        entry,
        tool_results: i === n.entries.length - 1 ? n.tool_results : [],
      });
      prevVid = vid;
    });
    if (prevVid != null) lastVirtualIdOf.set(n.id, prevVid);
  }
  return virtual;
}

// A single-agent run is one straight causal chain (every turn's parent is
// exactly the previous turn -- no real branching at all). Laying that out
// with layoutTree's "one column per depth" rule draws N sequential columns,
// which reads as a long boring line, not as work converging on a result.
// When there's no real branching, render it as a 3-layer diagram instead --
// the classic neural-net shape: one start node, every middle turn stacked
// in a single column (one "layer"), all fanning into one final result node
// -- which means the edges drawn here are NOT the literal 1:1 parent chain
// anymore (that would still be a straight line); they're deliberately
// redrawn as fan-out from the first node and fan-in to the last, since the
// ask is a layer diagram, not a strict causality graph. A genuinely
// branching multi-role tree (someone has 2+ children) keeps the real
// layoutTree/parent-edge behavior below, since that shape already means
// something structurally different (actual parallel roles).
function layoutNegotiationGraph(turns) {
  if (turns.length === 0) return { positioned: [], edges: [] };

  const childCount = new Map();
  for (const t of turns) {
    if (t.parent_id != null) childCount.set(t.parent_id, (childCount.get(t.parent_id) || 0) + 1);
  }
  const isBranching = turns.some((t) => (childCount.get(t.id) || 0) > 1);

  if (!isBranching && turns.length >= 2) {
    const first = turns[0];
    const last = turns[turns.length - 1];
    const middle = turns.slice(1, -1);
    const centerSlot = middle.length > 0 ? (middle.length - 1) / 2 : 0;
    const maxSlot = Math.max(0, middle.length - 1);
    const positioned = [
      { ...first, depth: 0, slot: centerSlot, maxDepth: 2, maxSlot },
      ...middle.map((t, i) => ({ ...t, depth: 1, slot: i, maxDepth: 2, maxSlot })),
      { ...last, depth: 2, slot: centerSlot, maxDepth: 2, maxSlot },
    ];
    const edges =
      middle.length > 0
        ? [...middle.map((t) => ({ from: first.id, to: t.id })), ...middle.map((t) => ({ from: t.id, to: last.id }))]
        : [{ from: first.id, to: last.id }];
    return { positioned, edges };
  }

  const positioned = layoutTree(turns);
  const edges = positioned.filter((n) => n.parent_id != null).map((n) => ({ from: n.parent_id, to: n.id }));
  return { positioned, edges };
}

function toolChipLabel(t) {
  if (t.tool === "run_shell") return `run_shell: ${t.command}`;
  if (t.tool === "install_package") return `install_package: ${(t.packages || []).join(", ")}`;
  return `${t.tool}: ${t.path}`;
}

// Node initials for the circle glyph -- "Backend Developer" -> "BD",
// "Prime" -> "PR". Falls back gracefully for single-word names.
function initialsFor(name) {
  const words = (name || "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

const ENTRY_TITLE = {
  reflect: (e) => `Reflection — turn ${e.turn}`,
  close_review: (e) => `Final review — turn ${e.turn}`,
};

// close_review entries (graph.py's close_review_node) carry findings/
// all_passed instead of response/tool_use/addressed_to/stack_decisions --
// a structurally different entry shape appended to whichever node happened
// to be current when the run finished. Rendering it through the same
// fields as a normal turn entry crashes (reading .length off undefined),
// which used to blank the whole app since there's no error boundary.
function EntryBody({ entry }) {
  if (entry.kind === "close_review") {
    return (
      <dd className="tool-results">
        {(entry.findings || []).map((f, i) => (
          <div key={i} className="tool-result-row" data-ok={f.passed}>
            <span className="kind">{f.criterion}</span>
            <span>{f.evidence}</span>
            <span className="status">{f.passed ? "PASS" : "FAIL"}</span>
          </div>
        ))}
      </dd>
    );
  }
  return (
    <>
      <dd>{entry.response}</dd>
      {entry.tool_use?.length > 0 && (
        <dd className="paths">
          {entry.tool_use.map((t, j) => (
            <span className="path-chip" key={j}>
              {toolChipLabel(t)}
            </span>
          ))}
        </dd>
      )}
      {entry.addressed_to?.length > 0 && (
        <dd className="paths">
          {entry.addressed_to.map((a, j) => (
            <span className="path-chip" key={j}>
              → {a.role}
            </span>
          ))}
        </dd>
      )}
      {entry.stack_decisions?.length > 0 && (
        <dd className="paths">
          {entry.stack_decisions.map((s, j) => (
            <span className="path-chip" key={j}>
              {s.package}
            </span>
          ))}
        </dd>
      )}
    </>
  );
}

// Fixed pixel spacing rather than squeezing the whole tree into one
// container width/height -- a wide/deep tree scrolls instead of clustering
// its nodes on top of each other.
const COL_WIDTH = 220;
const ROW_HEIGHT = 116;
const MIN_SCALE = 0.35;
const MAX_SCALE = 2.5;

export default function NegotiationTree({ nodes }) {
  const [selectedId, setSelectedId] = useState(null);
  const turns = useMemo(() => flattenToTurns(nodes), [nodes]);
  const { positioned, edges } = useMemo(() => layoutNegotiationGraph(turns), [turns]);
  const byId = useMemo(() => new Map(positioned.map((n) => [n.id, n])), [positioned]);
  const selected = selectedId != null ? byId.get(selectedId) : null;

  const viewportRef = useRef(null);
  const containerRef = useRef(null);
  const cardRefs = useRef({});
  const [edgePoints, setEdgePoints] = useState({});

  const maxDepth = positioned[0]?.maxDepth ?? 0;
  const maxSlot = positioned[0]?.maxSlot ?? 0;
  const width = COL_WIDTH * (maxDepth + 2);
  const height = ROW_HEIGHT * (maxSlot + 2);

  // Pan/zoom instead of a scrollbar -- wheel zooms toward the cursor, drag
  // pans. Applied as a CSS transform on the (fixed pixel-size) canvas inside
  // a fixed-height, clipped viewport.
  const [camera, setCamera] = useState({ x: 0, y: 0, scale: 1 });
  const draggingRef = useRef(false);
  const lastPointRef = useRef({ x: 0, y: 0 });
  const movedRef = useRef(false);

  // Fit the whole (fixed pixel-size) tree into the viewport on first render
  // and whenever the tree's bounding box changes, instead of always
  // snapping back to an unscaled top-left origin -- a wide/deep tree used
  // to load mostly off-screen, requiring a manual zoom-out just to see it.
  const fitCamera = () => {
    const el = viewportRef.current;
    if (!el || width === 0 || height === 0) return { x: 0, y: 0, scale: 1 };
    const vw = el.clientWidth;
    const vh = el.clientHeight;
    const pad = 48;
    const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.min((vw - pad) / width, (vh - pad) / height, 1)));
    return { x: (vw - width * scale) / 2, y: (vh - height * scale) / 2, scale };
  };

  useLayoutEffect(() => {
    setCamera(fitCamera());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      setCamera((c) => {
        const nextScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, c.scale * (1 - e.deltaY * 0.0015)));
        const ratio = nextScale / c.scale;
        return { x: cx - (cx - c.x) * ratio, y: cy - (cy - c.y) * ratio, scale: nextScale };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current) return;
      const dx = e.clientX - lastPointRef.current.x;
      const dy = e.clientY - lastPointRef.current.y;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) movedRef.current = true;
      lastPointRef.current = { x: e.clientX, y: e.clientY };
      setCamera((c) => ({ ...c, x: c.x + dx, y: c.y + dy }));
    };
    const onUp = () => {
      draggingRef.current = false;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const onViewportMouseDown = (e) => {
    movedRef.current = false;
    if (e.target.closest(".tree-node-hit")) return;
    e.preventDefault();
    draggingRef.current = true;
    lastPointRef.current = { x: e.clientX, y: e.clientY };
  };

  const resetCamera = () => setCamera(fitCamera());

  useLayoutEffect(() => {
    if (!containerRef.current) return;
    const containerRect = containerRef.current.getBoundingClientRect();
    const scale = camera.scale || 1;
    const points = {};
    for (const n of positioned) {
      const el = cardRefs.current[n.id];
      const rect = el?.getBoundingClientRect();
      if (!rect) continue;
      const top = (rect.top - containerRect.top) / scale;
      const left = (rect.left - containerRect.left) / scale;
      const right = (rect.right - containerRect.left) / scale;
      const midY = top + rect.height / scale / 2;
      points[n.id] = {
        left: { x: left, y: midY },
        right: { x: right, y: midY },
      };
    }
    setEdgePoints(points);
  }, [width, height, positioned.length, camera.scale]);

  const pathFor = (from, to) => {
    const midX = (from.x + to.x) / 2;
    return `M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}`;
  };

  const selectNode = (id) => () => {
    if (movedRef.current) return;
    setSelectedId(id);
  };
  const onKeyActivate = (id) => (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setSelectedId(id);
    }
  };

  return (
    <div>
      <div
        className="negotiation-tree-viewport"
        ref={viewportRef}
        onMouseDown={onViewportMouseDown}
        data-dragging={draggingRef.current}
      >
        <button type="button" className="btn-secondary btn-tiny tree-zoom-reset" onClick={resetCamera}>
          Reset view
        </button>
        <div
          className="negotiation-tree"
          ref={containerRef}
          style={{
            width,
            height,
            transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`,
          }}
        >
          {Object.keys(edgePoints).length > 0 && (
            <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
              <defs>
                <filter id="tree-edge-glow" x="-60%" y="-60%" width="220%" height="220%">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              {edges.map(({ from, to }) => {
                const fromPt = edgePoints[from]?.right;
                const toPt = edgePoints[to]?.left;
                if (!fromPt || !toPt) return null;
                const isSelected = to === selectedId || from === selectedId;
                return (
                  <path
                    key={`${from}->${to}`}
                    d={pathFor(fromPt, toPt)}
                    fill="none"
                    stroke={isSelected ? "#f7f7f5" : "rgba(247,247,245,0.4)"}
                    strokeWidth={isSelected ? 2.6 : 2}
                    strokeLinecap="round"
                    filter={isSelected ? "url(#tree-edge-glow)" : undefined}
                  />
                );
              })}
            </svg>
          )}

          {edges.map(({ from, to }, i) => {
            const fromPt = edgePoints[from]?.right;
            const toPt = edgePoints[to]?.left;
            if (!fromPt || !toPt) return null;
            const isSelected = to === selectedId || from === selectedId;
            return (
              <div
                key={`${from}->${to}`}
                className="wire-dot"
                data-active={isSelected}
                style={{ offsetPath: `path('${pathFor(fromPt, toPt)}')`, animationDelay: `${-i * 3}s` }}
              />
            );
          })}

          {positioned.map((n) => {
            const isReview = n.entry.kind === "close_review";
            const isDone = isReview && n.entry.all_passed;
            const isReflect = n.entry.kind === "reflect";
            const kind = isReview ? (isDone ? "done" : "review") : "turn";
            return (
              <motion.div
                key={n.id}
                className="tree-node"
                style={{ left: COL_WIDTH * (n.depth + 1), top: ROW_HEIGHT * (n.slot + 1) }}
                initial={{ opacity: 0, scale: 0.85 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
              >
                <div
                  role="button"
                  tabIndex={0}
                  className="tree-node-hit"
                  data-selected={n.id === selectedId}
                  data-node-kind={kind}
                  onClick={selectNode(n.id)}
                  onKeyDown={onKeyActivate(n.id)}
                >
                  <TiltCard max={10} className="tree-node-circle" style={{ borderRadius: "50%" }}>
                    <div
                      className="tree-node-circle-inner"
                      ref={(el) => {
                        cardRefs.current[n.id] = el;
                      }}
                    >
                      {isReview ? (isDone ? <CheckIcon /> : <span className="tree-node-glyph">!</span>) : initialsFor(n.role_name)}
                    </div>
                  </TiltCard>
                  <div className="tree-node-label">
                    <div className="node-name">{isReview ? (isDone ? "Converged" : "Review") : n.role_name}</div>
                    <div className="node-tier">
                      {isReview
                        ? isDone
                          ? "final review · done"
                          : "final review · issues found"
                        : `turn ${n.entry.turn}${isReflect ? " · reflected" : ""}`}
                    </div>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>

      {selected && (
        <motion.dl
          className="role-detail"
          key={selected.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          {selected.entry.kind !== "close_review" && (
            <>
              <dt>Role</dt>
              <dd>
                {selected.role_name} <span className="node-tier">({selected.model_tier})</span>
              </dd>
            </>
          )}

          <dt>{(ENTRY_TITLE[selected.entry.kind] || ((e) => `Response — turn ${e.turn}`))(selected.entry)}</dt>
          <EntryBody entry={selected.entry} />

          {selected.tool_results.length > 0 && (
            <>
              <dt>Tool results</dt>
              <dd className="tool-results">
                {selected.tool_results.map((r, i) => (
                  <div key={i} className="tool-result-row" data-ok={r.success}>
                    <span className="kind">{r.kind}</span>
                    <span>{r.path || r.command || (r.packages || []).join(", ")}</span>
                    <span className="status">{r.success ? "OK" : "FAILED"}</span>
                  </div>
                ))}
              </dd>
            </>
          )}
        </motion.dl>
      )}
    </div>
  );
}
