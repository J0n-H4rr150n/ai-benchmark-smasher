const API_BASE = "http://localhost:8000"; // Default, update via UI if needed
let SESSION_ID = null;
let IS_RUNNING = false;
let TURN_COUNT = 0;

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
        setInputState(false);
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
        setInputState(false);

        chatContainer.innerHTML = ''; // Clear chat
        addMessage('system', `Mission Started. Session ID: ${SESSION_ID}`);

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

    const response = await fetch(`${getApiUrl()}/chat/`, {
        method: 'POST',
        body: JSON.stringify({ session_id: SESSION_ID, message: messageInput }),
        headers: { 'Content-Type': 'application/json' }
    });

    const data = await response.json();
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
    // 0. Step Header
    const stepDiv = document.createElement('div');
    stepDiv.className = 'step-header';
    stepDiv.innerText = `Step ${TURN_COUNT}`;
    chatContainer.appendChild(stepDiv);

    // 1. Tool Calls
    if (data.tool_calls) {
        data.tool_calls.forEach(tc => {
            const toolDiv = document.createElement('div');
            toolDiv.className = 'tool-call';
            toolDiv.innerText = `🛠️ ${tc.tool}(${JSON.stringify(tc.args)})`;
            chatContainer.appendChild(toolDiv);
        });
    }

    // 2. Logic to Find and Display Screenshots INLINE
    if (data.tool_results) {
        console.log("[DEBUG] Tool Results:", data.tool_results); // Debugging line
        data.tool_results.forEach(res => {
            try {
                let params = res.result;
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
                    addInlineScreenshot(screenshotPath);
                }
            } catch (e) { console.error("Error parsing tool result", e); }
        });
    }

    // 3. Reasoning Panel
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';

    let content = "";
    if (data.llm_analysis) content += `<strong>Analysis:</strong> ${data.llm_analysis}\n\n`;
    if (data.llm_critique) content += `<strong>Critique:</strong> ${data.llm_critique}\n\n`;
    if (data.llm_next_steps) content += `<strong>Next:</strong> ${data.llm_next_steps}\n\n`;
    if (data.content) content += data.content;

    if (content.trim()) {
        msgDiv.innerHTML = content.replace(/\n/g, '<br>');
        chatContainer.appendChild(msgDiv); // Text Bubble

        // Metadata (Outside Bubble)
        if (data.timestamp || data.model_used) {
            const metaDiv = document.createElement('div');
            metaDiv.className = 'message-meta';
            const timeStr = data.timestamp ? new Date(data.timestamp).toLocaleString() : '';
            const modelStr = data.model_used || 'Unknown Model';
            const elapsedStr = data.elapsed_time ? ` | ${data.elapsed_time}s` : '';

            metaDiv.innerText = `${timeStr} | ${modelStr}${elapsedStr}`;
            chatContainer.appendChild(metaDiv);
        }
    }

    // Scroll to bottom
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // Update Confidence
    if (data.llm_confidence_score) {
        document.getElementById('confidenceScore').innerText = data.llm_confidence_score;
    }
}


function addInlineScreenshot(fullPath) {
    const filename = fullPath.split(/[\/\\]/).pop();
    const url = `${getApiUrl()}/screenshots/${filename}`;

    const img = document.createElement('img');
    img.className = 'chat-thumbnail';
    img.src = url;
    img.onclick = () => window.open(url, '_blank');
    img.title = "Click to view full size";

    chatContainer.appendChild(img);
}

function addMessage(role, text) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerText = text;
    chatContainer.appendChild(div);
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
