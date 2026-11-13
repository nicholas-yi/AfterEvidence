# Conversation, sleep, and resumable work

## A saved conversation is not an always-running process

VS Code stores chat/session history, and this project stores application data
and research journals separately. Sleep does not turn a local process into a
remote job. Local inference, scripts, and network connections can pause or
disconnect when the computer sleeps. A detached process is not immune to sleep.

Use VS Code's session history to reopen the same conversation. Keep the project
and its local run files rather than relying on one long chat as the only record.
Do not upload an entire conversation, credentials, or account snapshots to a
public repository.

## The exact automatic behavior is not guaranteed here

Upstream Copilot has model-request power blocking, but coverage of custom
providers and whole agent/tool lifecycles has known limits:

- [Original request and shipped model-request behavior](https://github.com/microsoft/vscode/issues/276546).
- [Custom-provider and long-tool-call coverage](https://github.com/microsoft/vscode/issues/332518).
- [Session-wide implementation proposal](https://github.com/microsoft/vscode/pull/332534).

Seeing a chat's current `inProgress` state is not the same as having a supported,
persistent activity subscription for an external Windows script. This project
does not pretend that an open VS Code process proves a chat is running.

## Optional temporary Windows hold

The bundled script prevents **automatic idle sleep** for a bounded period,
without permanently changing a power plan:

```powershell
.\scripts\keep-awake.ps1 -Minutes 120
```

Run it in a terminal you leave open. A native Windows execution-state request
is held only while that process is alive. The display is allowed to turn off.
By default the request releases within a few seconds if AC power disconnects.

From another PowerShell terminal:

```powershell
.\scripts\keep-awake.ps1 -Status
.\scripts\keep-awake.ps1 -Stop
```

`-ContinueOnBattery` is an explicit opt-in, not the default. The script does not
override manual Sleep, shutdown, critical-battery behavior, or a lid-close action.
Do not use it to keep a closed laptop running in an enclosed bag.

**This is a manual hold with an expiry, not automatic chat detection.**
It protects other ongoing local work too; it cannot tell when every chat finishes.
Normal sleep behavior returns when the hold expires, stops, or its process ends.

## Resume this project without losing the research boundary

1. Reopen this repository and the prior VS Code chat/session.
2. Read [the current research results](../research/RESULTS.md), not only the UI README.
3. Keep `data/`, `results/`, and `research/runs/` locally. They are intentionally
   excluded from Git; back them up privately if needed.
4. Inspect the last run's status and per-request journal. A `started` entry with
   no completed billing record is unknown usage, not a free or successful request.
5. Do not rerun an already consumed model call merely because the screen went away.
   The current drivers reject existing output paths; choose a fresh, explicitly
   labeled attempt only after accounting for the earlier one.
6. Preserve pilot/main-study separation. No main four-condition memory result
   or preregistration tag exists yet.

Current handoff: one repaired Copilot development episode completed with native
ENV/task-basis rewards of 1.0, reproduced by fresh zero-inference replay. Earlier
format failures remain counted; another selected task failed strict reference
preflight before inference, traced offline to a copied placeholder ID. An
offline audit found that the original cohort was one customer and proposed an
independent 11-task development cohort that passes native zero-inference
preflight but is not yet approved. Simulator
calibration, a held-out partition, and the main-study gates remain unfinished.

For another machine, use [the devbox handoff and copy-paste prompt](DEVBOX-HANDOFF.md).
It covers pinned setup, offline validation, private evidence that Git does not
transfer, and the exact next research gate.

For truly unattended work while a laptop sleeps, use an approved always-on remote
machine and durable run logging. That is a separate deployment, security, and cost
decision; this project does not start a cloud machine automatically.
