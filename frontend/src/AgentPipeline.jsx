import { useLayoutEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import TiltCard from "./TiltCard.jsx";

// A deterministic layered diagram (Prime -> each role), not a physics graph --
// reads like a neural net / org chart rather than a floating blob. Clicking a
// role node shows its full mandate/success_metric/owned_paths/reasoning below.
//
// Node cards are positioned by a simple percentage formula (measured via
// ResizeObserver on the container), but the SVG connector lines are drawn
// from the ACTUAL rendered edges of each card (measured via refs), not a
// formula guess -- so a line always meets a card's left/right edge at its
// true vertical center, regardless of card width/height.
//
// The traveling dot uses CSS offset-path, not SVG SMIL <animateMotion> --
// React re-rendering on click mutates SMIL elements' attributes via plain
// DOM attribute sets, which is a known fragile interaction that can silently
// break/hide the animation in Chromium. CSS offset-path has no such issue.
export default function AgentPipeline({ roster }) {
  const [selected, setSelected] = useState(roster[0]?.role_name ?? null);
  const selectedRole = roster.find((r) => r.role_name === selected);

  const containerRef = useRef(null);
  const primeCardRef = useRef(null);
  const roleCardRefs = useRef({});
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [edges, setEdges] = useState({ prime: null, roles: {} });

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const { width, height } = size;
  const primeX = width * 0.12;
  const primeY = height * 0.5;
  const roleX = width * 0.84;
  const n = roster.length;
  const roleYs = roster.map((_, i) => (height * (i + 1)) / (n + 1));

  // Measure actual card edges after layout settles (container size or
  // roster changes) -- not on `selected` changes, since selection styling
  // (box-shadow) doesn't affect a card's own box size.
  useLayoutEffect(() => {
    if (!containerRef.current || width === 0) return;
    const containerRect = containerRef.current.getBoundingClientRect();
    const relEdge = (rect, side) => ({
      x: (side === "right" ? rect.right : rect.left) - containerRect.left,
      y: rect.top + rect.height / 2 - containerRect.top,
    });

    const primeRect = primeCardRef.current?.getBoundingClientRect();
    const prime = primeRect ? relEdge(primeRect, "right") : null;

    const roles = {};
    for (const r of roster) {
      const node = roleCardRefs.current[r.role_name];
      const rect = node?.getBoundingClientRect();
      if (rect) roles[r.role_name] = relEdge(rect, "left");
    }
    setEdges({ prime, roles });
  }, [width, height, roster]);

  const selectRole = (roleName) => () => setSelected(roleName);
  const onKeyActivate = (roleName) => (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setSelected(roleName);
    }
  };

  const pathFor = (from, to) => {
    const midX = (from.x + to.x) / 2;
    return `M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}`;
  };

  return (
    <div>
      <div className="pipeline" ref={containerRef}>
        {width > 0 && edges.prime && (
          <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
            <defs>
              <filter id="edge-glow" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            {roster.map((r) => {
              const to = edges.roles[r.role_name];
              if (!to) return null;
              const isSelected = r.role_name === selected;
              return (
                <path
                  key={r.role_name}
                  d={pathFor(edges.prime, to)}
                  fill="none"
                  stroke={isSelected ? "#f7f7f5" : "rgba(247,247,245,0.28)"}
                  strokeWidth={isSelected ? 1.8 : 1.1}
                  filter={isSelected ? "url(#edge-glow)" : undefined}
                />
              );
            })}
          </svg>
        )}

        {roster.map((r, i) => {
          const to = edges.roles[r.role_name];
          if (!to || !edges.prime) return null;
          const d = pathFor(edges.prime, to);
          const isSelected = r.role_name === selected;
          return (
            <div
              key={r.role_name}
              className="wire-dot"
              data-active={isSelected}
              style={{ offsetPath: `path('${d}')`, animationDelay: `${-i * 7}s` }}
            />
          );
        })}

        <motion.div
          className="pipeline-node prime"
          style={{ left: primeX, top: primeY }}
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4 }}
        >
          <div className="pipeline-node-card" ref={primeCardRef}>
            <div className="node-name">Prime</div>
            <div className="node-tier">bootstrap</div>
          </div>
        </motion.div>

        {roster.map((r, i) => (
          <motion.div
            className="pipeline-node"
            key={r.role_name}
            style={{ left: roleX, top: roleYs[i] }}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: 0.08 * (i + 1), ease: [0.16, 1, 0.3, 1] }}
          >
            <TiltCard max={8} style={{ borderRadius: 8 }}>
              <div
                className="pipeline-node-card"
                ref={(el) => {
                  roleCardRefs.current[r.role_name] = el;
                }}
                role="button"
                tabIndex={0}
                data-selected={r.role_name === selected}
                onClick={selectRole(r.role_name)}
                onKeyDown={onKeyActivate(r.role_name)}
              >
                <div className="node-name">{r.role_name}</div>
                <div className="node-tier">{r.model_tier}</div>
              </div>
            </TiltCard>
          </motion.div>
        ))}
      </div>

      {selectedRole && (
        <motion.dl
          className="role-detail"
          key={selectedRole.role_name}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <dt>Mandate</dt>
          <dd>{selectedRole.mandate}</dd>
          <dt>Success metric</dt>
          <dd>{selectedRole.success_metric}</dd>
          {selectedRole.owned_paths?.length > 0 && (
            <>
              <dt>Owned paths</dt>
              <dd className="paths">
                {selectedRole.owned_paths.map((p) => (
                  <span className="path-chip" key={p}>
                    {p}
                  </span>
                ))}
              </dd>
            </>
          )}
          <dt>Why this role exists</dt>
          <dd>{selectedRole.reasoning}</dd>
        </motion.dl>
      )}
    </div>
  );
}
