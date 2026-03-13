"""
DuckClaw Skill Knowledge Base.
Canonical list of skill metadata used for ChromaDB seeding and semantic routing.
"""

SKILLS: list[dict] = [
    {
        "skill_id": "skill_web_search",
        "name": "web_search",
        "description": (
            "Search the web using DuckDuckGo. Free, no API key required. "
            "Use for real-time information, news, facts, prices, or anything "
            "that requires up-to-date data not in the model's training data. "
            "Also supports fetching latest news headlines on a topic."
        ),
        "use_cases": [
            "search the web for X",
            "what is the latest news about X",
            "find information about X online",
            "look up X on the internet",
            "current price of X",
        ],
        "input_format": (
            'action="search": {"query": "<search terms>", "max_results": 5}  // max_results optional, default 5, max 10\n'
            'action="news":   {"query": "<topic>", "max_results": 5}         // max_results optional, default 5, max 10'
        ),
        "output_format": (
            '{"skill": "web_search", "action": "search", "params": {"query": "<search terms>", "max_results": 5}}\n'
            '// or for news:\n'
            '{"skill": "web_search", "action": "news", "params": {"query": "<topic>", "max_results": 5}}'
        ),
    },
    {
        "skill_id": "skill_web_browser",
        "name": "web_browser",
        "description": (
            "Full browser automation via Playwright. Navigate to URLs, click buttons, "
            "fill forms, extract text content, and take screenshots of web pages. "
            "Use when web_search is insufficient and you need to visit a specific URL "
            "or interact with a webpage."
        ),
        "use_cases": [
            "open the website X",
            "go to URL X and extract the content",
            "fill out the form at X",
            "take a screenshot of X",
            "click the button on page X",
            "search and return results without navigating",
        ],
        "input_format": (
            'action="navigate":     {"url": "<full URL>"}\n'
            'action="extract_text": {"max_links": 20}                                                         // max_links optional, default 20; requires navigate first\n'
            'action="screenshot":   {"full_page": false}                                                      // full_page optional, default false; requires navigate first\n'
            'action="click":        {"selector": "<CSS selector>", "text": "<visible text>"}                  // selector OR text required; requires navigate first\n'
            'action="fill_form":    {"fields": [{"selector": "<CSS>", "value": "<text>"}], "submit": false}   // submit optional, default false; requires navigate first\n'
            'action="search":       {"query": "<search terms>", "max_results": 8}                             // max_results optional, default 8; no navigate needed'
        ),
        "output_format": (
            '{"skill": "web_browser", "action": "navigate", "params": {"url": "<full URL>"}}\n'
            '// or extract text (after navigate):\n'
            '{"skill": "web_browser", "action": "extract_text", "params": {"max_links": 20}}\n'
            '// or screenshot (after navigate):\n'
            '{"skill": "web_browser", "action": "screenshot", "params": {"full_page": false}}\n'
            '// or click (after navigate):\n'
            '{"skill": "web_browser", "action": "click", "params": {"selector": "<CSS>", "text": "<visible text>"}}\n'
            '// or fill form (after navigate):\n'
            '{"skill": "web_browser", "action": "fill_form", "params": {"fields": [{"selector": "<CSS>", "value": "<text>"}], "submit": false}}\n'
            '// or search (standalone):\n'
            '{"skill": "web_browser", "action": "search", "params": {"query": "<search terms>", "max_results": 8}}'
        ),
    },
    {
        "skill_id": "skill_file_manager",
        "name": "file_manager",
        "description": (
            "Read, write, list, search, and delete files on the local filesystem. "
            "Scoped to allowed paths (~/Documents, ~/Downloads, ~/Desktop, ~/Projects); "
            "credential files are always blocked. "
            "Use for reading config files, saving notes, listing directories, "
            "searching files by name or content, or writing output to a file."
        ),
        "use_cases": [
            "read the file at path X",
            "write X to a file",
            "list files in directory X",
            "what is in the file X",
            "save this to X",
            "show me the contents of X",
            "find files matching pattern X",
            "delete the file X",
            "create directory X",
        ],
        "input_format": (
            'action="read":       {"path": "<file path>"}\n'
            'action="write":      {"path": "<file path>", "content": "<text to write>"}\n'
            'action="list":       {"path": "<directory path>"}                                            // path optional, default ~\n'
            'action="search":     {"path": "<root dir>", "pattern": "<glob>", "content": "<text>"}       // all optional; path default ~\n'
            'action="delete":     {"path": "<file path>"}\n'
            'action="create_dir": {"path": "<directory path>"}'
        ),
        "output_format": (
            '{"skill": "file_manager", "action": "read", "params": {"path": "<file path>"}}\n'
            '// or write:\n'
            '{"skill": "file_manager", "action": "write", "params": {"path": "<file path>", "content": "<text>"}}\n'
            '// or list:\n'
            '{"skill": "file_manager", "action": "list", "params": {"path": "<directory path>"}}\n'
            '// or search:\n'
            '{"skill": "file_manager", "action": "search", "params": {"path": "<root>", "pattern": "<glob>", "content": "<text>"}}\n'
            '// or delete:\n'
            '{"skill": "file_manager", "action": "delete", "params": {"path": "<file path>"}}\n'
            '// or create directory:\n'
            '{"skill": "file_manager", "action": "create_dir", "params": {"path": "<directory path>"}}'
        ),
    },
    {
        "skill_id": "skill_shell_runner",
        "name": "shell_runner",
        "description": (
            "Execute shell commands on the local machine. "
            "Dangerous patterns (rm -rf, sudo, etc.) are permanently blocked. "
            "NOTIFY-tier commands (ls, cat, git status) auto-approve; "
            "ASK-tier commands require explicit user approval. "
            "Use for running scripts, git operations, checking system info, etc."
        ),
        "use_cases": [
            "run the command X",
            "execute X in terminal",
            "run the shell script X",
            "check git status",
            "list running processes",
            "install the package X",
        ],
        "input_format": (
            'action="run":        {"command": "<shell command string>"}\n'
            'action="check_safe": {"command": "<shell command string>"}  // dry-run safety check without executing'
        ),
        "output_format": (
            '{"skill": "shell_runner", "action": "run", "params": {"command": "<shell command string>"}}\n'
            '// or to check if a command is safe without running it:\n'
            '{"skill": "shell_runner", "action": "check_safe", "params": {"command": "<shell command string>"}}'
        ),
    },
    {
        "skill_id": "skill_screen_capture",
        "name": "screen_capture",
        "description": (
            "Take a screenshot of the current screen and analyze it with vision AI. "
            "ASK-tier — requires explicit user approval before capturing. "
            "Use when the user wants to know what is on their screen or asks you to "
            "look at something on their display."
        ),
        "use_cases": [
            "take a screenshot",
            "what is on my screen",
            "capture my screen",
            "analyze what is on my screen",
            "look at my screen and tell me X",
            "list available monitors",
        ],
        "input_format": (
            'action="capture":       {"monitor": 0, "question": "<what to analyze>"}  // monitor optional default 0; question optional default "What\'s on the screen?"\n'
            'action="list_monitors": {}                                                 // no params'
        ),
        "output_format": (
            '{"skill": "screen_capture", "action": "capture", "params": {"monitor": 0, "question": "<what to analyze>"}}\n'
            '// or to list monitors:\n'
            '{"skill": "screen_capture", "action": "list_monitors", "params": {}}'
        ),
    },
    {
        "skill_id": "skill_camera",
        "name": "camera",
        "description": (
            "Capture a photo from the webcam and optionally analyze it with vision AI. "
            "ASK-tier — requires explicit user approval. "
            "Use when the user asks you to see them, identify objects in front of the camera, "
            "or capture a photo."
        ),
        "use_cases": [
            "take a photo with the camera",
            "capture from webcam",
            "look at me",
            "what do you see through the camera",
            "take a picture of X",
            "list available cameras",
        ],
        "input_format": (
            'action="snap":         {"camera_index": 0, "quality": 85}                                          // all optional\n'
            'action="snap_analyze": {"camera_index": 0, "prompt": "<question about the photo>", "quality": 85}  // all optional\n'
            'action="list_cameras": {}                                                                            // no params'
        ),
        "output_format": (
            '{"skill": "camera", "action": "snap", "params": {"camera_index": 0, "quality": 85}}\n'
            '// or capture with AI analysis:\n'
            '{"skill": "camera", "action": "snap_analyze", "params": {"camera_index": 0, "prompt": "<question>", "quality": 85}}\n'
            '// or list cameras:\n'
            '{"skill": "camera", "action": "list_cameras", "params": {}}'
        ),
    },
    {
        "skill_id": "skill_scheduler",
        "name": "scheduler",
        "description": (
            "Create one-time reminders and recurring cron jobs using APScheduler. "
            "Use when the user wants to schedule something, set a reminder, "
            "or run a task at a specific time or interval."
        ),
        "use_cases": [
            "remind me to X in Y minutes",
            "remind me at HH:MM to X",
            "schedule X every day at Y",
            "set a reminder for X",
            "create a recurring cron job for X",
            "list all scheduled tasks",
            "cancel the reminder with id X",
            "set up a daily morning briefing",
        ],
        "input_format": (
            'action="remind_in":     {"minutes": <int>, "hours": <int>, "message": "<text>"}       // minutes OR hours required (or both); message optional\n'
            'action="remind_at":     {"time": "<HH:MM or ISO datetime>", "message": "<text>"}      // time required; message optional\n'
            'action="add_cron":      {"cron": "<5-field expr>", "label": "<name>", "message": "<text>"}  // cron required; label and message optional\n'
            'action="morning_brief": {"time": "<HH:MM>"}                                            // time optional, default "08:00"\n'
            'action="list_jobs":     {}                                                              // no params\n'
            'action="remove_job":    {"job_id": "<id>"}'
        ),
        "output_format": (
            '{"skill": "scheduler", "action": "remind_in", "params": {"minutes": 30, "message": "<text>"}}\n'
            '// or remind at specific time:\n'
            '{"skill": "scheduler", "action": "remind_at", "params": {"time": "14:30", "message": "<text>"}}\n'
            '// or recurring cron job:\n'
            '{"skill": "scheduler", "action": "add_cron", "params": {"cron": "0 8 * * *", "label": "<name>", "message": "<text>"}}\n'
            '// or daily morning briefing:\n'
            '{"skill": "scheduler", "action": "morning_brief", "params": {"time": "08:00"}}\n'
            '// or list jobs:\n'
            '{"skill": "scheduler", "action": "list_jobs", "params": {}}\n'
            '// or remove a job:\n'
            '{"skill": "scheduler", "action": "remove_job", "params": {"job_id": "<id>"}}'
        ),
    },
]
