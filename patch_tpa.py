import os
import re

files_to_patch = [
    r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\tpa_dashboard.html',
    r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\audit_requests.html',
    r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\audit_logs.html',
    r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\auditor_settings.html',
    r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\integrity_check.html'
]

script_to_add = """
    <script>
        function showIntegrityScan(e) {
            if (e.ctrlKey || e.metaKey) return; 
            e.preventDefault();
            
            const overlay = document.createElement('div');
            overlay.className = 'fixed inset-0 bg-green-900/95 z-50 flex flex-col items-center justify-center transition-opacity duration-300';
            overlay.innerHTML = `
                <div class="relative flex items-center justify-center mb-8">
                    <div class="absolute inset-0 rounded-full border-4 border-green-400 animate-ping opacity-75 h-32 w-32 m-auto"></div>
                    <div class="bg-green-800 rounded-full h-32 w-32 flex items-center justify-center shadow-[0_0_40px_rgba(74,222,128,0.6)] z-10 m-auto relative overflow-hidden">
                        <div class="absolute inset-0 bg-gradient-to-b from-transparent via-green-400/30 to-transparent h-full w-full animate-[scanPulse_2s_linear_infinite]"></div>
                        <i class="fa-solid fa-shield-halved text-5xl text-green-400"></i>
                    </div>
                </div>
                <h2 class="text-white text-3xl font-bold tracking-wider mb-2">INTEGRITY CHECK INITIATED</h2>
                <p class="text-green-400 font-mono text-sm mb-8 animate-pulse">Initializing TPA verification protocol...</p>
                <div class="w-64 bg-green-950 rounded-full h-1.5 overflow-hidden">
                    <div class="bg-green-400 h-1.5 rounded-full animate-[scanBar_1.5s_ease-in-out_infinite] w-1/3"></div>
                </div>
                <style>
                    @keyframes scanBar {
                        0% { transform: translateX(-100%); }
                        50% { transform: translateX(300%); }
                        100% { transform: translateX(-100%); }
                    }
                    @keyframes scanPulse {
                        0% { transform: translateY(-100%); opacity: 0; }
                        50% { transform: translateY(0%); opacity: 1; }
                        100% { transform: translateY(100%); opacity: 0; }
                    }
                </style>
            `;
            document.body.appendChild(overlay);
            
            setTimeout(() => {
                window.location.href = '/auditor/verify';
            }, 1200);
        }
    </script>
</body>
"""

for filepath in files_to_patch:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Replace href="/auditor/check" with href="/auditor/verify" onclick="showIntegrityScan(event)"
    content = content.replace(
        '<a href="/auditor/check"',
        '<a href="/auditor/verify" onclick="showIntegrityScan(event)"'
    )
    
    # Also in audit_requests.html table action:
    # <a href="/auditor/check?file_id={{ req.id }}" -> <a href="/auditor/verify?file_id={{ req.id }}" onclick="showIntegrityScan(event)"
    content = content.replace(
        '<a href="/auditor/check?file_id={{ req.id }}"',
        '<a href="/auditor/verify?file_id={{ req.id }}" onclick="showIntegrityScan(event)"'
    )

    # 2. Change the icon fa-shield-check to fa-shield-halved for Integrity Check
    # Let's target simply the Integrity Check menu item text and its preceding icon
    content = re.sub(
        r'<i class="fa-solid fa-shield-check w-5 text-center"></i>(\s*)Integrity Check',
        r'<i class="fa-solid fa-shield-halved w-5 text-center"></i>\1Integrity Check',
        content
    )

    # 3. Add script block right before </body>, ensuring we don't duplicate
    if "showIntegrityScan" not in content:
        content = content.replace('</body>', script_to_add)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

print("Patch applied to all 5 files successfully.")
