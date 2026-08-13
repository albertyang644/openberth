# OpenBerth UI Revision – TV Model (Codex Update)

Related notes: [[OpenBerth Map]], [[User Model]], [[Architecture]], [[Desktop Launch]].

## Philosophy Shift

OpenBerth is NOT a terminal manager.

OpenBerth is a visual organization layer for tmux.

Users should think in terms of:

* TVs
* Groups
* Workflows

Users should NOT need to understand:

* tmux sessions
* tmux windows
* tmux panes
* tmux targets

These remain implementation details.

---

# Core UI Object: TV

The primary object in the UI is a TV.

A TV represents a tmux target.

Example:

┌────────────────────┐
│ Trader             │
│                    │
│  Activity Map      │
│                    │
└────────────────────┘

The user interacts with TVs, not tmux objects.

---

# Left Panel Becomes TV Harbor

The left panel contains all TVs.

The right panel remains the active terminal area.

Think:

* Browser tabs, but vertical
* Photoshop layers, but visual
* Lightroom collections, but for tmux

---

# Selection Model (Photoshop Inspired)

This is the keystone interaction.

Users can:

* Single Click → Select
* Ctrl Click → Toggle Selection
* Shift Click → Range Select

Selected TVs become highlighted.

Example:

[X] Trader
[X] Scanner
[ ] News

The entire product should be organized around selection.

---

# Group Creation (Chain-Link)

Toolbar Icon:

🔗

Workflow:

1. User selects one or more TVs.
2. User clicks Chain-Link icon.
3. OpenBerth creates a Berth containing those TVs.
4. User may optionally name the berth.

Example:

Selected:

Trader
Scanner
News

Click:

🔗

Result:

Forex
├ Trader
├ Scanner
└ News

No tmux changes occur.

Only metadata changes.

---

# Color Assignment

A color palette exists at the bottom of the sidebar.

Workflow:

1. Select a berth.
2. Click color.

Result:

Forex = Green
Ollama = Orange
CRM = Blue

Colors should be highly visible and used as visual anchors.

Goal:

User identifies groups by color before reading text.

---

# TV Activity Map

The TV should NOT contain a screenshot.

The TV should NOT embed a terminal.

The TV should display a compressed visual representation of activity.

Inspired by:

* Kate minimap
* VS Code minimap
* Sublime minimap

Purpose:

Show liveness.

Allow the user to determine:

* Active
* Idle
* Dead
* Stuck

without opening the terminal.

The activity map is a first-class UI feature.

---

# TV Controls

Each TV contains actions.

Actions should be visible but lightweight.

Required actions:

↗ Pop Out
X Close
☠ Kill

---

## Pop Out (↗)

Behavior:

Open a new terminal window attached to the selected tmux target.

OpenBerth remains open.

tmux remains unchanged.

This action should require no confirmation.

---

## Close (X)

Behavior:

Remove the TV from the current OpenBerth workspace view.

IMPORTANT:

This does NOT kill tmux.

This does NOT kill the process.

This is equivalent to closing a browser tab.

The tmux target continues running.

User should be able to restore recently closed TVs.

Implement:

Ctrl+Shift+T

similar to browser tab restoration.

No confirmation required.

---

## Kill (☠)

Behavior:

Kill the underlying tmux target.

This is destructive.

Requirements:

* Right Click → Kill
  OR
* Click Skull → Confirmation Dialog

Never single-click destructive.

Goal:

Prevent fat-finger mistakes.

The product should assume users are comfortable closing TVs but cautious about killing tmux.

---

# Context Menu

Right-click TV:

* Open
* Pop Out
* Rename
* Move To Berth
* Close TV
* Kill Target

Right-click Berth:

* Rename
* Change Color
* Collapse
* Expand

---

# UI Principle

The UI should require effectively zero documentation.

The user should infer behavior naturally.

Use established software conventions whenever possible.

Examples:

* Photoshop selection model
* Browser tab closing
* Ctrl+Shift+T restore
* Google pop-out icon
* Context menu conventions

Do not invent new interaction models when established conventions already exist.

---

# Architectural Rules

OpenBerth never owns terminals.

OpenBerth never owns shell processes.

OpenBerth stores metadata about tmux targets.

tmux remains the source of truth.

OpenBerth may launch, attach, detach, or kill tmux targets only through explicit user actions.

---

# v0.1 Goal

The user should be able to:

1. Discover tmux targets.
2. See activity at a glance.
3. Select TVs.
4. Chain-link TVs into groups.
5. Color-code groups.
6. Pop out terminals.
7. Close and restore TVs.
8. Kill tmux targets safely.

without reading instructions.
