> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && hermes`
> - **SKILL**: `/ClipIt-Media-Graphics-Engineer`

# 🤝 AGENT 03: CHECK-IN & PEER REVIEW PROTOCOL

- 🎬 **[[Agent-03-Media-Graphics-Engineer| Back to Agent 03 Hub]]**

## 🔍 Peer Audit Responsibilities
- **Auditing Agent 02**: Verify input timestamps from `analyzer.py` are non-overlapping and valid.
- **Auditing Agent 04**: Verify web UI video player streams `.mp4` files properly from static path.

## 📝 Peer Audit Log History
| Timestamp | Peer Agent Audited | Verification Status | Notes |
| :--- | :--- | :---: | :--- |
| **2026-08-07** | Agent 02 | `🟢 PASSED` | Validated candidate clip timestamps |
| **2026-08-07** | Agent 04 | `🟢 PASSED` | Validated media stream route compatibility |

## 📝 Agent 03 Verification Log (2026-08-07)
| Artifact | Result | Evidence |
| :--- | :---: | :--- |
| `modules/clipper.py` center crop | 🟢 1080x1920 | ffprobe `stream=width,height` |
| `modules/clipper.py` blur crop | 🟢 1080x1920 | ffprobe `stream=width,height` |
| `modules/captioner.py` ASS gen | 🟢 `&H0000FFFF&` tags | ASS header + inline `\c&H0000FFFF&` |
| `modules/captioner.py` burn-in | 🟢 visible | bottom-frame MD5 differs captioned vs raw |
| `modules/metadata.py` package | 🟢 metadata.json | written beside clip in `storage/accounts/acc_01/outputs/` |



### 👁️ Multimodal Vision Capability (PRIMARY)
- **Model**: Gemini 1.5 Flash Vision / OpenCV Frame Analyzer
- **Vision Tasks**:
  1. **Smart Speaker Face Tracking**: Inspect keyframes to detect speaker face coordinates for dynamic 9:16 center cropping.
  2. **Subtitle Placement Audit**: Verify ASS animated captions do not obscure speaker faces or lower-third graphics.
  3. **Render Artifact Detection**: Visually audit exported video keyframes for black bars, distortion, or color corruption.



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: Claude 3.5 Sonnet