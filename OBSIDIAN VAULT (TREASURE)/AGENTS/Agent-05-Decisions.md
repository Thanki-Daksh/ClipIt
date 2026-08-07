> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && agy`
> - **SKILL**: `/ClipIt-Mobile-Daemon-OS-Runtime`

# ⚖️ AGENT 05: DECISIONS LOG

- 📱 **[[Agent-05-Mobile-Daemon-OS-Runtime| Back to Agent 05 Hub]]**

## ADR-005: Termux CPU Wake-Lock Integration
- **Status**: Approved
- **Decision**: Use `termux-wake-lock` during processing tasks to prevent Android OS deep sleep CPU throttling, releasing lock immediately when idle.



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Opencode Zen (-free) / Gemini 3.6 Flash
- **Effort Level**: Medium Effort
- **Fallback Model**: Gemini 3.6 Flash