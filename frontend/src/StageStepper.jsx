import { Fragment } from "react";
import { CheckIcon, SpinnerIcon } from "./icons.jsx";

// stages: [{ key, label }]. stateOf(key) -> "done" | "active" | "pending" | "disabled"
//
// Circles are fixed-size flex items directly inside .stepper; the connector
// between two circles is a separate flex:1 sibling that absorbs all the
// leftover width. That's what pins the first circle to the stepper's true
// left edge and the last circle to its true right edge, with the rest
// evenly spread between -- putting the line *inside* each step's own column
// (the old approach) left the last circle wherever its column happened to
// start, with dead space after it. Using Fragment (not a wrapping div) is
// what lets the circle and the line be true flex siblings of .stepper.
export default function StageStepper({ stages, stateOf, selected, onSelect }) {
  return (
    <div className="stepper">
      {stages.map((s, i) => {
        const state = stateOf(s.key);
        return (
          <Fragment key={s.key}>
            <div
              className="step"
              data-state={state}
              data-selected={s.key === selected}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(s.key)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(s.key)}
            >
              <div className="step-circle">
                {state === "done" ? <CheckIcon /> : state === "active" ? <SpinnerIcon /> : i + 1}
              </div>
              <div className="step-label">{s.label}</div>
            </div>
            {i < stages.length - 1 && <div className="step-line" data-filled={state === "done"} />}
          </Fragment>
        );
      })}
    </div>
  );
}
