import os
import re

admin_dash_path = r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\admin_dashboard.html'
with open(admin_dash_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Replace main content area
main_content_regex = r'(<!-- Dynamic Content Area -->\s*<div class="p-8 max-w-7xl mx-auto w-full space-y-8">).*?(</main>)'

# Storage Page Content
storage_content = """\\1
            <div class="flex justify-between items-end">
                <div>
                    <h2 class="text-2xl font-extrabold text-gray-900">Cloud Storage Management</h2>
                    <p class="text-sm text-gray-500 mt-1">Detailed view of data partitioning, archives, and cloud vault metrics.</p>
                </div>
            </div>

            <!-- Storage details -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-gray-100 flex flex-col justify-between">
                    <h3 class="text-sm font-bold text-gray-900 mb-4">Total Storage Volume</h3>
                    <div class="flex justify-center flex-1 items-center">
                        <div class="relative w-48 h-48 rounded-full border-[16px] border-orange-100 flex items-center justify-center">
                            <div class="absolute inset-[-16px] rounded-full border-[16px] border-orange-500" style="clip-path: polygon(50% 50%, 50% 0%, 100% 0%, 100% 100%, 0% 100%, 0% 50%); transform: rotate(15deg)"></div>
                            <div class="text-center z-10">
                                <span class="block text-2xl font-extrabold text-gray-900">{{ storage_display }}</span>
                                <span class="text-xs font-bold text-orange-500 uppercase tracking-widest">{{ storage_pct|round(1) }}% Used</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-gray-100 h-full overflow-y-auto">
                    <h3 class="text-sm font-bold text-gray-900 mb-4">Network Node Distribution</h3>
                    <ul class="space-y-4">
                        {% for group in active_groups %}
                        <li class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                            <div class="flex items-center gap-3">
                                <i class="fa-solid fa-server text-blue-500 text-lg"></i>
                                <div>
                                    <p class="text-sm font-bold text-gray-900">{{ group.owner_name }} Vault</p>
                                    <p class="text-[10px] text-gray-500 font-mono">{{ group.owner_email }}</p>
                                </div>
                            </div>
                            <div class="text-right">
                                <p class="text-sm font-bold text-gray-700">{{ group.member_count * 2.4 | round(1) }} GB</p>
                                <p class="text-[10px] text-green-500 font-bold uppercase">Active</p>
                            </div>
                        </li>
                        {% else %}
                        <li class="p-8 text-center text-gray-400 text-sm">No storage partitions currently allocated.</li>
                        {% endfor %}
                    </ul>
                </div>
            </div>
        </div>
        \\2"""

# Activity Page Content
activity_content = """\\1
            <div class="flex justify-between items-end">
                <div>
                    <h2 class="text-2xl font-extrabold text-gray-900">User Activity Auditing</h2>
                    <p class="text-sm text-gray-500 mt-1">Comprehensive system-wide logs for authentication and data transactions.</p>
                </div>
                <div class="flex gap-4">
                    <button class="px-5 py-2.5 bg-white border border-gray-200 text-gray-700 font-bold text-sm tracking-wide rounded-lg shadow-sm cursor-not-allowed opacity-50"><i class="fa-solid fa-download"></i> Export PCAP</button>
                </div>
            </div>

            <!-- Full width table for activities -->
            <div class="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
                <div class="p-6 border-b border-gray-100 flex justify-between items-center bg-gray-50/50">
                    <div class="relative w-64">
                         <input type="text" placeholder="Filter by event type or user..." class="w-full bg-white border border-gray-200 rounded text-sm p-2 pl-8">
                         <i class="fa-solid fa-filter absolute left-3 top-3 text-gray-400 text-xs"></i>
                    </div>
                </div>
                <div class="overflow-x-auto max-h-[60vh]">
                    <table class="w-full text-left">
                        <thead class="sticky top-0 bg-white shadow-sm z-10">
                            <tr class="text-[10px] font-bold text-gray-400 uppercase tracking-widest border-b border-gray-100">
                                <th class="p-4 pl-6">Client Identity</th>
                                <th class="p-4">Event Classification</th>
                                <th class="p-4">Target Resource</th>
                                <th class="p-4">Timestamp (UTC)</th>
                                <th class="p-4 pr-6 text-right">Integrity Status</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm font-medium text-gray-700 divide-y divide-gray-50">
                            {% for log in logs %}
                            <tr class="hover:bg-gray-50 transition">
                                <td class="p-4 pl-6">
                                    <div class="flex items-center gap-3">
                                        <div class="w-8 h-8 rounded-full bg-blue-50 text-blue-600 font-bold flex items-center justify-center text-xs uppercase border border-blue-100">
                                            {{ log.user[:2] }}
                                        </div>
                                        <div>
                                            <p class="font-bold text-gray-900 text-sm">{{ log.user.split('@')[0].capitalize() }}</p>
                                            <p class="text-[10px] text-gray-500">{{ log.user }}</p>
                                        </div>
                                    </div>
                                </td>
                                <td class="p-4">
                                    <span class="inline-flex items-center px-2 py-1 rounded text-[10px] font-bold bg-gray-100 text-gray-700 border border-gray-200 uppercase tracking-wider">{{ log.action }}</span>
                                </td>
                                <td class="p-4">
                                    <div class="text-xs font-mono text-gray-500 bg-gray-50 px-2 py-1 rounded w-max truncate max-w-[200px]" title="{{ log.resource }}">
                                        {{ log.resource }}
                                    </div>
                                </td>
                                <td class="p-4 font-mono text-xs text-gray-500">{{ log.time }}</td>
                                <td class="p-4 pr-6 text-right">
                                    {% if 'Gap' in log.action or 'Alert' in log.action %}
                                        <i class="fa-solid fa-flag text-red-500 text-lg"></i>
                                    {% else %}
                                        <i class="fa-solid fa-check text-green-500 text-lg"></i>
                                    {% endif %}
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="5" class="p-8 text-center text-gray-400 text-sm">No activity recorded across the network.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        \\2"""

storage_html = re.sub(main_content_regex, storage_content, html, flags=re.DOTALL)
activity_html = re.sub(main_content_regex, activity_content, html, flags=re.DOTALL)

# Update sidebar active states
def update_active_state(html_src, new_page):
    # reset dashboard active
    html_src = html_src.replace('class="flex items-center gap-3 px-4 py-3 rounded-lg transition bg-green-800 border-l-4 border-green-400 text-white"', 'class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white"')
    
    # We will just patch the template active states dynamically like the other pages if we want,
    # but since admin dashboard doesn't use jinja {% if active_page == ... %} for the sidebar, we'll hardcode the replacement.
    if new_page == 'Storage':
        html_src = html_src.replace(
            '<a href="#"\\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\\n                    <i class="fa-solid fa-database w-5 text-center"></i> Storage',
            '<a href="/admin/storage"\\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition bg-green-800 border-l-4 border-green-400 text-white">\\n                    <i class="fa-solid fa-database w-5 text-center"></i> Storage'
        )
    elif new_page == 'User Activity':
        html_src = html_src.replace(
            '<a href="#"\\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\\n                    <i class="fa-solid fa-users w-5 text-center"></i> User Activity',
            '<a href="/admin/activity"\\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition bg-green-800 border-l-4 border-green-400 text-white">\\n                    <i class="fa-solid fa-users w-5 text-center"></i> User Activity'
        )
    return html_src

storage_html = update_active_state(storage_html, 'Storage')
activity_html = update_active_state(activity_html, 'User Activity')

# Also we need to ensure the hrefs in admin_dashboard point to the right places
admin_dash_update = html.replace('<a href="#"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-database w-5 text-center"></i> Storage',
'<a href="/admin/storage"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-database w-5 text-center"></i> Storage')
admin_dash_update = admin_dash_update.replace('<a href="#"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-users w-5 text-center"></i> User Activity',
'<a href="/admin/activity"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-users w-5 text-center"></i> User Activity')

# and identical href fixes in storage and activity htmls
storage_html = storage_html.replace('href="#"', 'href="/admin_dashboard"', 1)
storage_html = storage_html.replace('<a href="#"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-users w-5 text-center"></i> User Activity',
'<a href="/admin/activity"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-users w-5 text-center"></i> User Activity')

activity_html = activity_html.replace('href="#"', 'href="/admin_dashboard"', 1)
activity_html = activity_html.replace('<a href="#"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-database w-5 text-center"></i> Storage',
'<a href="/admin/storage"\n                    class="flex items-center gap-3 px-4 py-3 rounded-lg transition text-green-100 hover:bg-green-800 hover:text-white">\n                    <i class="fa-solid fa-database w-5 text-center"></i> Storage')

with open(r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\admin_storage.html', 'w', encoding='utf-8') as f:
    f.write(storage_html)

with open(r'c:\Users\gsuba\OneDrive\Desktop\my_project\templates\admin_activity.html', 'w', encoding='utf-8') as f:
    f.write(activity_html)

with open(admin_dash_path, 'w', encoding='utf-8') as f:
    f.write(admin_dash_update)

print("Generated Admin pages successfully.")
