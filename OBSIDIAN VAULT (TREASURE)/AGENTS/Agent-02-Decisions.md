> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **agy Activation Command (Gemini 3.6 Flash - Primary Vision + STT)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && hermes`
> - **SKILL**: `/ClipIt-AI-Ingestion-Specialist`

# ⚖️ AGENT 02: DECISIONS LOG

- 🤖 **[[Agent-02-AI-Ingestion-Specialist| Back to Agent 02 Hub]]**

## ADR-002: Groq Whisper API for STT
- **Status**: Approved
- **Decision**: Use Groq Whisper API (`whisper-large-v3-turbo`) @ $0.04/hour for fast, cost-effective word timestamp extraction with OpenAI Whisper API as secondary fallback.



### 👁️ Multimodal Vision Capability (SECONDARY)
- **Model**: Gemini 1.5 Flash Vision / GPT-4o Vision
- **Vision Tasks**:
  1. **Visual Hook Analysis**: Analyze sampled keyframe images (1 frame every 3s) alongside audio transcripts to detect visual hooks (slide reveals, facial expressions, chart highlights).
  2. **Multi-Modal Virality Scoring**: Combine audio transcript score (0-10) with visual motion density score (0-10).



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: GPT-4o / Opencode Zen (-free)