# 📋 CEO TASK ASSIGNMENT: AGENT 06 (QA & SECURITY AUDITOR)

> [!IMPORTANT] **CEO Directive for Agent 06**
> **Target Files**: 	ests/conftest.py, 	ests/test_queue.py, 	ests/test_clipper.py, 	ests/test_pipeline.py
> **Primary Model**: deepseek-v4-flash-free (200k Context - FREE!) / Gemini 3.6 Flash
> **Secondary Fallback**: Claude 3.5 Sonnet

---

## 🎯 Central Hub Connections
- 💎 **[[Index| Master Vault Index]]**
- 👑 **[[CEO-Operational-Guide| CEO Orchestrator Guide]]**
- 🧪 **[[Agent-06-QA-Security-Auditor| Agent 06 Hub]]**

---

## 📋 Assigned Tasks Matrix

| Task ID | Task Title | Priority | Status | Target Deliverable |
| :---: | :--- | :---: | :---: | :--- |
| **TSK-A06-01** | Build Shared pytest Fixtures | HIGH | [ ] PENDING | Create isolated temporary SQLite DB & transcript mocks |
| **TSK-A06-02** | Build State Machine Test Suite | CRITICAL | [ ] PENDING | Test queue state transitions & simulated crash auto-recovery |
| **TSK-A06-03** | Build fprobe Video Render Test | HIGH | [ ] PENDING | Programmatically verify output .mp4 is 1080x1920 9:16 aspect ratio |
| **TSK-A06-04** | Audit Codebase Secret Sanitization | CRITICAL | [ ] PENDING | Scan commits to ensure zero API keys or DB files are committed |
