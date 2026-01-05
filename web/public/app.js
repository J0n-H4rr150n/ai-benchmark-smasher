const API_BASE = "http://localhost:8000"; // Default, update via UI if needed
let SESSION_ID = null;
let IS_RUNNING = false;
let TURN_COUNT = 0;

// In-flight request UI state
let THINKING_INTERVAL_ID = null;
let THINKING_STARTED_AT = null;
let THINKING_ELEMENT = null;

// DOM Elements
const startBtn = document.getElementById('startBtn');
const pauseBtn = document.getElementById('pauseBtn');
const stopBtn = document.getElementById('stopBtn');
const statusIndicator = document.getElementById('statusIndicator');
const chatContainer = document.getElementById('chatContainer');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const hitlModal = document.getElementById('hitlModal');
const humanInput = document.getElementById('humanInput');
const submissionGuidanceBtn = document.getElementById('submitGuidanceBtn');

// DOMPurify is loaded locally from /vendor/dompurify/purify.min.js (see index.html)
function sanitizeHtml(unsafeHtml) {
    if (unsafeHtml == null) return '';
    if (typeof DOMPurify === 'undefined') return String(unsafeHtml);
    return DOMPurify.sanitize(String(unsafeHtml), {
        USE_PROFILES: { html: true }
    });
}

function showThinkingIndicator() {
    hideThinkingIndicator();

    THINKING_STARTED_AT = performance.now();

    const row = document.createElement('div');
    row.className = 'thinking-row';

    const spinner = document.createElement('div');
    spinner.className = 'thinking-spinner';

    const text = document.createElement('div');
    text.className = 'thinking-text';
    text.textContent = 'Thinking… 0.0s';

    row.appendChild(spinner);
    row.appendChild(text);
    chatContainer.appendChild(row);
    THINKING_ELEMENT = row;

    THINKING_INTERVAL_ID = window.setInterval(() => {
        if (!THINKING_ELEMENT) return;
        const elapsedMs = performance.now() - THINKING_STARTED_AT;
        const elapsedSec = (elapsedMs / 1000).toFixed(1);
        text.textContent = `Thinking… ${elapsedSec}s`;
    }, 100);

    scrollToBottom();
}

function hideThinkingIndicator() {
    if (THINKING_INTERVAL_ID) {
        window.clearInterval(THINKING_INTERVAL_ID);
        THINKING_INTERVAL_ID = null;
    }
    THINKING_STARTED_AT = null;
    if (THINKING_ELEMENT && THINKING_ELEMENT.parentNode) {
        THINKING_ELEMENT.parentNode.removeChild(THINKING_ELEMENT);
    }
    THINKING_ELEMENT = null;
}

// Regression guard: prevent accidentally reintroducing HTML sinks.
// This app should never set non-empty innerHTML with untrusted data.
(function installInnerHtmlGuard() {
    if (window.__DISABLE_HTML_SINK_GUARDS__) return;

    const isNonEmpty = (value) => {
        if (value == null) return false;
        return String(value).trim().length > 0;
    };

    try {
        const desc = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
        if (!desc || typeof desc.set !== 'function' || typeof desc.get !== 'function') return;
        if (desc.set.__innerHtmlGuarded) return;

        const originalSet = desc.set;
        const originalGet = desc.get;
        const guardedSet = function (value) {
            if (isNonEmpty(value)) {
                throw new Error('Blocked non-empty innerHTML assignment. Use textContent or sanitize explicitly.');
            }
            return originalSet.call(this, value);
        };
        guardedSet.__innerHtmlGuarded = true;

        Object.defineProperty(Element.prototype, 'innerHTML', {
            configurable: true,
            enumerable: desc.enumerable,
            get: originalGet,
            set: guardedSet
        });
    } catch (e) {
        // If the browser blocks patching the descriptor, fail open but warn.
        console.warn('Could not install innerHTML guard:', e);
    }
})();

// Helper to get API URL
const getApiUrl = () => API_BASE;

// Start / Resume Mission
startBtn.addEventListener('click', async () => {
    // If resuming from pause
    if (!IS_RUNNING && SESSION_ID) {
        IS_RUNNING = true;
        updateStatus('RUNNING');
        startBtn.disabled = true;
        pauseBtn.disabled = false;
        stopBtn.disabled = false;
        setInputState(true);
        runMissionLoop();
        return;
    }

    // New Session
    const goal = document.getElementById('missionGoal').value;
    const targetUrl = document.getElementById('targetUrl').value;

    try {
        const res = await fetch(`${getApiUrl()}/sessions/`, {
            method: 'POST',
            body: JSON.stringify({
                target_url: targetUrl,
                goal: goal
            }),
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        SESSION_ID = data.id;

        IS_RUNNING = true;
        TURN_COUNT = 0;
        updateStatus('RUNNING');
        startBtn.disabled = true;
        pauseBtn.disabled = false;
        stopBtn.disabled = false;
        setInputState(true);

        chatContainer.innerHTML = ''; // Clear chat
        addMessage('system', `Mission Started. Session ID: ${SESSION_ID}`);

        // Ensure the Run History reflects the current session
        loadSessionHistory();

        runMissionLoop();

    } catch (e) {
        alert(`Failed to start session: ${e}`);
    }
});

// Pause Mission
pauseBtn.addEventListener('click', () => {
    IS_RUNNING = false;
    updateStatus('PAUSED');
    startBtn.innerText = 'Resume Mission';
    startBtn.disabled = false;
    pauseBtn.disabled = true;
    setInputState(true); // Enable chat input when paused
    addMessage('system', 'Mission Paused. You can now enter manual instructions.');
});

// Stop Mission
stopBtn.addEventListener('click', () => {
    IS_RUNNING = false;
    updateStatus('STOPPED');
    startBtn.innerText = 'Start Mission';
    startBtn.disabled = false;
    pauseBtn.disabled = true;
    stopBtn.disabled = true;
    setInputState(false);
    addMessage('system', 'Mission Stopped by User.');
});

// Send Chat Message (Interrupt)
sendBtn.addEventListener('click', async () => {
    const text = chatInput.value.trim();
    if (!text) return;

    // If running, user interrupt pauses auto-loop
    if (IS_RUNNING) {
        IS_RUNNING = false;
        updateStatus('INTERRUPTED');
        startBtn.innerText = 'Resume Mission';
        startBtn.disabled = false;
        pauseBtn.disabled = true;
    }

    addMessage('user', text);
    chatInput.value = '';

    // Execute single turn with user input
    await executeTurn(text);
});
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendBtn.click();
});

function setInputState(enabled) {
    chatInput.disabled = !enabled;
    sendBtn.disabled = !enabled;
}

// Main Autonomous Loop
async function runMissionLoop() {
    while (IS_RUNNING) {
        try {
            await executeTurn("Proceed");

            // Re-check running state after await
            if (!IS_RUNNING) break;

        } catch (e) {
            console.error(e);
            addMessage('system', `Error: ${e.message}`);
            IS_RUNNING = false;
            updateStatus('ERROR');
            break;
        }
    }
}

// Execute Single Turn
async function executeTurn(messageInput) {
    TURN_COUNT++;
    document.getElementById('turnCount').innerText = TURN_COUNT;

    showThinkingIndicator();

    let response;
    let data;
    try {
        response = await fetch(`${getApiUrl()}/chat/`, {
            method: 'POST',
            body: JSON.stringify({ session_id: SESSION_ID, message: messageInput }),
            headers: { 'Content-Type': 'application/json' }
        });

        data = await response.json();
    } finally {
        hideThinkingIndicator();
    }

    renderAssistantResponse(data);

    if (data.llm_confidence_score && parseFloat(data.llm_confidence_score) < 0.5) {
        await triggerHumanIntervention(data);
    }

    if (data.content && data.content.includes("GOAL-COMPLETE")) {
        IS_RUNNING = false;
        updateStatus('COMPLETE');
        addMessage('system', '🎯 Mission Accomplished!');
        startBtn.disabled = false;
        pauseBtn.disabled = true;
        stopBtn.disabled = true;
        setInputState(false);
    }
}

// Render Messages & Screenshots
function renderAssistantResponse(data) {
    // 0. Collapsible Step Container
    const stepDetails = document.createElement('details');
    stepDetails.className = 'step-container';
    stepDetails.open = true;

    const stepSummary = document.createElement('summary');
    stepSummary.className = 'step-summary';
    stepSummary.textContent = `Step ${TURN_COUNT}`;
    stepDetails.appendChild(stepSummary);

    chatContainer.appendChild(stepDetails);

    const stepBody = document.createElement('div');
    stepBody.className = 'step-body';
    stepDetails.appendChild(stepBody);

    // 1. Tool Calls
    if (data.tool_calls) {
        data.tool_calls.forEach(tc => {
            const toolDiv = document.createElement('div');
            toolDiv.className = 'tool-call';
            toolDiv.innerText = `🛠️ ${tc.tool}(${JSON.stringify(tc.args)})`;
            stepBody.appendChild(toolDiv);
        });
    }

    // 2. Logic to Find and Display Screenshots INLINE
    if (data.tool_results) {
        // console.log("[DEBUG] Tool Results:", data.tool_results); 
        data.tool_results.forEach(res => {
            try {
                // Backend returns flat object, but handle legacy nested structure just in case
                let params = res.result || res;
                let screenshotPath = null;

                if (typeof params === 'string') {
                    try {
                        const parsed = JSON.parse(params);
                        if (parsed.screenshot_path) screenshotPath = parsed.screenshot_path;
                    } catch (e) {
                        // Fallback check
                    }
                } else if (typeof params === 'object' && params !== null) {
                    if (params.screenshot_path) screenshotPath = params.screenshot_path;
                }

                if (screenshotPath) {
                    addInlineScreenshot(screenshotPath, !!data.skipScroll, stepBody);
                }
            } catch (e) { console.error("Error parsing tool result", e); }
        });
    }

    // 3. Reasoning Panel
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';

    const appendTextBlock = (label, text) => {
        if (!text) return;
        const section = document.createElement('div');
        section.className = 'assistant-section';

        if (label) {
            const strong = document.createElement('strong');
            strong.textContent = `${label}:`;
            section.appendChild(strong);
        }

        const pre = document.createElement('pre');
        pre.className = 'assistant-pre';
        pre.textContent = text;
        section.appendChild(pre);

        msgDiv.appendChild(section);
    };

    appendTextBlock('Analysis', data.llm_analysis);
    appendTextBlock('Critique', data.llm_critique);
    appendTextBlock('Next', data.llm_next_steps);
    appendTextBlock(null, data.content);

    if (msgDiv.textContent && msgDiv.textContent.trim()) {
        stepBody.appendChild(msgDiv); // Text Bubble

        // Metadata (Outside Bubble)
        if (data.timestamp || data.model_used) {
            const metaDiv = document.createElement('div');
            metaDiv.className = 'message-meta';
            const timeStr = data.timestamp ? new Date(data.timestamp).toLocaleString() : '';
            const modelStr = data.model_used || 'Unknown Model';
            const elapsedStr = data.elapsed_time ? ` | ${data.elapsed_time}s` : '';

            metaDiv.innerText = `${timeStr} | ${modelStr}${elapsedStr}`;
            stepBody.appendChild(metaDiv);
        }
    }

    // Scroll to bottom
    if (!data.skipScroll) {
        scrollToBottom();
    }

    // Update Confidence
    if (data.llm_confidence_score) {
        document.getElementById('confidenceScore').innerText = data.llm_confidence_score;
    }
}


function addInlineScreenshot(fullPath, skipScroll = false, parentEl = chatContainer) {
    const filename = fullPath.split(/[\/\\]/).pop();
    const safeFilename = encodeURIComponent(filename || '');
    const url = `${getApiUrl()}/screenshots/${safeFilename}`;

    const img = document.createElement('img');
    img.className = 'chat-thumbnail';
    img.src = url;
    img.onclick = () => window.open(url, '_blank');
    img.title = "Click to view full size";

    // Auto-scroll when image loads
    img.onload = () => {
        if (!skipScroll) scrollToBottom();
    };

    parentEl.appendChild(img);
}

function addMessage(role, text, skipScroll = false) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerText = text;
    chatContainer.appendChild(div);
    if (!skipScroll) scrollToBottom();
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function updateStatus(status) {
    statusIndicator.innerText = status;
    statusIndicator.className = `status-badge ${status.toLowerCase()}`;
}

// Human Intervention Logic
async function triggerHumanIntervention(data) {
    // Pause Loop
    IS_RUNNING = false;
    updateStatus('PAUSED (HITL)');

    // Show Modal
    const thoughts = data.llm_analysis || data.llm_critique || "Uncertain about next steps.";
    document.getElementById('lowConfidenceThought').innerText = thoughts;
    hitlModal.classList.remove('hidden');

    // Wait for User Submit
    return new Promise((resolve) => {
        submitGuidanceBtn.onclick = async () => {
            const guidance = humanInput.value;
            hitlModal.classList.add('hidden');
            humanInput.value = '';

            // Send Guidance as User Message
            addMessage('user', `Guidance: ${guidance}`);

            // Call Chat with user message
            await fetch(`${getApiUrl()}/chat/`, {
                method: 'POST',
                body: JSON.stringify({ session_id: SESSION_ID, message: guidance }),
                headers: { 'Content-Type': 'application/json' }
            });

            // Resume Loop
            IS_RUNNING = true;
            updateStatus('RUNNING');
            runMissionLoop(); // Restart loop
            resolve();
        };
    });
}

// --- History Logic ---

async function loadSessionHistory() {
    try {
        const res = await fetch(`${getApiUrl()}/chat/sessions?limit=50`);
        const sessions = await res.json();
        renderSessionList(sessions);
    } catch (e) {
        console.error("Failed to load history:", e);
    }
}

function renderSessionList(sessions) {
    const listForDom = document.getElementById('sessionList');
    listForDom.innerHTML = '';

    sessions.forEach(s => {
        const item = document.createElement('div');
        item.className = 'session-item';
        if (s.id === SESSION_ID) item.classList.add('active');

        const date = new Date(s.updated_at).toLocaleString();
        const shortGoal = s.goal ? (s.goal.substring(0, 40) + '...') : s.target_url;

        const main = document.createElement('div');
        main.className = 'session-main';
        main.textContent = shortGoal;

        const meta = document.createElement('div');
        meta.className = 'session-meta';

        const idSpan = document.createElement('span');
        idSpan.className = 'session-id';
        idSpan.textContent = `#${s.id}`;

        const dateSpan = document.createElement('span');
        dateSpan.textContent = date;

        meta.appendChild(idSpan);
        meta.appendChild(dateSpan);
        item.appendChild(main);
        item.appendChild(meta);

        item.onclick = () => loadSession(s.id);
        listForDom.appendChild(item);
    });
}

async function loadSession(id) {
    SESSION_ID = id;
    IS_RUNNING = false;
    updateStatus('HISTORY VIEW');
    chatContainer.innerHTML = '';

    // Highlight active
    document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
    // (Ideally find specific item and add active, but redraw works too)

    try {
        const res = await fetch(`${getApiUrl()}/chat/history?session_id=${id}&limit=100`);
        const history = await res.json(); // Ordered chronologically

        history.forEach(msg => {
            if (msg.role === 'user') {
                addMessage('user', msg.content, true); // true = skipScroll
            } else {
                renderAssistantResponse({
                    content: msg.content,
                    tool_calls: msg.tool_calls,
                    tool_results: msg.tool_results,
                    llm_analysis: msg.llm_analysis,
                    llm_critique: msg.llm_critique,
                    llm_next_steps: msg.llm_next_steps,
                    llm_confidence_score: msg.llm_confidence_score,
                    timestamp: msg.created_at,
                    skipScroll: true // Pass skipScroll
                });
            }
        });

        // Scroll once at the end
        // Short timeout to allow CSS layout to settle for a moment
        setTimeout(scrollToBottom, 50);

        // Refresh list to show active state
        loadSessionHistory();

    } catch (e) {
        console.error("Failed to load session:", e);
    }
}

// Init
loadSessionHistory();
