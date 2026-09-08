import { useRef } from "react";
import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";

// Cursor-reactive 3D tilt + radial glow wrapper, same technique used across
// the Portfolio site's cards (see Readar/Portfolio/frontend/.../Portfolio.jsx
// TiltCard) -- gives static panels real presence under the cursor.
export default function TiltCard({ children, className = "", style, max = 4, ...rest }) {
  const ref = useRef(null);
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const rotateX = useSpring(useTransform(my, [-0.5, 0.5], [max, -max]), { stiffness: 300, damping: 30 });
  const rotateY = useSpring(useTransform(mx, [-0.5, 0.5], [-max, max]), { stiffness: 300, damping: 30 });
  const glowX = useSpring(useTransform(mx, [-0.5, 0.5], ["0%", "100%"]), { stiffness: 300, damping: 30 });
  const glowY = useSpring(useTransform(my, [-0.5, 0.5], ["0%", "100%"]), { stiffness: 300, damping: 30 });

  const onMove = (e) => {
    const r = ref.current.getBoundingClientRect();
    mx.set((e.clientX - r.left) / r.width - 0.5);
    my.set((e.clientY - r.top) / r.height - 0.5);
  };
  const onLeave = () => {
    mx.set(0);
    my.set(0);
  };

  return (
    <motion.div
      ref={ref}
      className={`tilt-card ${className}`}
      style={{ ...style, rotateX, rotateY, "--gx": glowX, "--gy": glowY }}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      {...rest}
    >
      <div className="tilt-glow" aria-hidden />
      {children}
    </motion.div>
  );
}
