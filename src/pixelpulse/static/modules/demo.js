/**
 * Demo Mode — "Mission Control" pace
 *
 * Simulates a realistic pipeline run at a READABLE pace.
 * Shows agent thinking, inter-agent communication, pipeline progression,
 * and orchestrator coordination.
 *
 * Dynamically generates the demo script from the loaded config
 * (TEAMS, PIPELINE_STAGES, STAGE_TO_TEAM) so it works with any
 * agent configuration — works with any agent setup.
 *
 * Tick interval: 3500ms — one action per tick, not a flood.
 */

import {
  TEAMS,
  PIPELINE_STAGES,
  STAGE_TO_TEAM,
  updateAgent,
  updateOrchestrator,
  updatePipeline,
  updateCost,
  addEvent,
} from "./state.js";
import { show as showToast } from "./toasts.js";

let interval = null;
let tick = 0;
let scriptIdx = 0;
let tickInterval = 3500;
let generatedScript = null;

export function isRunning() {
  return interval !== null;
}

// --- Dynamic Script Generation ---
// Builds a demo script from the current config so it works
// with any team/agent/pipeline setup.

function _capitalize(s) {
  return s.replace(/(^|[-_ ])(\w)/g, (_, sep, ch) => (sep === "-" || sep === "_" ? " " : sep) + ch.toUpperCase());
}

function _agentLabel(id) {
  return _capitalize(id);
}

function generateScript() {
  const teamEntries = Object.entries(TEAMS);
  const script = [];

  // If no teams at all, return a minimal idle script
  if (teamEntries.length === 0) {
    script.push({
      type: "orchestrator", status: "idle", stage: "",
      message: "No configuration loaded — connect to a PixelPulse server to see agents"
    });
    return script;
  }

  // If no pipeline stages defined, generate a demo by cycling through all teams
  if (PIPELINE_STAGES.length === 0) {
    script.push({ type: "orchestrator", status: "active", stage: "", message: "Agents on standby — awaiting next pipeline run..." });
    script.push({ type: "orchestrator", status: "active", stage: "", message: "New trigger detected — preparing pipeline run" });
    for (let ti = 0; ti < teamEntries.length; ti++) {
      const [teamId, team] = teamEntries[ti];
      const teamLabel = team.label || _capitalize(teamId);
      const agents = team.agents || [];
      script.push({ type: "orchestrator", status: "active", stage: teamId, message: `Advancing to ${teamLabel} — ${team.role || "processing"}` });
      script.push({ type: "pipeline", stage: teamId });
      for (let ai = 0; ai < agents.length; ai++) {
        const agentName = agents[ai];
        const label = _agentLabel(agentName);
        script.push({ type: "agent_active", agent: agentName, thinking: `${label} processing tasks...` });
        script.push({ type: "agent_done", agent: agentName, thinking: `${label} completed — results ready` });
        const nextAgent = ai < agents.length - 1 ? agents[ai + 1]
          : ti < teamEntries.length - 1 ? (teamEntries[ti + 1][1].agents || [])[0] : null;
        if (nextAgent) {
          script.push({ type: "flow", from: agentName, to: nextAgent, content: `Results from ${label}`, tag: _inferTag(teamId, ai) });
        }
      }
      if (agents.length > 0) {
        script.push({ type: "cost", agent: agents[agents.length - 1], amount: 0.003 + Math.random() * 0.02 });
      }
    }
    script.push({ type: "orchestrator", status: "idle", stage: "", message: "Pipeline run complete — all stages finished" });
    return script;
  }

  // ======= IDLE WARM-UP =======
  script.push({
    type: "orchestrator", status: "idle", stage: "",
    message: "Agents on standby — awaiting next pipeline run..."
  });
  script.push({
    type: "orchestrator", status: "idle", stage: "",
    message: "Monitoring for trigger conditions..."
  });
  script.push({
    type: "orchestrator", status: "idle", stage: "",
    message: "New trigger detected — preparing pipeline run"
  });

  // ======= Walk through each pipeline stage =======
  for (let si = 0; si < PIPELINE_STAGES.length; si++) {
    const stage = PIPELINE_STAGES[si];
    const teamId = STAGE_TO_TEAM[stage];
    const team = teamId ? TEAMS[teamId] : null;
    const agents = team ? team.agents : [];
    const stageLabel = stage.replace(/_/g, " ");

    // Check if this is a "waiting" stage (e.g., human_approval)
    const isWaiting = !teamId;

    // Orchestrator announces stage
    script.push({
      type: "orchestrator",
      status: isWaiting ? "waiting" : "active",
      stage,
      message: isWaiting
        ? `Waiting for approval — ${stageLabel}`
        : `Advancing to ${stageLabel}${team ? ` — ${team.role}` : ""}`
    });
    script.push({ type: "pipeline", stage });

    if (isWaiting) {
      // Simulate approval after a pause
      script.push({
        type: "orchestrator", status: "active", stage,
        message: "Approval received — proceeding"
      });
      continue;
    }

    // Each agent in the team does work sequentially
    for (let ai = 0; ai < agents.length; ai++) {
      const agentName = agents[ai];
      const label = _agentLabel(agentName);

      // Agent starts working
      script.push({
        type: "agent_active", agent: agentName,
        thinking: `${label} processing ${stageLabel} tasks...`
      });

      // Agent finishes
      script.push({
        type: "agent_done", agent: agentName,
        thinking: `${label} completed — results ready`
      });

      // Flow to next agent in same team, or to first agent of next team
      const nextAgent = ai < agents.length - 1
        ? agents[ai + 1]
        : _findNextTeamFirstAgent(si);

      if (nextAgent) {
        script.push({
          type: "flow",
          from: agentName,
          to: nextAgent,
          content: `Passing ${stageLabel} results to ${_agentLabel(nextAgent)}`,
          tag: _inferTag(stage, ai)
        });
      }
    }

    // Add a cost event for the last agent in each team
    if (agents.length > 0) {
      script.push({
        type: "cost",
        agent: agents[agents.length - 1],
        amount: 0.003 + Math.random() * 0.02
      });
    }
  }

  // ======= COMPLETE =======
  script.push({
    type: "orchestrator", status: "idle", stage: "",
    message: "Pipeline run complete — all stages finished"
  });

  return script;
}

/**
 * Find the first agent of the next team-based stage after stageIndex.
 */
function _findNextTeamFirstAgent(currentStageIdx) {
  for (let i = currentStageIdx + 1; i < PIPELINE_STAGES.length; i++) {
    const nextTeamId = STAGE_TO_TEAM[PIPELINE_STAGES[i]];
    if (nextTeamId && TEAMS[nextTeamId] && TEAMS[nextTeamId].agents.length > 0) {
      return TEAMS[nextTeamId].agents[0];
    }
  }
  return null;
}

/**
 * Infer a data tag from stage name and agent position for visual variety.
 */
function _inferTag(stage, agentIdx) {
  const tags = ["data", "signals", "brief", "prompts", "artifacts", "listings", "feedback", "analysis", "memory"];
  // Use a mix of stage name and position to pick varied tags
  const hash = stage.length + agentIdx;
  return tags[hash % tags.length];
}

// Running cost accumulator
let runningCost = 0;

function demoTick() {
  if (!generatedScript || generatedScript.length === 0) return;

  const allAgents = Object.values(TEAMS).flatMap((t) => t.agents);
  tick++;
  if (scriptIdx >= generatedScript.length) {
    scriptIdx = 0;
    runningCost = 0;
    for (const agent of allAgents) {
      updateAgent(agent, { status: "idle", task: "" });
    }
  }
  const step = generatedScript[scriptIdx++];
  executeStep(step);
}

function startInterval() {
  if (interval) clearInterval(interval);
  interval = setInterval(demoTick, tickInterval);
}

export function start() {
  if (interval) return;
  tick = 0;
  scriptIdx = 0;
  runningCost = 0;

  // Generate script from current config
  generatedScript = generateScript();

  // Reset all agents to idle
  const allAgents = Object.values(TEAMS).flatMap((t) => t.agents);
  for (const agent of allAgents) {
    updateAgent(agent, { status: "idle", task: "" });
  }
  updateOrchestrator({ status: "idle", currentStage: "", message: "" });

  startInterval();
}

/** Change demo playback speed. Restarts interval if running. */
export function setSpeed(ms) {
  tickInterval = ms;
  if (interval) {
    startInterval();
  }
}

function executeStep(step) {
  switch (step.type) {
    case "orchestrator":
      updateOrchestrator({
        status: step.status,
        currentStage: step.stage,
        message: step.message,
      });
      if (step.status === "waiting") {
        showToast("Approval gate — waiting for human review", "warning");
      }
      addEvent({
        type: "pipeline_progress",
        timestamp: new Date().toISOString(),
        payload: {
          run_id: "demo",
          stage: step.stage,
          status: step.status,
          message: step.message,
        },
      });
      break;

    case "pipeline": {
      updatePipeline({ stage: step.stage });
      if (step.stage) {
        const stageName = step.stage.replace(/_/g, " ");
        showToast("Stage completed: " + stageName, "success");
      }
      // Set active team's agents to "waiting" state
      const activeTeam = STAGE_TO_TEAM[step.stage];
      if (activeTeam && TEAMS[activeTeam]) {
        for (const agent of TEAMS[activeTeam].agents) {
          updateAgent(agent, { status: "waiting", task: "Standing by..." });
        }
      }
      break;
    }

    case "agent_active":
      updateAgent(step.agent, {
        status: "active",
        task: step.thinking.slice(0, 40) + "...",
      });
      addEvent({
        type: "agent_status",
        timestamp: new Date().toISOString(),
        payload: {
          agent_id: step.agent,
          status: "active",
          current_task: step.thinking.slice(0, 40) + "...",
          thinking: step.thinking,
        },
      });
      break;

    case "agent_done":
      updateAgent(step.agent, { status: "idle", task: "" });
      addEvent({
        type: "agent_status",
        timestamp: new Date().toISOString(),
        payload: {
          agent_id: step.agent,
          status: "idle",
          current_task: "",
          thinking: step.thinking,
          decision: "Task completed successfully",
        },
      });
      break;

    case "flow":
      addEvent({
        type: "message_flow",
        timestamp: new Date().toISOString(),
        payload: {
          from: step.from,
          to: step.to,
          content: step.content,
          tag: step.tag || "data",
        },
      });
      break;

    case "cost":
      runningCost += step.amount;
      updateCost(step.agent, step.amount, runningCost);
      addEvent({
        type: "cost_update",
        timestamp: new Date().toISOString(),
        payload: {
          agent_id: step.agent,
          cost: step.amount,
          total: runningCost,
        },
      });
      break;
  }
}

export function stop() {
  if (interval) {
    clearInterval(interval);
    interval = null;
  }
}
