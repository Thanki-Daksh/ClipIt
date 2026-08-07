import os

startup_boxes = {
    'Agent-01': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/core`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && hermes`
> - **SKILL**: `/ClipIt-Systems-Architect`''',

    'Agent-02': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **agy Activation Command (Gemini 3.6 Flash - Primary Vision + STT)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && hermes`
> - **SKILL**: `/ClipIt-AI-Ingestion-Specialist`''',

    'Agent-03': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && hermes`
> - **SKILL**: `/ClipIt-Media-Graphics-Engineer`''',

    'Agent-04': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/ui`
> - **agy Activation Command (Gemini 3.6 Flash / Claude 3.5 Sonnet)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/ui" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/ui" && clear && hermes`
> - **SKILL**: `/ClipIt-Frontend-Mobile-UI-Dev`''',

    'Agent-05': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && agy`
> - **SKILL**: `/ClipIt-Mobile-Daemon-OS-Runtime`''',

    'Agent-06': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/tests`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/tests" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/tests" && clear && agy`
> - **SKILL**: `/ClipIt-QA-Security-Auditor`''',

    'ceo': '''> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt`
> - **agy Activation Command (Gemini 3.6 Flash / Claude 3.5 Sonnet)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt" && clear && hermes`
> - **SKILL**: `/ceo`'''
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
            print(f'Updated launch box in: {filepath}')

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
    print('Launch boxes updated cleanly!')
