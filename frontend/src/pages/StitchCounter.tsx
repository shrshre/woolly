// Voice-activated stitch counter (Web Speech API).
// Commands: "count" / "stitch", "next row", "undo", "reset" (then "yes" / "no").
// Recognition is continuous and auto-restarts, so it stays hands-free.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fetchProjects, updateProject, type Project } from "../api/client";

type VoiceStatus = "listening" | "idle" | "error" | "unsupported";
type CounterAction = { type: "count" } | { type: "row"; prevStitch: number };

// Minimal typing for the (still vendor-prefixed) Web Speech API
interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: any) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: any) => void) | null;
  start: () => void;
  stop: () => void;
}

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const COMMAND_RE = /next row|new row|count|stitch|undo|reset|yes|confirm|no|cancel/g;
const SAVE_DEBOUNCE_MS = 1200;

export function StitchCounter() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [stitches, setStitches] = useState(0);
  const [rows, setRows] = useState(0);
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [micOn, setMicOn] = useState(true);
  const [lastHeard, setLastHeard] = useState<string | null>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "unsaved">("saved");

  const historyRef = useRef<CounterAction[]>([]);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const micOnRef = useRef(micOn);
  const confirmingRef = useRef(confirmingReset);
  const saveTimerRef = useRef<number | null>(null);
  const countsRef = useRef({ stitches: 0, rows: 0 });
  const projectIdRef = useRef<number | null>(null);

  micOnRef.current = micOn;
  confirmingRef.current = confirmingReset;
  countsRef.current = { stitches, rows };
  projectIdRef.current = projectId;

  // Load active projects; default to the first
  useEffect(() => {
    fetchProjects()
      .then((res) => {
        const active = res.projects.filter((p) => p.status === "active");
        const list = active.length > 0 ? active : res.projects;
        setProjects(list);
        if (list.length > 0) {
          setProjectId(list[0].id);
          setStitches(list[0].stitch_count);
          setRows(list[0].row_count);
        }
      })
      .catch(() => setProjects([]));
  }, []);

  const scheduleSave = useCallback(() => {
    setSaveState("unsaved");
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(async () => {
      const id = projectIdRef.current;
      if (id === null) return;
      setSaveState("saving");
      try {
        await updateProject(id, {
          stitch_count: countsRef.current.stitches,
          row_count: countsRef.current.rows,
        });
        setSaveState("saved");
      } catch {
        setSaveState("unsaved");
      }
    }, SAVE_DEBOUNCE_MS);
  }, []);

  const doCount = useCallback(() => {
    historyRef.current.push({ type: "count" });
    setStitches((s) => s + 1);
    scheduleSave();
  }, [scheduleSave]);

  const doNextRow = useCallback(() => {
    historyRef.current.push({ type: "row", prevStitch: countsRef.current.stitches });
    setRows((r) => r + 1);
    setStitches(0);
    scheduleSave();
  }, [scheduleSave]);

  const doUndo = useCallback(() => {
    const last = historyRef.current.pop();
    if (!last) return;
    if (last.type === "count") {
      setStitches((s) => Math.max(0, s - 1));
    } else {
      setRows((r) => Math.max(0, r - 1));
      setStitches(last.prevStitch);
    }
    scheduleSave();
  }, [scheduleSave]);

  const doReset = useCallback(() => {
    historyRef.current = [];
    setStitches(0);
    setRows(0);
    setConfirmingReset(false);
    scheduleSave();
  }, [scheduleSave]);

  const handleCommand = useCallback(
    (command: string) => {
      if (confirmingRef.current) {
        if (command === "yes" || command === "confirm" || command === "reset") doReset();
        else if (command === "no" || command === "cancel") setConfirmingReset(false);
        return;
      }
      switch (command) {
        case "count":
        case "stitch":
          doCount();
          break;
        case "next row":
        case "new row":
          doNextRow();
          break;
        case "undo":
          doUndo();
          break;
        case "reset":
          setConfirmingReset(true);
          break;
      }
    },
    [doCount, doNextRow, doUndo, doReset]
  );

  // Speech recognition lifecycle
  useEffect(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      setStatus("unsupported");
      return;
    }

    const recognition = new Ctor();
    recognitionRef.current = recognition;
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (!result.isFinal) continue;
        const transcript: string = result[0].transcript.toLowerCase().trim();
        setLastHeard(transcript);
        const matches = transcript.match(COMMAND_RE);
        if (matches) matches.forEach((m) => handleCommand(m));
      }
    };

    recognition.onend = () => {
      // Chrome stops recognition periodically; restart to stay hands-free
      if (micOnRef.current) {
        try {
          recognition.start();
        } catch {
          setStatus("idle");
        }
      } else {
        setStatus("idle");
      }
    };

    recognition.onerror = (event: any) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setStatus("error");
        setMicOn(false);
      }
      // "no-speech" and "aborted" are routine; onend handles the restart
    };

    if (micOnRef.current) {
      try {
        recognition.start();
        setStatus("listening");
      } catch {
        setStatus("error");
      }
    }

    return () => {
      micOnRef.current = false;
      recognition.onend = null;
      recognition.stop();
    };
  }, [handleCommand]);

  function toggleMic() {
    const recognition = recognitionRef.current;
    if (!recognition) return;
    if (micOn) {
      setMicOn(false);
      recognition.stop();
      setStatus("idle");
    } else {
      setMicOn(true);
      try {
        recognition.start();
        setStatus("listening");
      } catch {
        // already started
      }
      setStatus("listening");
    }
  }

  function switchProject(id: number) {
    setProjectId(id);
    const project = projects.find((p) => p.id === id);
    if (project) {
      setStitches(project.stitch_count);
      setRows(project.row_count);
      historyRef.current = [];
      setSaveState("saved");
    }
  }

  const statusMeta: Record<VoiceStatus, { label: string; className: string }> = {
    listening: { label: "Listening", className: "voice-status listening" },
    idle: { label: "Not listening", className: "voice-status idle" },
    error: { label: "Microphone blocked — check browser permissions", className: "voice-status error" },
    unsupported: {
      label: "Voice not supported in this browser — buttons still work",
      className: "voice-status error",
    },
  };

  if (projects.length === 0) {
    return (
      <section className="counter-page">
        <h1 className="library-title">Stitch counter</h1>
        <p className="library-empty">
          The counter saves to an active project. <Link to="/projects">Create a project</Link>{" "}
          first, then come back.
        </p>
      </section>
    );
  }

  return (
    <section className="counter-page">
      <div className="counter-top">
        <select
          className="project-status-select"
          value={projectId ?? ""}
          onChange={(e) => switchProject(Number(e.target.value))}
          aria-label="Project"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.pattern.name}
            </option>
          ))}
        </select>
        <span className="counter-save-state">
          {saveState === "saved" ? "Saved" : saveState === "saving" ? "Saving…" : "Unsaved"}
        </span>
      </div>

      <div className={statusMeta[status].className} role="status">
        <span className="voice-dot" aria-hidden="true"></span>
        {statusMeta[status].label}
      </div>

      <div className="counter-display">
        <div className="counter-block">
          <span className="counter-number">{stitches}</span>
          <span className="counter-label">stitches</span>
        </div>
        <div className="counter-block counter-rows">
          <span className="counter-number-sm">{rows}</span>
          <span className="counter-label">rows</span>
        </div>
      </div>

      {lastHeard && <p className="counter-heard">heard: “{lastHeard}”</p>}

      {confirmingReset ? (
        <div className="counter-confirm" role="alertdialog" aria-label="Confirm reset">
          <p className="counter-confirm-text">Reset both counters? Say “yes” or “no”.</p>
          <div className="counter-actions">
            <button type="button" className="btn-primary" onClick={doReset}>
              Yes, reset
            </button>
            <button type="button" className="btn-ghost" onClick={() => setConfirmingReset(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="counter-actions">
          <button type="button" className="btn-primary counter-btn" onClick={doCount}>
            Count
          </button>
          <button type="button" className="btn-ghost counter-btn" onClick={doNextRow}>
            Next row
          </button>
          <button type="button" className="btn-ghost counter-btn" onClick={doUndo}>
            Undo
          </button>
          <button type="button" className="btn-ghost counter-btn" onClick={() => setConfirmingReset(true)}>
            Reset
          </button>
          <button
            type="button"
            className={micOn ? "btn-ghost counter-btn tool-active" : "btn-ghost counter-btn"}
            onClick={toggleMic}
            aria-pressed={micOn}
          >
            <i className={micOn ? "ti ti-microphone" : "ti ti-microphone-off"} aria-hidden="true"></i>{" "}
            {micOn ? "Mic on" : "Mic off"}
          </button>
        </div>
      )}

      <p className="counter-help">
        Say <strong>“count”</strong> for each stitch, <strong>“next row”</strong> to finish a row,{" "}
        <strong>“undo”</strong> to take back the last action, or <strong>“reset”</strong> to start
        over.
      </p>
    </section>
  );
}
