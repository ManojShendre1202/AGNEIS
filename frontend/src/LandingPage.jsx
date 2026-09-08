import { motion } from "framer-motion";
import TiltCard from "./TiltCard.jsx";

const STACK = [
  { label: "Backend", items: ["Django", "Django ORM"] },
  { label: "Orchestration", items: ["LangGraph", "LangChain"] },
  { label: "Models", items: ["Claude Sonnet", "Gemini"] },
  { label: "Frontend", items: ["React", "Vite", "Framer Motion"] },
  { label: "Data & Live", items: ["SQLite", "WebSocket"] },
];

const STEPS = [
  {
    num: "01",
    title: "Extract",
    body: "Drop a task brief and Prime turns it into a structured spec — objective, constraints, success criteria — no solution attached.",
  },
  {
    num: "02",
    title: "Roster",
    body: "Prime decides which roles the objective actually needs, staffs each one with a model tier and owned scope, and reasons about resource budgets before a single action runs.",
  },
  {
    num: "03",
    title: "Negotiate",
    body: "Roles execute real, checkable actions inside an isolated sandbox — file I/O, shell, package installs — negotiating with each other and with Prime, turn by turn, fully visible live.",
  },
];

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 24, filter: "blur(4px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  transition: { duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] },
});

export default function LandingPage({ onStart }) {
  return (
    <div className="landing">
      <motion.div className="landing-hero" {...fadeUp(0)}>
        <span className="logo">
          AGN<em>IES</em>
        </span>
        <p className="landing-acronym">Autonomous Goal-driven Negotiating Intelligent Execution System</p>
        <h1>Give it a goal. Not a plan.</h1>
        <p>
          Just the goal, the constraints, the budget, what "done" means — never the how.
          Prime hires the team the job actually needs. Agents can't self-spawn; they ask
          Prime, against a token-optimized budget. Sandboxed. Guardrails held by real
          prompt engineering. Evaluated, never self-graded.
        </p>
        <button onClick={onStart}>Start a run</button>
      </motion.div>

      <div className="landing-section">
        <p className="section-label landing-section-label">
          <span className="num">01</span> How it works
        </p>
        <div className="landing-steps">
          {STEPS.map((s, i) => (
            <TiltCard className="panel landing-step" max={2} key={s.num} {...fadeUp(0.1 + i * 0.08)}>
              <p className="section-label">
                <span className="num">{s.num}</span> {s.title}
              </p>
              <p className="landing-step-body">{s.body}</p>
            </TiltCard>
          ))}
        </div>
      </div>

      <motion.div className="landing-stack" {...fadeUp(0.3)}>
        <p className="section-label landing-section-label">
          <span className="num">02</span> Stack
        </p>
        <div className="stack-groups">
          {STACK.map((g) => (
            <div className="stack-group" key={g.label}>
              <span className="stack-group-label">{g.label}</span>
              <span className="stack-group-items">{g.items.join(" · ")}</span>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
