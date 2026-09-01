(function () {
  const chatMessages = document.getElementById("chat-messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const sendBtnIcon = sendBtn ? sendBtn.querySelector(".material-symbols-outlined") : null;
  const typingIndicator = document.getElementById("typing-indicator");

  let currentAbortController = null;
  let isStreaming = false;
  let userScrolledUp = false;

  // Track if user manually scrolled up
  window.addEventListener("scroll", function () {
    const threshold = 120;
    const scrollPosition = window.innerHeight + window.scrollY;
    const isAtBottom = scrollPosition >= document.documentElement.scrollHeight - threshold;
    if (isStreaming) {
      userScrolledUp = !isAtBottom;
    }
  }, { passive: true });

  // Thread ID for LangGraph memory persistence
  let threadId = localStorage.getItem("pure_conversation_thread_id");
  if (!threadId) {
    threadId = "thread_" + Math.random().toString(36).substring(2, 10);
    localStorage.setItem("pure_conversation_thread_id", threadId);
  }

  // Auto-resize input
  chatInput.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 150) + "px";
  });

  // Enter to send
  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event("submit"));
    }
  });

  let scrollRafId = null;
  function scrollToBottom(force = false) {
    if (userScrolledUp && !force) return;
    if (scrollRafId) return;

    scrollRafId = requestAnimationFrame(() => {
      window.scrollTo({
        top: document.documentElement.scrollHeight,
        behavior: force ? "smooth" : "auto"
      });
      scrollRafId = null;
    });
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatResponse(text) {
    if (!text) return "";
    let formatted = escapeHtml(text);

    // Code blocks: ```code```
    formatted = formatted.replace(/```([a-zA-Z0-9_\-#+]*)?\n?([\s\S]*?)```/g, function (match, lang, code) {
      return `<div class="bg-surface-variant/50 rounded-2xl p-4 overflow-x-auto my-2 border border-surface-dim"><pre class="font-code-md text-code-md text-on-surface-variant m-0 leading-relaxed"><code>${code.trim()}</code></pre></div>`;
    });

    // Inline code: `code`
    formatted = formatted.replace(/`([^`]+)`/g, `<code class="bg-surface-variant/80 px-1.5 py-0.5 rounded font-code-md text-[13px] text-tertiary-container">$1</code>`);

    // Bold
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, `<strong>$1</strong>`);

    // Lists
    formatted = formatted.replace(/^\s*[-*]\s+(.*$)/gim, `<li class="ml-4 list-disc">$1</li>`);

    // Line breaks
    formatted = formatted.replace(/\n/g, "<br/>");

    return formatted;
  }

  function appendUserMessage(text) {
    const div = document.createElement("div");
    div.className = "flex w-full justify-end fade-in-up";
    div.innerHTML = `
      <div class="flex max-w-[85%] md:max-w-[75%] bg-primary text-on-primary px-5 md:px-7 py-4 md:py-5 rounded-[28px] rounded-tr-sm shadow-[0_8px_24px_rgba(224,122,95,0.2)]">
        <p class="font-body-md text-body-md leading-relaxed whitespace-pre-wrap break-words">${escapeHtml(text)}</p>
      </div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom(true);
  }

  function createAssistantMessageElement() {
    const div = document.createElement("div");
    div.className = "flex w-full fade-in-up";
    div.innerHTML = `
      <div class="flex flex-col gap-2 max-w-[85%] md:max-w-[75%] bg-surface-container-low text-on-surface px-5 md:px-7 py-4 md:py-5 rounded-[28px] rounded-tl-sm shadow-[0_8px_24px_rgba(139,121,105,0.06)] border-none">
        <div class="reasoning-container hidden">
          <details class="bg-surface-variant/40 rounded-2xl p-3 border border-surface-dim/60 mb-2 transition-all" open>
            <summary class="cursor-pointer text-[13px] font-medium text-tertiary select-none flex items-center gap-1.5 outline-none">
              <span class="material-symbols-outlined text-[16px] animate-spin">progress_activity</span>
              <span class="reasoning-label">Thinking...</span>
            </summary>
            <div class="reasoning-content mt-2 text-[12px] font-code-md text-on-surface-variant/90 leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto border-t border-surface-dim/40 pt-2"></div>
          </details>
        </div>
        <div class="message-content font-body-md text-body-md leading-relaxed streaming-cursor"></div>
      </div>
    `;
    chatMessages.appendChild(div);

    const contentEl = div.querySelector(".message-content");
    const reasoningContainer = div.querySelector(".reasoning-container");
    const reasoningContent = div.querySelector(".reasoning-content");
    const reasoningDetails = div.querySelector("details");
    const reasoningIcon = div.querySelector("summary .material-symbols-outlined");
    const reasoningLabel = div.querySelector(".reasoning-label");

    // Smooth token streaming buffer queue
    let targetText = "";
    let displayedText = "";
    let targetReasoning = "";
    let displayedReasoning = "";
    let animFrameId = null;
    let isStreamDone = false;
    let hasFinalizedReasoning = false;

    function renderLoop() {
      let updated = false;

      // Smoothly update reasoning text
      if (displayedReasoning.length < targetReasoning.length) {
        reasoningContainer.classList.remove("hidden");
        const step = Math.max(1, Math.ceil((targetReasoning.length - displayedReasoning.length) / 3));
        displayedReasoning = targetReasoning.slice(0, displayedReasoning.length + step);
        reasoningContent.textContent = displayedReasoning;
        reasoningContent.scrollTop = reasoningContent.scrollHeight;
        updated = true;
      }

      // Smoothly update answer content
      if (displayedText.length < targetText.length) {
        if (!hasFinalizedReasoning && targetReasoning) {
          finalizeReasoningUi();
        }
        const step = Math.max(1, Math.ceil((targetText.length - displayedText.length) / 3));
        displayedText = targetText.slice(0, displayedText.length + step);
        contentEl.innerHTML = formatResponse(displayedText);
        updated = true;
      }

      if (updated) {
        scrollToBottom();
      }

      if (displayedText.length < targetText.length || displayedReasoning.length < targetReasoning.length) {
        animFrameId = requestAnimationFrame(renderLoop);
      } else {
        animFrameId = null;
        if (isStreamDone) {
          contentEl.classList.remove("streaming-cursor");
          finalizeReasoningUi();
          scrollToBottom(true);
        }
      }
    }

    function finalizeReasoningUi() {
      hasFinalizedReasoning = true;
      if (reasoningIcon) {
        reasoningIcon.textContent = "psychology";
        reasoningIcon.classList.remove("animate-spin");
      }
      if (reasoningLabel) {
        reasoningLabel.textContent = "Thought Process";
      }
      if (reasoningDetails && reasoningDetails.hasAttribute("open")) {
        reasoningDetails.removeAttribute("open");
      }
    }

    function scheduleRender() {
      if (!animFrameId) {
        animFrameId = requestAnimationFrame(renderLoop);
      }
    }

    return {
      element: div,
      contentEl: contentEl,
      appendReasoning(chunk) {
        targetReasoning += chunk;
        scheduleRender();
      },
      appendText(chunk) {
        targetText += chunk;
        scheduleRender();
      },
      finalize() {
        isStreamDone = true;
        // Fast-forward remaining text if any
        if (!animFrameId) {
          contentEl.classList.remove("streaming-cursor");
          finalizeReasoningUi();
          scrollToBottom(true);
        }
      },
      appendError(errorMsg) {
        isStreamDone = true;
        contentEl.classList.remove("streaming-cursor");
        finalizeReasoningUi();
        const errDiv = document.createElement("div");
        errDiv.className = "mt-2 p-3 bg-error-container text-on-error-container rounded-xl text-sm font-body-sm";
        errDiv.innerHTML = `⚠️ <strong>Error:</strong> ${escapeHtml(errorMsg)}`;
        div.firstElementChild.appendChild(errDiv);
        scrollToBottom(true);
      }
    };
  }

  function appendAssistantMessage(text) {
    const div = document.createElement("div");
    div.className = "flex w-full fade-in-up";
    div.innerHTML = `
      <div class="flex flex-col gap-3 max-w-[85%] md:max-w-[75%] bg-surface-container-low text-on-surface px-5 md:px-7 py-4 md:py-5 rounded-[28px] rounded-tl-sm shadow-[0_8px_24px_rgba(139,121,105,0.06)] border-none">
        <div class="font-body-md text-body-md leading-relaxed">${formatResponse(text)}</div>
      </div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom(true);
  }

  function setStreamingState(streaming) {
    isStreaming = streaming;
    if (streaming) {
      userScrolledUp = false;
      if (sendBtnIcon) sendBtnIcon.textContent = "stop";
      sendBtn.title = "Stop generating";
      sendBtn.classList.add("bg-tertiary");
      sendBtn.classList.remove("bg-primary");
    } else {
      if (sendBtnIcon) sendBtnIcon.textContent = "send";
      sendBtn.title = "Send message";
      sendBtn.classList.remove("bg-tertiary");
      sendBtn.classList.add("bg-primary");
      currentAbortController = null;
    }
  }

  chatForm.addEventListener("submit", async function (e) {
    e.preventDefault();

    // If currently streaming, clicking button stops generation
    if (isStreaming && currentAbortController) {
      currentAbortController.abort();
      setStreamingState(false);
      return;
    }

    const text = chatInput.value.trim();
    if (!text) return;

    chatInput.value = "";
    chatInput.style.height = "auto";
    appendUserMessage(text);

    currentAbortController = new AbortController();
    setStreamingState(true);

    if (typingIndicator) typingIndicator.classList.remove("hidden");
    scrollToBottom(true);

    let assistantMsgObj = null;

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          thread_id: threadId
        }),
        signal: currentAbortController.signal
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop(); // keep last partial piece in buffer

        for (const part of parts) {
          const trimmed = part.trim();
          if (!trimmed.startsWith("data:")) continue;

          const jsonStr = trimmed.slice(5).trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);

            if (data.type === "reasoning") {
              if (!assistantMsgObj) {
                if (typingIndicator) typingIndicator.classList.add("hidden");
                assistantMsgObj = createAssistantMessageElement();
              }
              assistantMsgObj.appendReasoning(data.content);
            } else if (data.type === "token") {
              if (!assistantMsgObj) {
                if (typingIndicator) typingIndicator.classList.add("hidden");
                assistantMsgObj = createAssistantMessageElement();
              }
              assistantMsgObj.appendText(data.content);
            } else if (data.type === "done") {
              if (assistantMsgObj) {
                assistantMsgObj.finalize();
              }
            } else if (data.type === "error") {
              if (typingIndicator) typingIndicator.classList.add("hidden");
              if (assistantMsgObj) {
                assistantMsgObj.appendError(data.message);
              } else {
                appendAssistantMessage(`⚠️ Error: ${data.message}`);
              }
            }
          } catch (parseErr) {
            console.warn("Could not parse SSE JSON:", jsonStr, parseErr);
          }
        }
      }

      if (assistantMsgObj) {
        assistantMsgObj.finalize();
      }

    } catch (err) {
      if (typingIndicator) typingIndicator.classList.add("hidden");

      if (err.name === "AbortError") {
        if (assistantMsgObj) {
          assistantMsgObj.finalize();
          const stopNotice = document.createElement("span");
          stopNotice.className = "text-xs text-on-surface-variant/70 italic ml-2 block mt-1";
          stopNotice.textContent = "(Generation stopped)";
          assistantMsgObj.contentEl.appendChild(stopNotice);
        }
      } else {
        if (assistantMsgObj) {
          assistantMsgObj.appendError(err.message);
        } else {
          appendAssistantMessage(`⚠️ Error: ${err.message}`);
        }
      }
    } finally {
      setStreamingState(false);
      if (typingIndicator) typingIndicator.classList.add("hidden");
      scrollToBottom(true);
      chatInput.focus();
    }
  });
})();
