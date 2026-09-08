import { useCallback, useEffect, useState } from "react";
import { fetchSandboxFile, fetchSandboxFiles, writeSandboxFile } from "./api.js";

// §8.3: inspect/edit a task's sandbox files while a dev-mode negotiation
// run is paused between steps (see App.jsx's "Next step" flow). Writing is
// only accepted by the backend while status="negotiating" (core/views.py's
// sandbox_file_view) -- editable here follows that same gate, not a
// separate frontend-only check, so a stale UI state can never claim a save
// will work when the server would actually 409 it.
export default function SandboxBrowser({ taskSpecId, editable }) {
  const [files, setFiles] = useState([]);
  const [selected, setSelected] = useState(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const reloadFiles = useCallback(async () => {
    if (!taskSpecId) return;
    try {
      const list = await fetchSandboxFiles(taskSpecId);
      setFiles(list);
    } catch (e) {
      setError(String(e));
    }
  }, [taskSpecId]);

  useEffect(() => {
    reloadFiles();
  }, [reloadFiles]);

  const openFile = useCallback(
    async (path) => {
      setSelected(path);
      setError(null);
      setLoading(true);
      try {
        const text = await fetchSandboxFile(taskSpecId, path);
        setContent(text);
        setSavedContent(text);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [taskSpecId]
  );

  const handleSave = useCallback(async () => {
    if (!selected) return;
    setError(null);
    setSaving(true);
    try {
      await writeSandboxFile(taskSpecId, selected, content);
      setSavedContent(content);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }, [taskSpecId, selected, content]);

  const dirty = content !== savedContent;

  return (
    <div className="sandbox-browser">
      <div className="sandbox-file-list">
        <div className="sandbox-file-list-header">
          <span>Sandbox files</span>
          <button type="button" className="btn-secondary btn-tiny" onClick={reloadFiles}>
            Refresh
          </button>
        </div>
        {files.length === 0 && <div className="sandbox-empty">No files written yet.</div>}
        {files.map((path) => (
          <button
            type="button"
            key={path}
            className="sandbox-file-row"
            data-selected={path === selected}
            onClick={() => openFile(path)}
          >
            {path}
          </button>
        ))}
      </div>

      <div className="sandbox-file-view">
        {!selected && <div className="sandbox-empty">Select a file to view{editable ? " or edit" : ""} it.</div>}
        {selected && (
          <>
            <div className="sandbox-file-view-header">
              <span className="path-chip">{selected}</span>
              {editable ? (
                <button
                  type="button"
                  disabled={!dirty || saving}
                  onClick={handleSave}
                >
                  {saving ? "Saving…" : dirty ? "Save" : "Saved"}
                </button>
              ) : (
                <span className="hint-text">Read-only — pause a dev-mode run to edit</span>
              )}
            </div>
            {loading ? (
              <div className="sandbox-empty">Loading…</div>
            ) : (
              <textarea
                className="sandbox-file-editor"
                value={content}
                readOnly={!editable}
                spellCheck={false}
                onChange={(e) => setContent(e.target.value)}
              />
            )}
          </>
        )}
      </div>

      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
