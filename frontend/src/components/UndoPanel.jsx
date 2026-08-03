import { useEffect, useState } from "react";
import { api } from "../api";

const COLLECTION_LABEL = {
  gear: "Gear",
  goals: "Goal",
  workouts: "Workout",
  strength_sessions: "Strength session",
};

function itemName(entry) {
  const item = entry.item;
  return item.name || item.title || item.date || "item";
}

// Global, not per-view: deletions happen from Gear/Plan/Builder, all
// different screens, but there's one shared undo history rather than one
// per surface. Motivated by a real incident (see batch_5 memory) where a
// gear entry was deleted with nothing to recover it from.
export default function UndoPanel() {
  const [open, setOpen] = useState(false);
  const [log, setLog] = useState([]);

  const load = () => api.undoLog().then(setLog).catch(() => {});

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000); // catch deletions made elsewhere in the app
    return () => clearInterval(interval);
  }, []);

  const restore = async (id) => {
    await api.restoreUndo(id);
    load();
  };

  if (log.length === 0 && !open) return null;

  return (
    <div className="undo-panel">
      <button className="followup-btn" onClick={() => setOpen((v) => !v)}>
        ↩ Recently deleted{log.length ? ` (${log.length})` : ""}
      </button>
      {open && (
        <div className="undo-dropdown">
          {log.length === 0 ? (
            <div className="empty-note">Nothing to restore.</div>
          ) : (
            log.map((entry) => (
              <div className="undo-row" key={entry.id}>
                <span>
                  <span className="plan-badge badge-muted">{COLLECTION_LABEL[entry.collection] ?? entry.collection}</span>{" "}
                  {itemName(entry)}
                </span>
                <button className="followup-btn" onClick={() => restore(entry.id)}>
                  Restore
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
