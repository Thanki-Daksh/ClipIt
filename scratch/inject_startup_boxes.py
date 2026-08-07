import os

startup_boxes = {
    'Agent-01': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/core`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` (agy subscription)
> - **Effort Level**: `High Effort`
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (OpenCode Zen - 200k Context)''',

    'Agent-02': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` (Multimodal Vision + STT)
> - **Effort Level**: `High Effort`
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (200k Context for long transcripts)''',

    'Agent-03': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash`
> - **Effort Level**: `High Effort`
> - **Fallback Model**: `Claude 3.5 Sonnet`''',

    'Agent-04': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/ui`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/ui" && clear && agy`
> - **Primary Model**: `Claude 3.5 Sonnet`
> - **Effort Level**: `High Effort`
> - **Fallback Model**: `Gemini 3.6 Flash` (High Effort)''',

    'Agent-05': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && agy`
> - **Primary Model**: `DeepSeek v4 Flash-Free` (OpenCode Zen - 200k Context - FREE!)
> - **Effort Level**: `Medium Effort`
> - **Fallback Model**: `Gemini 3.6 Flash`''',

    'Agent-06': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/tests`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/tests" && clear && agy`
> - **Primary Model**: `DeepSeek v4 Flash-Free` (200k Context) / `Gemini 3.6 Flash`
> - **Effort Level**: `High Effort`
> - **Fallback Model**: `Claude 3.5 Sonnet`''',

    'ceo': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt" && clear && agy`
> - **Primary Model**: `Claude 3.5 Sonnet` / `Claude Opus`
> - **Effort Level**: `High Effort`
> - **Fallback Model**: `Gemini 3.6 Flash` (High Effort)'''
}

def process_file(filepath):
    filename = os.path.basename(filepath)
    for key, box_text in startup_boxes.items():
        if key.lower() in filename.lower():
            with open(filepath, 'r', encoding='utf-8') as fh:
                content = fh.read()
            if 'SKILL STARTUP ACTIVATION & MODEL CONFIGURATION' not in content:
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        new_content = '---' + parts[1] + '---\n\n' + box_text + '\n\n' + parts[2]
                    else:
                        new_content = box_text + '\n\n' + content
                else:
                    new_content = box_text + '\n\n' + content
                
                with open(filepath, 'w', encoding='utf-8') as fh:
                    fh.write(new_content)
                print(f'Injected startup box into: {filepath}')

def process_dir(d):
    for root, dirs, files in os.walk(d):
        for f in files:
            if f.endswith('.md'):
                process_file(os.path.join(root, f))

if __name__ == '__main__':
    process_dir(r'C:\Users\Admin\OneDrive\Desktop\ClipIt\agents')
    process_dir(r'C:\Users\Admin\OneDrive\Desktop\ClipIt\OBSIDIAN VAULT (TREASURE)\AGENTS')
    process_dir(r'C:\Users\Admin\.gemini\config\skills')
    process_dir(r'C:\Users\Admin\.agents\skills')
    process_dir(r'C:\Users\Admin\.hermes\skills')
    print('Done!')
