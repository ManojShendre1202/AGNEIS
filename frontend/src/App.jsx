import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import AgentPipeline from "./AgentPipeline.jsx";
import LandingPage from "./LandingPage.jsx";
import NegotiationTree from "./NegotiationTree.jsx";
import SandboxBrowser from "./SandboxBrowser.jsx";
import StageStepper from "./StageStepper.jsx";
import TiltCard from "./TiltCard.jsx";
import { RefreshIcon, /* TrashIcon, UploadIcon, */ UserIcon } from "./icons.jsx";
import {
  connectTaskSocket,
  // deleteTask, // disabled for read-only server deploy (uncomment locally)
  fetchTasks,
  fetchTaskState,
  runStage,
  // uploadTaskFile, // disabled for read-only server deploy (uncomment locally)
  verifyTask,
} from "./api.js";

const STAGES = [
  { key: "extract", label: "Extract" },
  { key: "roster", label: "Roster" },
  { key: "negotiate", label: "Negotiate" },
];

const STAGE_TITLE = {
  extract: "Task brief to structured spec",
  roster: "Prime's team bootstrap",
  negotiate: "Agent execution pipeline",
};

const STATUS_LABEL = {
  pending: "Pending",
  extracted: "Awaiting review",
  verified: "Verified",
  roster_created: "Roster created",
  negotiating: "Negotiating",
  done: "Done",
};

const STATUS_TONE = {
  pending: "pending",
  extracted: "progress",
  verified: "progress",
  roster_created: "done",
  negotiating: "progress",
  done: "done",
};

const EMPTY_STATE = {
  taskSpecId: null,
  status: null, // pending | extracted | verified | roster_created | negotiating | done
  sourceFilename: null,
  extractedJson: null,
  roster: [],
  resourcePools: [],
  overallReasoning: null,
  negotiationMode: null, // "dev" | "prod"
  negotiationTree: [],
};

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 24, filter: "blur(4px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  transition: { duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] },
});

export default function App() {
  const [state, setState] = useState(EMPTY_STATE);
  const [runningStage, setRunningStage] = useState(null);
  const [selectedStage, setSelectedStage] = useState("extract");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showLaunch, setShowLaunch] = useState(false);
  const [launchMode, setLaunchMode] = useState("prod");
  const [waitingForStep, setWaitingForStep] = useState(false);
  const [started, setStarted] = useState(false);
  const [tasks, setTasks] = useState([]);
  const socketRef = useRef(null);

  useEffect(() => {
    if (started && !state.taskSpecId) {
      fetchTasks().then(setTasks).catch(() => {});
    }
  }, [started, state.taskSpecId]);

  const applyServerState = useCallback((s) => {
    setState({
      taskSpecId: s.task_spec_id,
      status: s.status,
      sourceFilename: s.source_filename,
      extractedJson: s.extracted_json,
      roster: s.roster || [],
      resourcePools: s.resource_pools || [],
      overallReasoning: s.prime_overall_reasoning,
      negotiationMode: s.negotiation_mode || null,
      negotiationTree: s.negotiation_tree || [],
    });
    // A page reload can't see whether a dev-mode run is mid-step or just
    // paused waiting — either way "negotiating" + mode "dev" means a
    // "Next step" click is the right next action.
    setWaitingForStep(s.status === "negotiating" && s.negotiation_mode === "dev");
    if (s.negotiation_mode) setLaunchMode(s.negotiation_mode);
    setShowLaunch(false);
    if (s.status === "negotiating" || s.status === "done") setSelectedStage("negotiate");
    else setSelectedStage(s.status === "roster_created" ? "roster" : "extract");
  }, []);

  const connectSocket = useCallback((taskSpecId) => {
    socketRef.current?.close();
    socketRef.current = connectTaskSocket(taskSpecId, (msg) => {
      if (msg.type === "stage_started") {
        setRunningStage(msg.stage);
        setError(null);
        if (msg.stage === "negotiate") {
          // A fresh run (Submit / Re-run / Reset & Re-run) always replaces
          // the tree from turn 0 -- see negotiation_graph.py::run_negotiate.
          setState((s) => ({ ...s, status: "negotiating", negotiationTree: [] }));
        }
      } else if (msg.type === "negotiate_node") {
        setState((s) => {
          const tree = s.negotiationTree;
          if (msg.event === "created") {
            return { ...s, negotiationTree: [...tree, msg.node] };
          }
          if (msg.event === "continued" || msg.event === "reflected") {
            return {
              ...s,
              negotiationTree: tree.map((n) =>
                n.id === msg.node_id ? { ...n, entries: [...n.entries, msg.entry] } : n
              ),
            };
          }
          if (msg.event === "close_review") {
            // close_review carries no node_id -- graph.py's close_review_node
            // appends it to whichever node was current when the run ended,
            // which is always the last node already in the tree.
            if (tree.length === 0) return s;
            const lastId = tree[tree.length - 1].id;
            return {
              ...s,
              negotiationTree: tree.map((n) =>
                n.id === lastId ? { ...n, entries: [...n.entries, msg.entry] } : n
              ),
            };
          }
          if (msg.event === "tool_results") {
            return {
              ...s,
              negotiationTree: tree.map((n) =>
                n.id === msg.node_id ? { ...n, tool_results: [...n.tool_results, ...msg.tool_results] } : n
              ),
            };
          }
          return s;
        });
      } else if (msg.type === "stage_complete") {
        setRunningStage(null);
        if (msg.stage === "extract") {
          setSelectedStage("extract");
          setState((s) => ({ ...s, status: "extracted", extractedJson: msg.extracted_json }));
        } else if (msg.stage === "roster") {
          setSelectedStage("roster");
          setState((s) => ({
            ...s,
            status: "roster_created",
            roster: msg.roster || [],
            resourcePools: msg.resource_pools || [],
            overallReasoning: msg.overall_reasoning,
          }));
        } else if (msg.stage === "negotiate" || msg.stage === "negotiate_step") {
          setSelectedStage("negotiate");
          setWaitingForStep(!!msg.waiting_for_step);
          setState((s) => ({ ...s, status: msg.done ? "done" : "negotiating" }));
        }
      } else if (msg.type === "stage_failed") {
        setRunningStage(null);
        setError(`${msg.stage} failed: ${msg.error}`);
      }
    });
  }, []);

  // --- disabled for read-only server deploy (uncomment locally) ---
  // const handleUpload = useCallback(
  //   async (file) => {
  //     setError(null);
  //     setBusy(true);
  //     try {
  //       const { task_spec_id } = await uploadTaskFile(file);
  //       applyServerState({
  //         task_spec_id,
  //         status: "pending",
  //         source_filename: file.name,
  //         extracted_json: null,
  //         roster: [],
  //         resource_pools: [],
  //         prime_overall_reasoning: null,
  //       });
  //       connectSocket(task_spec_id);
  //     } catch (e) {
  //       setError(String(e));
  //     } finally {
  //       setBusy(false);
  //     }
  //   },
  //   [applyServerState, connectSocket]
  // );

  const loadTask = useCallback(
    async (id) => {
      if (!id) return;
      setError(null);
      setBusy(true);
      try {
        const s = await fetchTaskState(id);
        applyServerState(s);
        connectSocket(id);
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
      }
    },
    [applyServerState, connectSocket]
  );

  const handleBackToList = useCallback(() => {
    socketRef.current?.close();
    setState(EMPTY_STATE);
    setError(null);
  }, []);

  // --- disabled for read-only server deploy (uncomment locally) ---
  // const handleDeleteTask = useCallback(async (e, taskSpecId, filename) => {
  //   e.stopPropagation();
  //   if (!window.confirm(`Delete task #${taskSpecId} (${filename})? This can't be undone.`)) return;
  //   setError(null);
  //   try {
  //     await deleteTask(taskSpecId);
  //     setTasks((prev) => prev.filter((t) => t.task_spec_id !== taskSpecId));
  //   } catch (e2) {
  //     setError(String(e2));
  //   }
  // }, []);

  const handleRunStage = useCallback(
    async (stage) => {
      if (!state.taskSpecId) return;
      setError(null);
      setBusy(true);
      try {
        await runStage(state.taskSpecId, stage);
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
      }
    },
    [state.taskSpecId]
  );

  const handleVerify = useCallback(async () => {
    if (!state.taskSpecId) return;
    setError(null);
    setBusy(true);
    try {
      const s = await verifyTask(state.taskSpecId);
      applyServerState(s);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [state.taskSpecId, applyServerState]);

  const handleLaunchNegotiate = useCallback(
    async (mode, reset) => {
      if (!state.taskSpecId) return;
      setError(null);
      setBusy(true);
      try {
        await runStage(state.taskSpecId, "negotiate", { mode, reset });
        setState((s) => ({ ...s, negotiationMode: mode }));
        setShowLaunch(false);
        setSelectedStage("negotiate");
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
      }
    },
    [state.taskSpecId]
  );

  const handleStepNegotiate = useCallback(async () => {
    if (!state.taskSpecId) return;
    setError(null);
    setBusy(true);
    try {
      await runStage(state.taskSpecId, "negotiate_step");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [state.taskSpecId]);

  const stepState = (key) => {
    if (key === "extract") {
      if (runningStage === "extract") return "active";
      return state.status === "pending" ? "pending" : "done";
    }
    if (key === "roster") {
      if (runningStage === "roster") return "active";
      if (["roster_created", "negotiating", "done"].includes(state.status)) return "done";
      return "pending";
    }
    if (key === "negotiate") {
      if (runningStage === "negotiate" || runningStage === "negotiate_step") return "active";
      if (state.status === "done") return "done";
      if (state.status === "negotiating") return "active";
      return "pending";
    }
    return "pending";
  };

  // --- disabled for read-only server deploy (uncomment locally) ---
  // Covers extract run/re-run, roster build/re-run/submit/launch, and
  // negotiate step/re-run/reset -- every backend run-triggering control.
  const renderActions = () => {
    // if (selectedStage === "extract") {
    //   return state.status === "pending" ? (
    //     <button disabled={busy || runningStage} onClick={() => handleRunStage("extract")}>
    //       {runningStage === "extract" ? "Extracting…" : "Run extraction"}
    //     </button>
    //   ) : (
    //     <button className="btn-secondary" disabled={busy || runningStage} onClick={() => handleRunStage("extract")}>
    //       <RefreshIcon /> Re-run
    //     </button>
    //   );
    // }
    // if (selectedStage === "roster") {
    //   if (state.status === "verified") {
    //     return (
    //       <button disabled={busy || runningStage} onClick={() => handleRunStage("roster")}>
    //         {runningStage === "roster" ? "Building…" : "Build roster"}
    //       </button>
    //     );
    //   }
    //   if (["roster_created", "negotiating", "done"].includes(state.status)) {
    //     return (
    //       <div className="launch-row">
    //         <button className="btn-secondary" disabled={busy || runningStage} onClick={() => handleRunStage("roster")}>
    //           <RefreshIcon /> Re-run
    //         </button>
    //         {!showLaunch && (
    //           <button disabled={busy || runningStage} onClick={() => setShowLaunch(true)}>
    //             Submit
    //           </button>
    //         )}
    //         {showLaunch && (
    //           <>
    //             <div className="mode-toggle">
    //               <button type="button" data-active={launchMode === "dev"} onClick={() => setLaunchMode("dev")}>
    //                 Dev mode
    //               </button>
    //               <button type="button" data-active={launchMode === "prod"} onClick={() => setLaunchMode("prod")}>
    //                 Prod mode
    //               </button>
    //             </div>
    //             <button
    //               disabled={busy || runningStage}
    //               onClick={() => handleLaunchNegotiate(launchMode, false)}
    //             >
    //               Start negotiation
    //             </button>
    //             <button className="btn-secondary" disabled={busy || runningStage} onClick={() => setShowLaunch(false)}>
    //               Cancel
    //             </button>
    //           </>
    //         )}
    //       </div>
    //     );
    //   }
    //   return null;
    // }
    // if (selectedStage === "negotiate") {
    //   if (!["negotiating", "done"].includes(state.status)) return null;
    //   return (
    //     <div className="launch-row">
    //       {state.status === "negotiating" && state.negotiationMode === "dev" && waitingForStep && (
    //         <button disabled={busy || runningStage} onClick={handleStepNegotiate}>
    //           {runningStage === "negotiate_step" ? "Running…" : "Next step"}
    //         </button>
    //       )}
    //       <button
    //         className="btn-secondary"
    //         disabled={busy || runningStage}
    //         onClick={() => handleLaunchNegotiate(state.negotiationMode || "prod", false)}
    //       >
    //         <RefreshIcon /> Re-run
    //       </button>
    //       <button
    //         className="btn-secondary"
    //         disabled={busy || runningStage}
    //         onClick={() => handleLaunchNegotiate(state.negotiationMode || "prod", true)}
    //       >
    //         <RefreshIcon /> Reset &amp; Re-run
    //       </button>
    //     </div>
    //   );
    // }
    return null;
  };

  const renderScreen = () => {
    if (selectedStage === "extract") {
      if (!state.extractedJson) {
        return <div className="placeholder-screen">This stage hasn't run yet.</div>;
      }
      return (
        <>
          <pre className="json-viewer">{JSON.stringify(state.extractedJson, null, 2)}</pre>
          {/* --- disabled for read-only server deploy (uncomment locally) ---
          {state.status === "extracted" && (
            <div style={{ marginTop: 20 }}>
              <button disabled={busy} onClick={handleVerify}>
                Verify &amp; continue
              </button>
            </div>
          )}
          --- */}
        </>
      );
    }
    if (selectedStage === "roster") {
      if (state.roster.length === 0) {
        return (
          <div className="placeholder-screen">
            {state.status === "verified"
              ? "Spec verified — click Build roster to have Prime staff the team."
              : "Verify the extracted spec first."}
          </div>
        );
      }
      return (
        <>
          {state.overallReasoning && <p className="reasoning-text">{state.overallReasoning}</p>}
          <AgentPipeline roster={state.roster} />
        </>
      );
    }
    if (selectedStage === "negotiate") {
      if (state.negotiationTree.length === 0) {
        return (
          <div className="placeholder-screen">
            {state.status === "roster_created"
              ? "Click Submit on the Roster tab to send the roster to work."
              : "Waiting for the first turn…"}
          </div>
        );
      }
      const canEditSandbox =
        state.status === "negotiating" && state.negotiationMode === "dev" && waitingForStep;
      return (
        <>
          <NegotiationTree nodes={state.negotiationTree} />
          <div className="sandbox-browser-section">
            <p className="section-label">
              <span className="num">03</span> Sandbox state
              {canEditSandbox && <span className="paused-badge">paused — editable</span>}
            </p>
            <SandboxBrowser taskSpecId={state.taskSpecId} editable={canEditSandbox} />
          </div>
        </>
      );
    }
    return null;
  };

  if (!started) {
    return <LandingPage onStart={() => setStarted(true)} />;
  }

  return (
    <div className="app">
      <motion.div className="app-header" initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <div className="app-header-left">
          <button
            className="btn-secondary btn-tiny"
            onClick={() => (state.taskSpecId ? handleBackToList() : setStarted(false))}
          >
            ← Back
          </button>
          <span className="logo">
            AGN<em>IES</em>
          </span>
        </div>
        <div className="app-header-center">
          {state.taskSpecId ? (
            <span className="header-task-meta">
              <span className="task-id">#{state.taskSpecId}</span>
              <span className="filename">{state.sourceFilename}</span>
            </span>
          ) : (
            <span className="tagline">Sandboxed multi-agent task execution</span>
          )}
        </div>
        <div className="app-header-right">
          {state.taskSpecId && (
            <span className="status-indicator" data-tone={STATUS_TONE[state.status] || "pending"}>
              <span className="status-dot" />
              {runningStage ? `Running ${runningStage}…` : STATUS_LABEL[state.status] || state.status}
            </span>
          )}
          <div className="profile-badge">
            <span className="profile-avatar">
              <UserIcon />
            </span>
            <span className="profile-name">Guest</span>
          </div>
        </div>
      </motion.div>

      {!state.taskSpecId && (
        <TiltCard className="panel" max={2} {...fadeUp(0.1)}>
          <div className="stage-screen-header">
            <p className="section-label">
              <span className="num">01</span> Processed tasks
            </p>
            {/* --- disabled for read-only server deploy (uncomment locally) ---
            <label className="upload-btn" data-busy={busy}>
              <UploadIcon />
              Upload task brief
              <input
                type="file"
                accept=".md"
                disabled={busy}
                onChange={(e) => e.target.files[0] && handleUpload(e.target.files[0])}
              />
            </label>
            --- */}
          </div>
          {error && <div className="error-box">{error}</div>}

          {tasks.length === 0 ? (
            <div className="placeholder-screen">No tasks yet.</div>
          ) : (
            <table className="task-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Filename</th>
                  <th>Objective</th>
                  <th>Status</th>
                  {/* <th /> disabled for read-only server deploy (uncomment locally, was the delete-action column) */}
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.task_spec_id} onClick={() => loadTask(t.task_spec_id)}>
                    <td>#{t.task_spec_id}</td>
                    <td>{t.source_filename}</td>
                    <td className="task-table-objective">{t.objective || "—"}</td>
                    <td>
                      <span className="status-indicator" data-tone={STATUS_TONE[t.status] || "pending"}>
                        <span className="status-dot" />
                        {STATUS_LABEL[t.status] || t.status}
                      </span>
                    </td>
                    {/* --- disabled for read-only server deploy (uncomment locally) ---
                    <td className="task-table-actions">
                      <button
                        className="icon-btn icon-btn-danger"
                        title="Delete task"
                        onClick={(e) => handleDeleteTask(e, t.task_spec_id, t.source_filename)}
                      >
                        <TrashIcon />
                      </button>
                    </td>
                    --- */}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </TiltCard>
      )}

      <AnimatePresence mode="wait">
        {state.taskSpecId && (
          <motion.div key={state.taskSpecId} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
            <motion.div {...fadeUp(0.08)}>
              <StageStepper stages={STAGES} stateOf={stepState} selected={selectedStage} onSelect={setSelectedStage} />
            </motion.div>

            <TiltCard className="panel" max={1.5} key={selectedStage} {...fadeUp(0.12)}>
              <div className="stage-screen-header">
                <div className="stage-title-row">
                  <p className="section-label">
                    <span className="num">{String(STAGES.findIndex((s) => s.key === selectedStage) + 1).padStart(2, "0")}</span>
                    {selectedStage}
                  </p>
                  <div className="stage-title">{STAGE_TITLE[selectedStage]}</div>
                </div>
                <div className="actions">{renderActions()}</div>
              </div>
              {renderScreen()}
              {error && <div className="error-box">{error}</div>}
            </TiltCard>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
