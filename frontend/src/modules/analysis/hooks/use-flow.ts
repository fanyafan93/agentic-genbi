"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type SetStateAction } from "react";
import { getAgentClient } from "@/modules/analysis/agentClients";
import type { AgentClient, AgentEvent, AgentInput } from "@/modules/analysis/agentClients";
import type { ArtifactFolder, ArtifactKind } from "../types/artifact";
import type { InteractiveReport } from "../types/interactive-report";

export type FlowRole = "user" | "agent" | "ask";

export type FlowActivity =
  | { kind: "message"; content: string; itemId?: string }
  | { kind: "reasoning"; content: string; itemId: string }
  | {
      kind: "tool";
      label: string;
      state: "queued" | "running" | "done" | "failed";
      detail?: string;
      details?: string[];
      itemId?: string;
      count?: number;
    };

export type FlowNode =
  | { id: string; role: "user"; content: string }
  | {
      id: string;
      role: "agent";
      content: string;
      mode?: "replace" | "delta";
      thinking?: boolean;
      steps?: { label: string; state: "queued" | "running" | "done" | "failed"; detail?: string; itemId?: string }[];
      activity?: FlowActivity[];
      activeItemId?: string;
      processRunning?: boolean;
      processStartedAt?: string;
      processCompletedAt?: string;
      debug?: { title: string; content: string }[];
    }
  | { id: string; role: "ask"; question: string; options: { id: string; label: string }[]; current?: boolean };

export type FlowCodexLineage = {
  sourceCodexThreadId?: string;
  sourceCodexTurnId?: string;
  sourceCodexItemId?: string;
};

type FlowSessionSnapshot = {
  currentTurnId: string | null;
  nodes: FlowNode[];
  artifacts: ArtifactFolder[];
  reportArtifact: InteractiveReport | null;
  codexLineage: FlowCodexLineage;
  running: boolean;
};

const NEW_FLOW_SESSION_KEY = "__new_analysis_session__";

export const STEP_INITIAL = ["识别业务口径", "查询可用数据表", "生成并校验 SQL", "整理图表与结论"];

export function useFlow(
  sessionId: string | null,
  initial: FlowNode[] = [],
  options: {
    onSessionCreated?: (sessionId: string) => void;
    onTurnSettled?: (sessionId: string) => Promise<FlowNode[] | undefined>;
  } = {},
) {
  const initialSignature = useMemo(() => flowNodeSignature(initial), [initial]);
  const firstSessionKey = flowSessionKey(sessionId);
  const sessionIdRef = useRef(sessionId);
  const activeSessionKeyRef = useRef(firstSessionKey);
  const mutationSessionKeyRef = useRef<string | null>(null);
  const sessionSnapshotsRef = useRef<Map<string, FlowSessionSnapshot>>(new Map([
    [firstSessionKey, createFlowSessionSnapshot(initial)],
  ]));
  const sessionAgentsRef = useRef<Map<string, AgentClient>>(new Map());
  const activeRunTokensRef = useRef<Map<string, symbol>>(new Map());
  const cancelledRunTokensRef = useRef<Set<symbol>>(new Set());
  const stoppingPromisesRef = useRef<Map<string, Promise<void>>>(new Map());

  const [currentTurnId, setDisplayedCurrentTurnId] = useState<string | null>(null);
  const [nodes, setDisplayedNodes] = useState<FlowNode[]>(initial);
  const [artifacts, setDisplayedArtifacts] = useState<ArtifactFolder[]>([]);
  const [reportArtifact, setDisplayedReportArtifact] = useState<InteractiveReport | null>(null);
  const [codexLineage, setDisplayedCodexLineage] = useState<FlowCodexLineage>({});
  const [running, setDisplayedRunning] = useState(false);

  const displaySnapshot = useCallback((snapshot: FlowSessionSnapshot) => {
    setDisplayedCurrentTurnId(snapshot.currentTurnId);
    setDisplayedNodes(snapshot.nodes);
    setDisplayedArtifacts(snapshot.artifacts);
    setDisplayedReportArtifact(snapshot.reportArtifact);
    setDisplayedCodexLineage(snapshot.codexLineage);
    setDisplayedRunning(snapshot.running);
  }, []);

  const updateSessionSnapshot = useCallback((
    sessionKey: string,
    update: (snapshot: FlowSessionSnapshot) => FlowSessionSnapshot,
  ): FlowSessionSnapshot => {
    const current = sessionSnapshotsRef.current.get(sessionKey) ?? createFlowSessionSnapshot([]);
    const next = update(current);
    sessionSnapshotsRef.current.set(sessionKey, next);
    if (activeSessionKeyRef.current === sessionKey) displaySnapshot(next);
    return next;
  }, [displaySnapshot]);

  const mutationKey = useCallback(
    () => mutationSessionKeyRef.current ?? activeSessionKeyRef.current,
    [],
  );
  const setCurrentTurnId = useCallback((update: SetStateAction<string | null>) => {
    const key = mutationKey();
    updateSessionSnapshot(key, (snapshot) => ({
      ...snapshot,
      currentTurnId: resolveStateAction(update, snapshot.currentTurnId),
    }));
  }, [mutationKey, updateSessionSnapshot]);
  const setNodes = useCallback((update: SetStateAction<FlowNode[]>) => {
    const key = mutationKey();
    updateSessionSnapshot(key, (snapshot) => ({
      ...snapshot,
      nodes: resolveStateAction(update, snapshot.nodes),
    }));
  }, [mutationKey, updateSessionSnapshot]);
  const setArtifacts = useCallback((update: SetStateAction<ArtifactFolder[]>) => {
    const key = mutationKey();
    updateSessionSnapshot(key, (snapshot) => ({
      ...snapshot,
      artifacts: resolveStateAction(update, snapshot.artifacts),
    }));
  }, [mutationKey, updateSessionSnapshot]);
  const setReportArtifact = useCallback((update: SetStateAction<InteractiveReport | null>) => {
    const key = mutationKey();
    updateSessionSnapshot(key, (snapshot) => ({
      ...snapshot,
      reportArtifact: resolveStateAction(update, snapshot.reportArtifact),
    }));
  }, [mutationKey, updateSessionSnapshot]);
  const setCodexLineage = useCallback((update: SetStateAction<FlowCodexLineage>) => {
    const key = mutationKey();
    updateSessionSnapshot(key, (snapshot) => ({
      ...snapshot,
      codexLineage: resolveStateAction(update, snapshot.codexLineage),
    }));
  }, [mutationKey, updateSessionSnapshot]);
  const setRunning = useCallback((update: SetStateAction<boolean>) => {
    const key = mutationKey();
    updateSessionSnapshot(key, (snapshot) => ({
      ...snapshot,
      running: resolveStateAction(update, snapshot.running),
    }));
  }, [mutationKey, updateSessionSnapshot]);

  const getSessionAgent = useCallback((sessionKey: string): AgentClient => {
    let agent = sessionAgentsRef.current.get(sessionKey);
    if (!agent) {
      agent = getAgentClient(sessionKey);
      sessionAgentsRef.current.set(sessionKey, agent);
    }
    return agent;
  }, []);

  const rekeySession = useCallback((fromKey: string, toSessionId: string): string => {
    const toKey = flowSessionKey(toSessionId);
    if (fromKey === toKey) return toKey;
    const snapshot = sessionSnapshotsRef.current.get(fromKey);
    if (snapshot) {
      sessionSnapshotsRef.current.set(toKey, snapshot);
      sessionSnapshotsRef.current.delete(fromKey);
    }
    const agent = sessionAgentsRef.current.get(fromKey);
    if (agent) {
      sessionAgentsRef.current.set(toKey, agent);
      sessionAgentsRef.current.delete(fromKey);
    }
    const activeRunToken = activeRunTokensRef.current.get(fromKey);
    if (activeRunToken) {
      activeRunTokensRef.current.set(toKey, activeRunToken);
      activeRunTokensRef.current.delete(fromKey);
    }
    const stoppingPromise = stoppingPromisesRef.current.get(fromKey);
    if (stoppingPromise) {
      stoppingPromisesRef.current.set(toKey, stoppingPromise);
      stoppingPromisesRef.current.delete(fromKey);
    }
    if (activeSessionKeyRef.current === fromKey) {
      activeSessionKeyRef.current = toKey;
      if (snapshot) displaySnapshot(snapshot);
    }
    return toKey;
  }, [displaySnapshot]);

  const onSessionCreatedRef = useRef(options.onSessionCreated);
  const onTurnSettledRef = useRef(options.onTurnSettled);
  useEffect(() => {
    onSessionCreatedRef.current = options.onSessionCreated;
    onTurnSettledRef.current = options.onTurnSettled;
  }, [options.onSessionCreated, options.onTurnSettled]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
    const sessionKey = flowSessionKey(sessionId);
    activeSessionKeyRef.current = sessionKey;
    mutationSessionKeyRef.current = null;
    const existing = sessionSnapshotsRef.current.get(sessionKey);
    const shouldHydrateHistory = Boolean(
      existing
      && !existing.running
      && initial.length > 0
      && flowNodeSignature(existing.nodes) !== initialSignature
    );
    const snapshot = existing
      ? (shouldHydrateHistory ? { ...existing, nodes: [...initial] } : existing)
      : createFlowSessionSnapshot(initial);
    sessionSnapshotsRef.current.set(sessionKey, snapshot);
    displaySnapshot(snapshot);
  }, [displaySnapshot, initial, initialSignature, sessionId]);

  useEffect(() => () => {
    for (const [sessionKey, agent] of sessionAgentsRef.current.entries()) {
      const activeRunToken = activeRunTokensRef.current.get(sessionKey);
      if (activeRunToken) cancelledRunTokensRef.current.add(activeRunToken);
      agent.cancel?.();
    }
  }, []);

  const applyEvent = useCallback((event: AgentEvent, currentNodes: FlowNode[]): FlowNode[] => {
    const lineage = codexLineageFromEvent(event);
    if (Object.keys(lineage).length > 0) {
      setCodexLineage((current) => ({ ...current, ...lineage }));
    }

    if (event.type === "session/created") {
      // Informational event from the sessionless flow. Surface the
      // Codex-issued id to the page via the ``onSessionCreated``
      // callback so the router can switch the URL from
      // ``/analysis/new`` to ``/analysis/{codex_thread_id}``. We also
      // adopt it as the lineage anchor so subsequent events that carry
      // ``codex_thread_id`` resolve to the same session.
      const codexSessionId = event.codexThreadId || event.sessionId;
      if (codexSessionId) {
        setCodexLineage((lineage) => ({
          ...lineage,
          sourceCodexThreadId: codexSessionId,
        }));
        onSessionCreatedRef.current?.(codexSessionId);
      }
      return currentNodes;
    }

    if (event.type === "user") {
      // The backend maps ``turn/started`` to a ``user`` event carrying
      // the same ``turnId`` in the system context. This is the only
      // place we cache ``currentTurnId``: continuations echo the same
      // id and we never accept a turn id from a later event.
      if (event.turnId) setCurrentTurnId(event.turnId);

      const userNode: FlowNode = { id: event.nodeId, role: "user", content: cleanDisplayText(event.content) };
      const pendingIndex = currentNodes.findIndex((node) => node.id === "user-pending");
      const next = pendingIndex >= 0
        ? currentNodes.map((node, index) => (index === pendingIndex ? userNode : node))
        : [...currentNodes, userNode];
      setNodes(next);
      return next;
    }

    if (event.type === "agent") {
      const next: FlowNode[] = currentNodes.filter((node) => node.id !== "agent-pending").map((node) => ({ ...node }) as FlowNode);
      const existing = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      if (existing >= 0) {
        const target = next[existing];
        if (target.role === "agent") {
          const itemId = getAgentEventItemId(event);
          const itemChanged = Boolean(itemId && target.activeItemId && itemId !== target.activeItemId);
          const content = cleanDisplayText(event.content);
          if (isDuplicateAgentContent(target.content, content)) {
            next[existing] = { ...target, mode: event.mode };
          } else {
            const withArchivedMessage = itemChanged ? archiveAgentMessage(target) : target;
            next[existing] = {
              ...withArchivedMessage,
              content,
              mode: event.mode,
              thinking: false,
              activeItemId: itemId ?? withArchivedMessage.activeItemId,
            };
          }
        }
      } else {
          next.push({
          id: event.nodeId,
          role: "agent",
          content: cleanDisplayText(event.content),
          mode: event.mode,
          thinking: false,
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "process") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const pendingIndex = next.findIndex((node) => node.id === "agent-pending");
      const exactIndex = next.findIndex((node) => node.id === event.nodeId && node.role === "agent");
      const reverseIndex = [...next].reverse().findIndex((node) => node.role === "agent");
      const targetIndex = exactIndex >= 0
        ? exactIndex
        : pendingIndex >= 0
          ? pendingIndex
          : reverseIndex >= 0
            ? next.length - 1 - reverseIndex
            : -1;
      const itemId = `${getAgentEventItemId(event) ?? event.nodeId}:${event.summaryIndex}`;
      const now = new Date().toISOString();

      if (targetIndex >= 0) {
        const target = next[targetIndex];
        if (target.role === "agent") {
          const withArchivedMessage = target.id === "agent-pending"
            ? { ...target, content: "", activity: [] }
            : archiveAgentMessage(target);
          const activity = [...(withArchivedMessage.activity ?? [])];
          const activityIndex = activity.findIndex((item) => item.kind === "reasoning" && item.itemId === itemId);
          const currentText = activityIndex >= 0 && activity[activityIndex].kind === "reasoning"
            ? activity[activityIndex].content
            : "";
          const reasoningActivity: Extract<FlowActivity, { kind: "reasoning" }> = {
            kind: "reasoning",
            itemId,
            content: cleanDisplayText(event.mode === "delta" ? currentText + event.text : event.text),
          };
          if (activityIndex >= 0) activity[activityIndex] = reasoningActivity;
          else activity.push(reasoningActivity);
          next[targetIndex] = {
            ...withArchivedMessage,
            id: event.nodeId,
            thinking: false,
            activity,
            processRunning: true,
            processStartedAt: withArchivedMessage.processStartedAt ?? now,
            processCompletedAt: undefined,
          };
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: "",
          mode: "replace",
          thinking: false,
          steps: [],
          activity: [{
            kind: "reasoning",
            itemId,
            content: cleanDisplayText(event.text),
          }],
          processRunning: true,
          processStartedAt: now,
        });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "thinking") {
      const pendingIndex = currentNodes.findIndex((node) => node.id === "agent-pending");
      if (pendingIndex >= 0) {
        const thinkingNode: FlowNode = {
          id: event.nodeId,
          role: "agent",
          content: "",
          mode: "replace",
          thinking: true,
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        };
        const next = currentNodes.map((node, index) => (index === pendingIndex ? thinkingNode : node));
        setNodes(next);
        return next;
      }

      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const exactIndex = next.findIndex((node) => node.id === event.nodeId && node.role === "agent");
      const reverseIndex = [...next].reverse().findIndex((node) => node.role === "agent");
      const targetIndex = exactIndex >= 0 ? exactIndex : reverseIndex >= 0 ? next.length - 1 - reverseIndex : -1;
      if (targetIndex >= 0) {
        const target = next[targetIndex];
        if (target.role === "agent") {
          if (target.content.trim() || (target.activity?.length ?? 0) > 0) {
            return currentNodes;
          }
          next[targetIndex] = {
            ...target,
            id: event.nodeId,
            content: "",
            mode: "replace",
            thinking: true,
            activeItemId: getAgentEventItemId(event) ?? target.activeItemId,
          };
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: "",
          mode: "replace",
          thinking: true,
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "tokens") {
      const pendingIndex = currentNodes.findIndex((node) => node.id === "agent-pending");
      if (pendingIndex >= 0) {
        const streamedNode: FlowNode = {
          id: event.nodeId,
          role: "agent",
          content: cleanDisplayText(event.text),
          mode: "delta",
          thinking: false,
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        };
        const next = currentNodes.map((node, index) => (index === pendingIndex ? streamedNode : node));
        setNodes(next);
        return next;
      }

      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const idx = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      if (idx >= 0) {
        const target = next[idx];
        if (target.role === "agent") {
          const itemId = getAgentEventItemId(event);
          const itemChanged = Boolean(itemId && target.activeItemId && itemId !== target.activeItemId);
          const withArchivedMessage = itemChanged ? archiveAgentMessage(target) : target;
          const currentContent = withArchivedMessage.content;
          next[idx] = {
            ...withArchivedMessage,
            content: currentContent + cleanDisplayText(event.text),
            thinking: false,
            activeItemId: itemId ?? withArchivedMessage.activeItemId,
          };
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: cleanDisplayText(event.text),
          mode: "delta",
          thinking: false,
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "step") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const exactIndex = event.nodeId
        ? next.findIndex((node) => node.id === event.nodeId && node.role === "agent")
        : -1;
      const reverseIndex = [...next].reverse().findIndex((node) => node.role === "agent");
      const targetIndex = exactIndex >= 0 ? exactIndex : reverseIndex >= 0 ? next.length - 1 - reverseIndex : -1;
      if (targetIndex >= 0) {
        const target = next[targetIndex];
        if (target.role === "agent") {
          const withArchivedMessage = target.id === "agent-pending"
            ? { ...target, content: "", activity: [] }
            : archiveAgentMessage(target);
          const steps = [...(target.steps ?? [])];
          const existing = steps.findIndex((s) => (
            event.itemId
              ? s.itemId === event.itemId
              : s.label === event.label && s.detail === event.detail
          ));
          if (existing >= 0) {
            steps[existing] = { label: event.label, state: event.state, detail: event.detail, itemId: event.itemId };
          } else {
            steps.push({ label: event.label, state: event.state, detail: event.detail, itemId: event.itemId });
          }
          const activity = [...(withArchivedMessage.activity ?? [])];
          const activityIndex = activity.findIndex((item) => item.kind === "tool" && (
            event.itemId ? item.itemId === event.itemId : item.label === event.label && item.detail === event.detail
          ));
          const toolActivity: Extract<FlowActivity, { kind: "tool" }> = {
            kind: "tool",
            label: event.label,
            state: event.state,
            detail: event.detail,
            itemId: event.itemId,
          };
          if (activityIndex >= 0) activity[activityIndex] = toolActivity;
          else appendToolActivity(activity, toolActivity);
          next[targetIndex] = {
            ...withArchivedMessage,
            id: event.nodeId ?? target.id,
            thinking: false,
            steps,
            activity,
            processRunning: true,
            processStartedAt: withArchivedMessage.processStartedAt ?? new Date().toISOString(),
            processCompletedAt: undefined,
          };
        }
      } else if (event.nodeId) {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: "",
          mode: "delta",
          steps: [{ label: event.label, state: event.state, detail: event.detail, itemId: event.itemId }],
          activity: [{ kind: "tool", label: event.label, state: event.state, detail: event.detail, itemId: event.itemId }],
          processRunning: true,
          processStartedAt: new Date().toISOString(),
        });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "debug") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const idx = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      const debugItem = { title: event.title, content: event.content };
      if (idx >= 0) {
        const target = next[idx];
        if (target.role === "agent") {
          next[idx] = { ...target, debug: [...(target.debug ?? []), debugItem] };
        }
      } else {
        next.push({ id: event.nodeId, role: "agent", content: "", mode: "delta", steps: [], debug: [debugItem] });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "ask") {
      const next = currentNodes.map((n) => (n.role === "ask" ? { ...n, current: false } : n));
      next.push({ id: event.nodeId, role: "ask", question: event.question, options: event.options, current: true });
      setNodes(next);
      return next;
    }

    if (event.type === "artifact") {
      setArtifacts((folders) => upsertArtifact(folders, event.path, event.kind));
      return currentNodes;
    }

    if (event.type === "report-artifact") {
      setReportArtifact(event.report);
      return currentNodes;
    }

    if (event.type === "done") {
      const next = currentNodes
        .filter((node) => !(
          node.role === "agent"
          && node.thinking
          && !node.content.trim()
          && (node.activity?.length ?? 0) === 0
          && (node.steps?.length ?? 0) === 0
        ))
        .map((node) => {
          if (node.role !== "agent") return node;
          const hasProcess = (node.activity?.length ?? 0) > 0 || (node.steps?.length ?? 0) > 0;
          return {
            ...node,
            thinking: node.thinking ? false : node.thinking,
            ...(hasProcess ? {
              processRunning: false,
              processCompletedAt: node.processCompletedAt ?? new Date().toISOString(),
            } : {}),
          };
        });
      setNodes(next);
      return next;
    }

    if (event.type === "error") {
      const errorNode: FlowNode = { id: `agent-error-${Date.now()}`, role: "agent", content: cleanDisplayText(event.message), mode: "replace" };
      const pendingIndex = currentNodes.findIndex((node) => node.id === "agent-pending");
      const next = pendingIndex >= 0
        ? currentNodes.map((node, index) => (index === pendingIndex ? errorNode : node))
        : [...currentNodes, errorNode];
      setNodes(next);
      return next;
    }

    return currentNodes;
  }, [setArtifacts, setCodexLineage, setCurrentTurnId, setNodes, setReportArtifact]);

  // Intentionally use a hand-written discriminated union instead of
  // ``Omit<AgentInput, "sessionId">`` because ``Omit`` collapses
  // union-specific fields (``question`` / ``content`` / ``optionId``)
  // into a shared shape, breaking the per-branch property check
  // described in P2-1. This union is 1:1 with ``AgentInput`` branches
  // but strips ``sessionId`` from every arm so callers cannot smuggle
  // a different session id than the one the hook was constructed with.
  type HookScopedInput =
    | {
        kind: "start";
        suggestionId?: string;
        question?: string;
        context?: { sourceReportId?: string };
      }
    | { kind: "message"; content: string }
    | { kind: "reply"; optionId: string }
    | { kind: "reset" };

  const consume = useCallback(async (input: HookScopedInput) => {
    let sessionKey = activeSessionKeyRef.current;
    let resolvedSessionId = sessionIdRef.current;
    const fullInput: AgentInput = { ...input, sessionId: resolvedSessionId } as AgentInput;
    const agent = getSessionAgent(sessionKey);
    mutationSessionKeyRef.current = sessionKey;
    const sessionSnapshot = sessionSnapshotsRef.current.get(sessionKey) ?? createFlowSessionSnapshot([]);
    let snapshot: FlowNode[] = withOptimisticTurn(sessionSnapshot.nodes, fullInput);
    if (snapshot !== sessionSnapshot.nodes) setNodes(snapshot);
    // A stop cancels one native Codex Turn, not the whole Session.
    // Keep the user's next message visible immediately, but do not
    // start its Turn until the preceding interrupt request settles.
    // This prevents the old stream's terminal cleanup from racing the
    // new Turn and clearing its running state.
    const stoppingPromise = stoppingPromisesRef.current.get(sessionKey);
    if (stoppingPromise) await stoppingPromise;
    const runToken = Symbol(sessionKey);
    activeRunTokensRef.current.set(sessionKey, runToken);
    mutationSessionKeyRef.current = sessionKey;
    setRunning(true);
    let sawError = false;
    try {
      for await (const event of agent.send(fullInput)) {
        if (cancelledRunTokensRef.current.has(runToken)) break;
        if (event.type === "error") sawError = true;
        if (event.type === "session/created") {
          const provisionedSessionId = event.codexThreadId || event.sessionId;
          if (provisionedSessionId) {
            sessionKey = rekeySession(sessionKey, provisionedSessionId);
            resolvedSessionId = provisionedSessionId;
          }
        }
        mutationSessionKeyRef.current = sessionKey;
        snapshot = applyEvent(event, snapshot);
      }
    } finally {
      mutationSessionKeyRef.current = sessionKey;
      const wasCancelled = cancelledRunTokensRef.current.has(runToken);
      if (!wasCancelled && resolvedSessionId && onTurnSettledRef.current) {
        try {
          const reconciledNodes = await onTurnSettledRef.current(resolvedSessionId);
          mutationSessionKeyRef.current = sessionKey;
          if (reconciledNodes && !(sawError && reconciledNodes.length === 0)) {
            snapshot = reconciledNodes;
            setNodes(reconciledNodes);
          }
        } catch {
          // The live stream remains the fallback when the terminal
          // database reconciliation request is temporarily unavailable.
        }
      }
      mutationSessionKeyRef.current = sessionKey;
      if (activeRunTokensRef.current.get(sessionKey) === runToken) {
        activeRunTokensRef.current.delete(sessionKey);
        setRunning(false);
      }
      cancelledRunTokensRef.current.delete(runToken);
      mutationSessionKeyRef.current = null;
    }
  }, [applyEvent, getSessionAgent, rekeySession, setNodes, setRunning]);

  const start = useCallback(
    // ``sessionId`` is not exposed: it is always the hook's own id
    // (null on the first turn of a brand-new session). Closing over
    // the hook instance id prevents the "useFlow(A) + send(msg, B)"
    // cross-session leakage bug described in P2-1.
    (question?: string, context?: { sourceReportId?: string }) => consume({ kind: "start", question, context }),
    [consume],
  );
  const send = useCallback(
    (content: string) => consume({ kind: "message", content }),
    [consume],
  );
  const reply = useCallback(
    (optionId: string) => consume({ kind: "reply", optionId }),
    [consume],
  );
  const stop = useCallback(() => {
    const sessionKey = activeSessionKeyRef.current;
    const snapshot = sessionSnapshotsRef.current.get(sessionKey);
    if (!snapshot?.running) return;
    // Two actions, run together: abort the SSE stream locally so
    // the UI stops consuming events, AND ask the backend to
    // interrupt the live Codex turn so the CLI actually stops
    // running tools. The backend endpoint
    // ``POST /sessions/{id}/turns/{turn_id}/cancel`` is the only
    // place that calls ``CodexSdkAnalysisRuntime.interrupt_turn``;
    // before the user spec was applied, the cancel button only
    // aborted the HTTP fetch, so the Codex turn kept running
    // until its own timeout.
    //
    // Cancellation is scoped to the selected Session key. Other
    // native Codex Turn streams in the workspace continue consuming
    // events while the user views or stops a different Session.
    const activeRunToken = activeRunTokensRef.current.get(sessionKey);
    if (activeRunToken) cancelledRunTokensRef.current.add(activeRunToken);
    mutationSessionKeyRef.current = sessionKey;
    const agent = getSessionAgent(sessionKey);
    agent.cancel?.();
    if (sessionIdRef.current && snapshot.currentTurnId && typeof agent.cancelTurn === "function") {
      const interruptPromise = Promise.resolve(
        agent.cancelTurn(sessionIdRef.current, snapshot.currentTurnId),
      ).catch(() => undefined);
      stoppingPromisesRef.current.set(sessionKey, interruptPromise);
      void interruptPromise.finally(() => {
        for (const [key, pending] of stoppingPromisesRef.current.entries()) {
          if (pending === interruptPromise) stoppingPromisesRef.current.delete(key);
        }
      });
    }
    setRunning(false);
    setCurrentTurnId(null);
    setNodes((current) => current.flatMap<FlowNode>((node) => {
      if (node.id === "agent-pending") return [];
      if (node.role !== "agent") return [node];
      const hasVisibleProcess = Boolean(
        node.content.trim()
        || (node.steps?.length ?? 0) > 0
        || (node.activity?.length ?? 0) > 0
        || (node.debug?.length ?? 0) > 0
      );
      if (!hasVisibleProcess) return [];
      return [{
        ...node,
        thinking: false,
        processRunning: false,
        processCompletedAt: node.processStartedAt
          ? (node.processCompletedAt ?? new Date().toISOString())
          : node.processCompletedAt,
      }];
    }));
    mutationSessionKeyRef.current = null;
  }, [getSessionAgent, setCurrentTurnId, setNodes, setRunning]);

  return {
    currentTurnId,
    nodes,
    artifacts,
    reportArtifact,
    codexLineage,
    running,
    start,
    send,
    reply,
    stop,
  };
}

function flowSessionKey(sessionId: string | null): string {
  return sessionId || NEW_FLOW_SESSION_KEY;
}

function createFlowSessionSnapshot(nodes: FlowNode[]): FlowSessionSnapshot {
  return {
    currentTurnId: null,
    nodes: [...nodes],
    artifacts: [],
    reportArtifact: null,
    codexLineage: {},
    running: false,
  };
}

function resolveStateAction<T>(update: SetStateAction<T>, current: T): T {
  return typeof update === "function"
    ? (update as (previous: T) => T)(current)
    : update;
}

function isDuplicateAgentContent(currentContent: string, nextContent: string): boolean {
  return Boolean(currentContent && nextContent && currentContent.includes(nextContent));
}

function flowNodeSignature(nodes: FlowNode[]): string {
  return nodes
    .map((node) => {
      if (node.role === "user") return `user:${node.id}:${node.content}`;
      if (node.role === "agent") return `agent:${node.id}:${node.content}:${node.activity?.length ?? 0}:${node.thinking ? "thinking" : ""}`;
      return `ask:${node.id}:${node.question}`;
    })
    .join("|");
}

function cleanDisplayText(value: string): string {
  // Strict UTF-8 contract: no runtime mojibake stripping. If � appears
  // the source data is corrupted and should be fixed at rest, not patched
  // on render. Previously this stripped \uFFFD, which masked encoding
  // bugs at the database / persistence layer.
  return value;
}

function withOptimisticTurn(nodes: FlowNode[], input: AgentInput): FlowNode[] {
  const content = input.kind === "start" ? input.question : input.kind === "message" ? input.content : "";
  if (!content || nodes.some((node) => node.id === "user-pending" || node.id === "agent-pending")) return nodes;
  return [
    ...nodes,
    { id: "user-pending", role: "user", content: cleanDisplayText(content) },
    { id: "agent-pending", role: "agent", content: "", mode: "replace", thinking: true, steps: [] },
  ];
}

function getAgentEventItemId(event: AgentEvent): string | undefined {
  return event.codexItemId ?? event.itemId;
}

function archiveAgentMessage(node: Extract<FlowNode, { role: "agent" }>): Extract<FlowNode, { role: "agent" }> {
  if (!node.content.trim()) return node;
  const activity = [...(node.activity ?? [])];
  const existing = activity.findIndex((item) => item.kind === "message" && node.activeItemId && item.itemId === node.activeItemId);
  const message: FlowActivity = { kind: "message", content: node.content, itemId: node.activeItemId };
  if (existing >= 0) activity[existing] = message;
  else activity.push(message);
  return { ...node, content: "", activity };
}

function appendToolActivity(activity: FlowActivity[], toolActivity: Extract<FlowActivity, { kind: "tool" }>): void {
  const previous = activity.at(-1);
  if (
    previous?.kind === "tool"
    && previous.label === toolActivity.label
    && previous.state === toolActivity.state
  ) {
    const details = [
      ...(previous.details ?? (previous.detail ? [previous.detail] : [])),
      ...(toolActivity.detail ? [toolActivity.detail] : []),
    ];
    activity[activity.length - 1] = {
      ...previous,
      count: (previous.count ?? 1) + 1,
      details,
    };
    return;
  }
  activity.push(toolActivity);
}

function codexLineageFromEvent(event: AgentEvent): FlowCodexLineage {
  const lineage: FlowCodexLineage = {};
  if (event.codexThreadId) lineage.sourceCodexThreadId = event.codexThreadId;
  if (event.codexTurnId) lineage.sourceCodexTurnId = event.codexTurnId;
  if (event.codexItemId) lineage.sourceCodexItemId = event.codexItemId;
  return lineage;
}

function upsertArtifact(folders: ArtifactFolder[], path: string, kind: ArtifactKind): ArtifactFolder[] {
  const [folderName = "assets", fileName = path] = path.split("/");
  const fileId = path.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "");
  const next = folders.map((folder) => ({
    ...folder,
    children: folder.children.map((file) => ({ ...file })),
  }));
  let folder = next.find((item) => item.id === folderName);
  if (!folder) {
    folder = { id: folderName, name: folderName, children: [] };
    next.push(folder);
  }
  const existing = folder.children.findIndex((file) => file.id === fileId);
  const file = { id: fileId, name: fileName, kind };
  if (existing >= 0) {
    folder.children[existing] = file;
  } else {
    folder.children.push(file);
  }
  return next;
}
