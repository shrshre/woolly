import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import * as api from "../api/client";
import { useAuth } from "./AuthContext";

interface SavedPatternsValue {
  savedIds: Set<number>;
  /** Optimistically toggle a save; reverts on API failure. */
  toggleSave: (ravelryId: number) => Promise<void>;
}

const SavedPatternsContext = createContext<SavedPatternsValue | null>(null);

export function SavedPatternsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!user) {
      setSavedIds(new Set());
      return;
    }
    api
      .fetchLibrary()
      .then((lib) => setSavedIds(new Set(lib.patterns.map((p) => p.id))))
      .catch(() => setSavedIds(new Set()));
  }, [user]);

  async function toggleSave(ravelryId: number) {
    const wasSaved = savedIds.has(ravelryId);
    setSavedIds((prev) => {
      const next = new Set(prev);
      if (wasSaved) next.delete(ravelryId);
      else next.add(ravelryId);
      return next;
    });

    try {
      if (wasSaved) await api.unsavePattern(ravelryId);
      else await api.savePattern(ravelryId);
    } catch {
      // Revert the optimistic update
      setSavedIds((prev) => {
        const next = new Set(prev);
        if (wasSaved) next.add(ravelryId);
        else next.delete(ravelryId);
        return next;
      });
    }
  }

  return (
    <SavedPatternsContext.Provider value={{ savedIds, toggleSave }}>
      {children}
    </SavedPatternsContext.Provider>
  );
}

export function useSavedPatterns(): SavedPatternsValue {
  const ctx = useContext(SavedPatternsContext);
  if (!ctx) throw new Error("useSavedPatterns must be used within SavedPatternsProvider");
  return ctx;
}
