import os

startup_boxes = {
    'Agent-01': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/core`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` (High Effort - High Usage Quota)
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (OpenCode Zen - 200k Context)
> - **Secondary Fallback**: `Claude 3.5 Sonnet`''',

    'Agent-02': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` (High Effort - Vision + STT - High Usage Quota)
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (200k Context for long transcripts)
> - **Secondary Fallback**: `GPT-4o`''',

    'Agent-03': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` (High Effort - High Usage Quota)
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (200k Context)
> - **Secondary Fallback**: `Claude 3.5 Sonnet`''',

    'Agent-04': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/ui`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/ui" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` (High Effort - High Usage Quota)
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (200k Context)
> - **Secondary Fallback**: `Claude 3.5 Sonnet` (Use sparingly for UI polish)''',

    'Agent-05': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` / `DeepSeek v4 Flash-Free` (200k Context - FREE!)
> - **Effort Level**: `High Effort` / `Medium Effort`
> - **Secondary Fallback**: `Opencode Zen (-free)`''',

    'Agent-06': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/tests`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/tests" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` (High Effort - High Usage Quota)
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (200k Context)
> - **Secondary Fallback**: `Claude 3.5 Sonnet`''',

    'ceo': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt`
> - **Activation Command**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt" && clear && agy`
> - **Primary Model**: `Gemini 3.6 Flash` / `Gemini Pro` (High Effort - High Usage Quota)
> - **Free Fallback Model**: `DeepSeek v4 Flash-Free` (200k Context)
> - **Secondary Fallback**: `Claude 3.5 Sonnet` (Use sparingly for architecture reviews)'''
}

def update_file(filepath):
    filename = os.path.basename(filepath)
    for key, box_text in startup_boxes.items():
        if key.lower() in filename.lower():
            with open(filepath, 'r', encoding='utf-8') as fh:
                content = fh.read()
            
            if '[!LAUNCH]' in content:
                lines = content.splitlines()
                new_lines = []
                in_launch = False
                for line in lines:
                    if '[!LAUNCH]' in line:
                        in_launch = True
                        new_lines.append(box_text)
                    elif in_launch and line.startswith('>'):
                        continue
                    else:
                        in_launch = False
                        new_lines.append(line)
                new_content = '\n'.join(new_lines)
            else:
                new_content = box_text + '\n\n' + content
                
            with open(filepath, 'w', encoding='utf-8') as fh:
                fh.write(new_content)
            print(f'Updated Gemini priority in: {filepath}')

def process_dir(d):
    for root, dirs, files in os.walk(d):
        for f in files:
            if f.endswith('.md'):
                update_file(os.path.join(root, f))

if __name__ == '__main__':
    process_dir(r'C:\Users\Admin\OneDrive\Desktop\ClipIt\agents')
    process_dir(r'C:\Users\Admin\OneDrive\Desktop\ClipIt\OBSIDIAN VAULT (TREASURE)\AGENTS')
    process_dir(r'C:\Users\Admin\.gemini\config\skills')
    process_dir(r'C:\Users\Admin\.agents\skills')
    process_dir(r'C:\Users\Admin\.hermes\skills')
    print('Gemini model priority update complete!')
