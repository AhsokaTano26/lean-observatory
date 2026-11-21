import { useEffect, useRef, useState } from "react";
import type { Snapshot, Log, Metrics } from "../types";
import { mergeSamples, chartSample } from "../chartMath";

export function useObservatory() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [logs, setLogs] = useState<Log[]>([]),
    [history, setHistory] = useState<Metrics[]>([]);
  const [connection, setConnection] = useState<
      "connecting" | "live" | "reconnecting"
    >("connecting"),
    [error, setError] = useState<string | null>(null);
  const currentRun = useRef<string | null>(null);
  useEffect(() => {
    let disposed = false;
    fetch("/api/state")
      .then((r) => {
        if (!r.ok) throw Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((p) => {
        if (!disposed) setSnapshot(p);
      })
      .catch((e) => {
        if (!disposed) setError(e.message);
      });
    let stream: EventSource;
    let cursor = "0";
    let lastMessage = Date.now();
    const loadHistory = (requestedRun = currentRun.current) =>
      fetch(
        "/api/history" +
          (requestedRun ? "?run=" + encodeURIComponent(requestedRun) : ""),
      )
        .then((r) => r.json())
        .then((samples: Metrics[]) => {
          if (!disposed && requestedRun === currentRun.current)
            setHistory((old) => mergeSamples(old, samples.map(chartSample)));
        })
        .catch(() => {});
    const receive = (event: Event) => {
      const p: Snapshot = JSON.parse((event as MessageEvent).data);
      if (disposed) return;
      cursor = (event as MessageEvent).lastEventId || cursor;
      lastMessage = Date.now();
      setSnapshot(p);
      setConnection("live");
      const changed = currentRun.current !== p.run.id;
      currentRun.current = p.run.id;
      const sample = chartSample({
        ...p.metrics,
        sampledAt: p.metrics.stale
          ? p.serverTime
          : (p.metrics.sampledAt ?? p.serverTime),
        observedAt: p.serverTime,
        runId: p.run.id || undefined,
        mode: p.run.mode,
        rate: p.run.compile.rate,
        completed: p.run.compile.succeeded,
      });
      setHistory((old) => mergeSamples(changed ? [] : old, [sample]));
      if (changed) loadHistory(p.run.id);
      setLogs((old) => {
        const list = changed ? [] : old;
        const ids = new Set(list.map((l) => l.id));
        return [...list, ...(p.logs || []).filter((l) => !ids.has(l.id))].slice(
          -500,
        );
      });
    };
    const connect = () => {
      stream?.close();
      stream = new EventSource(
        "/api/events" + (cursor === "0" ? "" : "?after=" + cursor),
      );
      stream.addEventListener("snapshot", receive);
      stream.onerror = () => {
        if (!disposed) setConnection("reconnecting");
      };
    };
    const offline = () => {
      stream?.close();
      setConnection("reconnecting");
    };
    const online = () => {
      lastMessage = Date.now();
      connect();
    };
    connect();
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    const watchdog = setInterval(() => {
      if (Date.now() - lastMessage > 8000) {
        setConnection("reconnecting");
        if (navigator.onLine) {
          lastMessage = Date.now();
          connect();
        }
      }
    }, 2000);
    loadHistory();
    const interval = setInterval(() => loadHistory(), 5000);
    return () => {
      disposed = true;
      stream.close();
      clearInterval(interval);
      clearInterval(watchdog);
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
    };
  }, []);
  return {
    snapshot: snapshot
      ? {
          ...snapshot,
          metrics: {
            ...snapshot.metrics,
            stale: snapshot.metrics.stale || connection !== "live",
          },
        }
      : null,
    logs,
    history:
      snapshot?.run.mode === "mock"
        ? history.filter((m) => m.runId === snapshot.run.id)
        : history.filter((m) => m.mode !== "mock"),
    connection,
    error,
    clearError: () => setError(null),
  };
}
