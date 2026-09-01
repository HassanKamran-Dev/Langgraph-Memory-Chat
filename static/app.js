(function () {
  const chatMessages = document.getElementById("chat-messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const typingIndicator = document.getElementById("typing-indicator");

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

  function scrollToBottom() {
    setTimeout(() => {
      window.scrollTo({
        top: document.body.scrollHeight,
        behavior: "smooth"
      });
    }, 50);
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
    scrollToBottom();
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
    scrollToBottom();
  }

  chatForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;

    chatInput.value = "";
    chatInput.style.height = "auto";
    appendUserMessage(text);

    sendBtn.disabled = true;
    if (typingIndicator) typingIndicator.classList.remove("hidden");
    scrollToBottom();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          thread_id: threadId
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${res.status}`);
      }

      const data = await res.json();
      appendAssistantMessage(data.response || "No response received.");

    } catch (err) {
      appendAssistantMessage(`⚠️ Error: ${err.message}`);
    } finally {
      sendBtn.disabled = false;
      if (typingIndicator) typingIndicator.classList.add("hidden");
      scrollToBottom();
      chatInput.focus();
    }
  });
})();
