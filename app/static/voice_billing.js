/**
 * ShopBridge Voice Billing Client v3
 * - Full-duplex continuous streaming with live barge-in interruption (Earphones optimized)
 * - Pristine 24kHz -> system sample rate Web Audio playback (eliminates Windows WASAPI distortion)
 * - Automatic microphone downsampling to 16kHz PCM mono
 * - Zero outgoing audio suppression during assistant speech
 * - Dynamic voice selection (Aoede, Puck, Kore, Fenrir, Charon)
 * - Instant playback cutoff on server INTERRUPTED signal
 * - Live token usage tracking & reactive cart rendering
 */

(function () {
  let ws = null;
  let micAudioContext = null;
  let micStream = null;
  let processorNode = null;
  let micSource = null;
  let muteGain = null;

  let isActivelyTransmitting = false;
  let isContinuous = false;
  let isGeminiSpeaking = false;

  let playbackAudioContext = null;
  let scheduledPlaybackTime = 0;
  let activeAudioSources = [];
  let currentPlaybackEpoch = 0;
  let knownLineIds = new Set();

  // DOM Elements
  const statusBadge = document.getElementById("connectionStatusBadge");
  const tokenUsageBadge = document.getElementById("tokenUsageBadge");
  const voiceSelect = document.getElementById("voiceSelect");
  const micBtn = document.getElementById("micToggleBtn");
  const micBtnText = document.getElementById("micBtnText");
  const continuousCheck = document.getElementById("continuousMicCheck");
  const clearCartBtn = document.getElementById("clearCartBtn");
  const transcriptLog = document.getElementById("transcriptLog");
  const transcriptIndicator = document.getElementById("transcriptIndicator");
  const cartTableBody = document.getElementById("cartTableBody");
  const cartTotalDisplay = document.getElementById("cartTotalDisplay");
  const itemCountLabel = document.getElementById("itemCountLabel");

  function initWebSocket() {
    if (ws) {
      try {
        ws.close();
      } catch (e) {}
      ws = null;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const voice = (voiceSelect && voiceSelect.value) || localStorage.getItem("sb_live_voice") || "Aoede";
    const sessionId = sessionStorage.getItem("sb_pos_session_id");
    const params = new URLSearchParams({ voice });
    if (sessionId) {
      params.set("session_id", sessionId);
    }
    const wsUrl = `${protocol}//${window.location.host}/ws/voice-billing?${params.toString()}`;

    updateStatus("Connecting...", "warn");
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      updateStatus("Live Ready", "ok");
      createTranscriptMessage(
        "System",
        `Connected to Gemini Live agent (${voice} voice). Earphones active: speak naturally or interrupt anytime.`,
        "system-msg"
      );
    };

    ws.onclose = () => {
      stopAllAudioPlayback();
      updateStatus("Disconnected", "danger");
      setTimeout(() => {
        if (!ws || ws.readyState === WebSocket.CLOSED) {
          initWebSocket();
        }
      }, 2000);
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
      updateStatus("Error", "danger");
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          const msg = JSON.parse(event.data);
          handleServerJson(msg);
        } catch (e) {
          console.error("Error parsing server JSON:", e, event.data);
        }
      } else if (event.data instanceof ArrayBuffer) {
        // Binary 24kHz PCM audio chunk from Gemini
        playAudioChunk(event.data);
      }
    };
  }

  let activeTurnSender = null;
  let activeTurnTextSpan = null;
  let lastChunkTimestamp = 0;

  function updateStatus(text, type) {
    if (!statusBadge) return;
    statusBadge.textContent = text;
    statusBadge.className = `badge ${type || ""}`;
  }

  function handleServerJson(msg) {
    switch (msg.type) {
      case "SESSION_STARTED":
        if (msg.session_id) {
          sessionStorage.setItem("sb_pos_session_id", msg.session_id);
        }
        if (msg.cart) {
          renderCart(msg.cart);
        }
        break;

      case "LIVE_READY":
        updateStatus("Agent Ready", "ok");
        break;

      case "CART_UPDATED":
        renderCart(msg.cart);
        break;

      case "TRANSCRIPT_CHUNK":
        handleTranscript(msg.sender, msg.text);
        break;

      case "TURN_COMPLETE":
        activeTurnSender = null;
        activeTurnTextSpan = null;
        if (transcriptIndicator) {
          transcriptIndicator.textContent = "Listening...";
        }
        break;

      case "INTERRUPTED":
        // Gemini server detected user speech (barge-in); cut off current speech playback immediately
        stopAllAudioPlayback();
        activeTurnSender = null;
        activeTurnTextSpan = null;
        if (transcriptIndicator) {
          transcriptIndicator.textContent = "Listening (Barge-in)...";
        }
        break;

      case "USAGE_UPDATE":
        if (tokenUsageBadge && msg.tokens) {
          const total = msg.tokens.total || 0;
          const prompt = msg.tokens.prompt || 0;
          const resp = msg.tokens.response || 0;
          tokenUsageBadge.textContent = `Tokens: ${total.toLocaleString()}`;
          tokenUsageBadge.title = `Total: ${total} | Input: ${prompt} | Output: ${resp}`;
        }
        break;

      case "TOOL_ERROR":
        createTranscriptMessage("System", `Error: ${msg.error}`, "system-msg");
        break;

      case "ERROR":
        updateStatus("Error", "danger");
        createTranscriptMessage("System", msg.message || "Unknown error", "system-msg");
        break;
    }
  }

  function handleTranscript(sender, text) {
    if (!text || !text.trim()) return;
    const isUser = sender === "user";
    const senderLabel = isUser ? "Dad" : "Staff";
    const cls = isUser ? "user" : "assistant";
    const now = Date.now();

    if (transcriptIndicator) {
      transcriptIndicator.textContent = isUser ? "Listening..." : "Speaking...";
    }

    // Append to existing active turn bubble if same sender arrived within 3000ms
    if (activeTurnSender === sender && activeTurnTextSpan && (now - lastChunkTimestamp < 3000)) {
      const current = activeTurnTextSpan.textContent;
      const cleanText = text.trim();
      if (!current) {
        activeTurnTextSpan.textContent = cleanText;
      } else if (/[\s\n]$/.test(current) || /^[.,!?:;]/.test(cleanText)) {
        activeTurnTextSpan.textContent += cleanText;
      } else {
        activeTurnTextSpan.textContent += " " + cleanText;
      }
      lastChunkTimestamp = now;
      if (transcriptLog) {
        transcriptLog.scrollTop = transcriptLog.scrollHeight;
      }
    } else {
      // Start a new turn bubble
      createTranscriptMessage(senderLabel, text.trim(), cls);
      activeTurnSender = sender;
      lastChunkTimestamp = now;
    }
  }

  function createTranscriptMessage(sender, text, cls) {
    if (!transcriptLog) return;
    const msgDiv = document.createElement("div");
    msgDiv.className = `transcript-msg ${cls}`;

    const senderSpan = document.createElement("span");
    senderSpan.className = "sender";
    senderSpan.textContent = sender;

    const textSpan = document.createElement("span");
    textSpan.className = "text";
    textSpan.textContent = text;

    msgDiv.appendChild(senderSpan);
    msgDiv.appendChild(textSpan);
    transcriptLog.appendChild(msgDiv);
    transcriptLog.scrollTop = transcriptLog.scrollHeight;

    if (cls === "user" || cls === "assistant") {
      activeTurnTextSpan = textSpan;
    } else {
      activeTurnSender = null;
      activeTurnTextSpan = null;
    }
  }

  function renderCart(cart) {
    if (!cartTableBody || !cart) return;

    const items = cart.items || [];
    const subtotal = cart.subtotal || 0;

    if (cartTotalDisplay) {
      cartTotalDisplay.textContent = `₹${subtotal.toFixed(2)}`;
    }
    if (itemCountLabel) {
      itemCountLabel.textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;
    }

    if (items.length === 0) {
      cartTableBody.innerHTML = `
        <tr class="empty-row" id="emptyCartRow">
          <td colspan="6" style="text-align: center; color: var(--muted); padding: 32px;">
            Cart is empty. Speak an item (e.g. <em>"2 rakhi 20 wali"</em>) to start.
          </td>
        </tr>
      `;
      knownLineIds.clear();
      return;
    }

    cartTableBody.innerHTML = "";
    items.forEach((item) => {
      const tr = document.createElement("tr");
      const isNew = !knownLineIds.has(item.line_id);
      if (isNew) {
        tr.className = "line-highlight";
        knownLineIds.add(item.line_id);
      }

      tr.innerHTML = `
        <td style="font-weight: 600; color: var(--muted);">${item.line_id}</td>
        <td><strong>${escapeHtml(item.name)}</strong></td>
        <td style="text-align: center;">${item.quantity}</td>
        <td style="text-align: right; color: var(--muted);">${item.mrp !== null ? `₹${item.mrp.toFixed(2)}` : "—"}</td>
        <td style="text-align: right; font-weight: 500;">₹${(item.rate || 0).toFixed(2)}</td>
        <td style="text-align: right; font-weight: 700; color: #0f172a;">₹${item.amount.toFixed(2)}</td>
      `;
      cartTableBody.appendChild(tr);
    });
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // --- Audio Recording (Full-Duplex 16kHz PCM mono) ---
  async function ensureMicInitialized() {
    if (micStream && micAudioContext) return true;

    try {
      // Allow mic context to run at default hardware sample rate; we downsample cleanly to 16kHz in JS
      micAudioContext = new (window.AudioContext || window.webkitAudioContext)();
      if (micAudioContext.state === "suspended") {
        await micAudioContext.resume();
      }

      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      micSource = micAudioContext.createMediaStreamSource(micStream);
      // Buffer size 2048 samples
      processorNode = micAudioContext.createScriptProcessor(2048, 1, 1);

      processorNode.onaudioprocess = (e) => {
        // Gate: Must be actively transmitting (Continuous mode or Space held)
        if (!isActivelyTransmitting) return;

        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        const inputData = e.inputBuffer.getChannelData(0);

        // Compute RMS energy of this audio buffer
        let sum = 0;
        for (let i = 0; i < inputData.length; i++) {
          sum += inputData[i] * inputData[i];
        }
        const rms = Math.sqrt(sum / inputData.length);

        // 1. Echo / False Barge-in suppression:
        // While Gemini is speaking, only transmit if Dad is deliberately speaking above ambient sound (vocal barge-in)
        if (isGeminiSpeaking && rms < 0.025) {
          return;
        }

        // 2. Transmit clean 16kHz PCM audio chunk
        const pcmBuffer = downsampleAndConvertTo16BitPCM(inputData, micAudioContext.sampleRate, 16000);
        ws.send(pcmBuffer);
      };

      // Mute gain prevents the microphone from echoing locally through headphones
      muteGain = micAudioContext.createGain();
      muteGain.gain.value = 0.0;

      micSource.connect(processorNode);
      processorNode.connect(muteGain);
      muteGain.connect(micAudioContext.destination);

      return true;
    } catch (err) {
      console.error("Microphone initialization failed:", err);
      alert("Microphone access error: " + err.message);
      return false;
    }
  }

  /**
   * Resamples float32 input from inputSampleRate down to 16000Hz and returns 16-bit PCM ArrayBuffer.
   */
  function downsampleAndConvertTo16BitPCM(input, inputSampleRate, targetSampleRate = 16000) {
    if (inputSampleRate === targetSampleRate) {
      const output = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      return output.buffer;
    }

    const ratio = inputSampleRate / targetSampleRate;
    const newLength = Math.round(input.length / ratio);
    const output = new Int16Array(newLength);
    let offsetResult = 0;
    let offsetInput = 0;

    while (offsetResult < output.length) {
      const nextOffsetInput = Math.round((offsetResult + 1) * ratio);
      let accum = 0;
      let count = 0;
      for (let i = offsetInput; i < nextOffsetInput && i < input.length; i++) {
        accum += input[i];
        count++;
      }
      const sample = count > 0 ? accum / count : 0;
      const s = Math.max(-1, Math.min(1, sample));
      output[offsetResult] = s < 0 ? s * 0x8000 : s * 0x7fff;
      offsetResult++;
      offsetInput = nextOffsetInput;
    }
    return output.buffer;
  }

  async function startTransmitting() {
    const ready = await ensureMicInitialized();
    if (!ready) return;

    if (micAudioContext.state === "suspended") {
      await micAudioContext.resume();
    }

    // Manual barge-in: If user explicitly starts transmitting while Gemini is speaking, halt speech immediately
    if (isGeminiSpeaking) {
      stopAllAudioPlayback();
    }

    isActivelyTransmitting = true;
    updateMicVisualState();
  }

  function stopTransmitting() {
    if (isContinuous) return; // Keep streaming if in continuous mode
    isActivelyTransmitting = false;
    updateMicVisualState();
  }

  function updateMicVisualState() {
    if (!micBtn) return;
    if (isActivelyTransmitting) {
      micBtn.classList.add("active-listening");
      if (micBtnText) {
        micBtnText.textContent = isContinuous ? "Live Streaming (Click to Mute)" : "Listening... (Release Space)";
      }
      if (transcriptIndicator) {
        transcriptIndicator.textContent = "Listening...";
      }
    } else {
      micBtn.classList.remove("active-listening");
      if (micBtnText) {
        micBtnText.textContent = isContinuous ? "Mic Muted (Click to Stream)" : "Hold Space to Speak";
      }
      if (transcriptIndicator) {
        transcriptIndicator.textContent = isGeminiSpeaking ? "Speaking..." : "Idle";
      }
    }
  }

  // --- Audio Playback (High Fidelity 24kHz PCM from Gemini) ---
  function getPlaybackContext() {
    if (!playbackAudioContext) {
      // NOTE: Using native hardware sample rate (e.g., 44.1kHz or 48kHz) avoids Windows WASAPI
      // driver crackling and metallic distortion when forced to 24000Hz hardware rate.
      playbackAudioContext = new (window.AudioContext || window.webkitAudioContext)();
      scheduledPlaybackTime = playbackAudioContext.currentTime;
    }
    if (playbackAudioContext.state === "suspended") {
      playbackAudioContext.resume();
    }
    return playbackAudioContext;
  }

  function playAudioChunk(arrayBuffer) {
    if (!arrayBuffer || arrayBuffer.byteLength < 2) return;

    // Ensure byte length is even
    let safeBuffer = arrayBuffer;
    if (arrayBuffer.byteLength % 2 !== 0) {
      safeBuffer = arrayBuffer.slice(0, arrayBuffer.byteLength - 1);
    }

    const ctx = getPlaybackContext();
    const pcm16 = new Int16Array(safeBuffer);
    const float32 = new Float32Array(pcm16.length);

    for (let i = 0; i < pcm16.length; i++) {
      float32[i] = pcm16[i] / 32768.0;
    }

    // Gemini generates 24000Hz PCM. Web Audio resamples seamlessly to device rate (48000Hz) with crystal clarity.
    const audioBuffer = ctx.createBuffer(1, float32.length, 24000);
    audioBuffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    const now = ctx.currentTime;
    // Low-latency jitter smoothing (50ms)
    if (scheduledPlaybackTime < now) {
      scheduledPlaybackTime = now + 0.05;
    }

    source.start(scheduledPlaybackTime);
    scheduledPlaybackTime += audioBuffer.duration;

    isGeminiSpeaking = true;
    activeAudioSources.push(source);

    source.onended = () => {
      const idx = activeAudioSources.indexOf(source);
      if (idx !== -1) activeAudioSources.splice(idx, 1);

      if (activeAudioSources.length === 0 && ctx.currentTime >= scheduledPlaybackTime - 0.05) {
        isGeminiSpeaking = false;
        if (transcriptIndicator) {
          transcriptIndicator.textContent = isActivelyTransmitting ? "Listening..." : "Idle";
        }
      }
    };
  }

  function stopAllAudioPlayback() {
    currentPlaybackEpoch++;
    activeAudioSources.forEach((src) => {
      try {
        src.stop(0);
        src.disconnect();
      } catch (e) {}
    });
    activeAudioSources = [];
    isGeminiSpeaking = false;
    if (playbackAudioContext) {
      scheduledPlaybackTime = playbackAudioContext.currentTime;
    }
  }

  // --- Keyboard & Click Controls ---

  // Spacebar Push-To-Talk / Instant Barge-in
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.repeat && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      if (isContinuous) {
        // In continuous mode, pressing space acts as manual barge-in cutoff
        if (isGeminiSpeaking) {
          stopAllAudioPlayback();
        }
      } else {
        e.preventDefault();
        startTransmitting();
      }
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.code === "Space" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      if (!isContinuous) {
        e.preventDefault();
        stopTransmitting();
      }
    }
  });

  // Mic Button Click
  if (micBtn) {
    micBtn.addEventListener("click", async () => {
      if (isContinuous) {
        if (isActivelyTransmitting) {
          isActivelyTransmitting = false;
        } else {
          isActivelyTransmitting = true;
          await ensureMicInitialized();
        }
        updateMicVisualState();
      } else {
        if (isActivelyTransmitting) {
          stopTransmitting();
        } else {
          await startTransmitting();
        }
      }
    });
  }

  // Continuous Mic Mode Checkbox (Hands-Free / Earphones Mode)
  if (continuousCheck) {
    continuousCheck.addEventListener("change", async (e) => {
      isContinuous = e.target.checked;
      if (isContinuous) {
        const ready = await ensureMicInitialized();
        if (ready) {
          isActivelyTransmitting = true;
        } else {
          continuousCheck.checked = false;
          isContinuous = false;
        }
      } else {
        isActivelyTransmitting = false;
      }
      updateMicVisualState();
    });
  }

  // Voice Selector change handler
  if (voiceSelect) {
    const savedVoice = localStorage.getItem("sb_live_voice");
    if (savedVoice) {
      voiceSelect.value = savedVoice;
    }
    voiceSelect.addEventListener("change", () => {
      localStorage.setItem("sb_live_voice", voiceSelect.value);
      initWebSocket();
    });
  }

  // Clear Cart Button
  if (clearCartBtn) {
    clearCartBtn.addEventListener("click", () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "CLEAR_CART" }));
      }
    });
  }

  // 15-second Keep-Alive Heartbeat (prevents broadband router/firewall silent timeout during pauses between customers)
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "PING" }));
    }
  }, 15000);

  // Resume Web Audio Contexts and re-verify socket on tab switch / window unlock
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      if (playbackAudioContext && playbackAudioContext.state === "suspended") {
        playbackAudioContext.resume();
      }
      if (micAudioContext && micAudioContext.state === "suspended") {
        micAudioContext.resume();
      }
      if (!ws || ws.readyState === WebSocket.CLOSED) {
        initWebSocket();
      }
    }
  });

  // Auto-connect on page load
  document.addEventListener("DOMContentLoaded", initWebSocket);
})();
