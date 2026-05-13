# TrustLayer Memory Vault

This folder is designed to be opened as an Obsidian vault.
It acts as the human-understanding layer.

## Structure
- `01_Architecture/`: System design and ADRs.
- `02_Agent_Skills/`: Documentation of available agent tools.
- `03_Memory_Traces/`: One markdown note per `(agent_id, session_id)`,
  written by Hermes from `AgentTraceEvent` JSONL.
- `04_Development/`: Project status and task tracking.
- `05_Reflections/`: Dated reflection notes synthesised by Hermes from the
  cached session events.
- `06_Code_Graph/`: One note per code entity (file, class, function)
  mirrored from a GitNexus JSON graph by `hermes.cli import-code-graph`
  — runtime memory and static structure share one navigable vault.
