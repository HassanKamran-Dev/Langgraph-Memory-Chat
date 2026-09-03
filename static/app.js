(function () {
  // DOM Elements
  const sidebar = document.getElementById("sidebar");
  const sidebarBackdrop = document.getElementById("sidebar-backdrop");
  const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");
  const collapseSidebarBtn = document.getElementById("collapse-sidebar-btn");
  const closeSidebarBtn = document.getElementById("close-sidebar-btn");
  const newChatBtn = document.getElementById("new-chat-btn");
  const headerNewChatBtn = document.getElementById("header-new-chat-btn");
  const recentChatsList = document.getElementById("recent-chats-list");
  const chatsCount = document.getElementById("chats-count");
  const activeChatTitle = document.getElementById("active-chat-title");

  const chatMessagesContainer = document.getElementById("chat-messages-container");
  const chatMessages = document.getElementById("chat-messages");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const sendBtnIcon = sendBtn ? sendBtn.querySelector(".material-symbols-outlined") : null;
  const typingIndicator = document.getElementById("typing-indicator");

  // Storage Keys
  const STORAGE_KEY = "pure_conversation_chats_v1";
  const SIDEBAR_STATE_KEY = "pure_conversation_sidebar_collapsed";

  // Application State
  let state = loadState();
  let currentAbortController = null;
  let isStreaming = false;
  let userScrolledUp = false;
  let scrollRafId = null;

  // Initialize Desktop Sidebar Collapse State
  const isDesktopCollapsed = localStorage.getItem(SIDEBAR_STATE_KEY) === "true";
  if (isDesktopCollapsed && window.innerWidth >= 768) {
    sidebar.classList.add("collapsed");
  }

  // Track scroll position inside message container
  chatMessagesContainer.addEventListener("scroll", function () {
    const threshold = 100;
    const isAtBottom =
      chatMessagesContainer.scrollHeight - chatMessagesContainer.scrollTop - chatMessagesContainer.clientHeight <= threshold;
    if (isStreaming) {
      userScrolledUp = !isAtBottom;
    }
  }, { passive: true });

  // Auto-resize chat textarea
  chatInput.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 150) + "px";
  });

  // Enter to send (Shift+Enter for newline)
  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event("submit"));
    }
  });

  // Global Keyboard Shortcuts
  window.addEventListener("keydown", function (e) {
    // Ctrl+N or Cmd+N to start New Chat
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n") {
      e.preventDefault();
      createNewChat();
    }
    // Escape to close mobile sidebar
    if (e.key === "Escape") {
      closeMobileSidebar();
    }
  });

  // --- Sidebar Mobile / Desktop Toggle Actions ---
  function openMobileSidebar() {
    sidebar.classList.remove("-translate-x-full");
    sidebar.classList.add("translate-x-0");
    sidebarBackdrop.classList.remove("hidden");
  }

  function closeMobileSidebar() {
    sidebar.classList.add("-translate-x-full");
    sidebar.classList.remove("translate-x-0");
    sidebarBackdrop.classList.add("hidden");
  }

  function toggleSidebar() {
    if (window.innerWidth < 768) {
      if (sidebar.classList.contains("translate-x-0")) {
        closeMobileSidebar();
      } else {
        openMobileSidebar();
      }
    } else {
      sidebar.classList.toggle("collapsed");
      const isCollapsed = sidebar.classList.contains("collapsed");
      localStorage.setItem(SIDEBAR_STATE_KEY, isCollapsed ? "true" : "false");
    }
  }

  if (toggleSidebarBtn) toggleSidebarBtn.addEventListener("click", toggleSidebar);
  if (collapseSidebarBtn) collapseSidebarBtn.addEventListener("click", toggleSidebar);
  if (closeSidebarBtn) closeSidebarBtn.addEventListener("click", closeMobileSidebar);
  if (sidebarBackdrop) sidebarBackdrop.addEventListener("click", closeMobileSidebar);

  // --- State Persistence & Management ---
  function loadState() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed && Array.isArray(parsed.chats)) {
          if (!parsed.activeChatId && parsed.chats.length > 0) {
            parsed.activeChatId = parsed.chats[0].id;
          } else if (!parsed.activeChatId) {
            parsed.activeChatId = generateThreadId();
          }
          return parsed;
        }
      }
    } catch (e) {
      console.error("Failed to parse stored chat state", e);
    }

    // Default state
    const initialThreadId = localStorage.getItem("pure_conversation_thread_id") || generateThreadId();
    return {
      activeChatId: initialThreadId,
      chats: []
    };
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      localStorage.setItem("pure_conversation_thread_id", state.activeChatId);
    } catch (e) {
      console.error("Failed to save chat state", e);
    }
  }

  function generateThreadId() {
    return "thread_" + Date.now() + "_" + Math.random().toString(36).substring(2, 8);
  }

  function getActiveChat() {
    return state.chats.find(function (c) {
      return c.id === state.activeChatId;
    }) || null;
  }

  // --- Scrolling ---
  function scrollToBottom(force = false) {
    if (userScrolledUp && !force) return;
    if (scrollRafId) return;

    scrollRafId = requestAnimationFrame(function () {
      chatMessagesContainer.scrollTo({
        top: chatMessagesContainer.scrollHeight,
        behavior: force ? "smooth" : "auto"
      });
      scrollRafId = null;
    });
  }

  // --- HTML & Markdown Helpers ---
  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatResponse(text) {
    if (!text) return "";
    let formatted = escapeHtml(text);

    // Code blocks: ```lang\ncode```
    formatted = formatted.replace(/```([a-zA-Z0-9_\-#+]*)?\n?([\s\S]*?)```/g, function (match, lang, code) {
      const languageBadge = lang ? `<span class="text-[11px] font-code-md text-on-surface-variant/70 uppercase">${lang}</span>` : "";
      return `<div class="bg-surface-variant/50 rounded-2xl p-4 overflow-x-auto my-2.5 border border-surface-dim/70">
        ${languageBadge}
        <pre class="font-code-md text-code-md text-on-surface m-0 leading-relaxed mt-1"><code>${code.trim()}</code></pre>
      </div>`;
    });

    // Inline code: `code`
    formatted = formatted.replace(/`([^`]+)`/g, `<code class="bg-surface-variant/80 px-1.5 py-0.5 rounded font-code-md text-[13px] text-tertiary-container">$1</code>`);

    // Bold: **text**
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, `<strong>$1</strong>`);

    // Lists
    formatted = formatted.replace(/^\s*[-*]\s+(.*$)/gim, `<li class="ml-4 list-disc">$1</li>`);

    // Line breaks
    formatted = formatted.replace(/\n/g, "<br/>");

    return formatted;
  }

  // --- DOM Rendering Methods ---
  function renderWelcomeMessage() {
    chatMessages.innerHTML = `
      <div class="flex w-full fade-in-up" style="animation-delay: 0.05s;">
        <div class="flex max-w-[85%] md:max-w-[75%] bg-surface-container-low text-on-surface px-5 md:px-7 py-4 md:py-5 rounded-[28px] rounded-tl-sm shadow-[0_8px_24px_rgba(139,121,105,0.06)] border-none">
          <p class="font-body-md text-body-md leading-relaxed">Hello. How can I assist you today? I'm designed to be fast, clear, and out of your way.</p>
        </div>
      </div>
    `;
  }

  function appendUserMessageDom(text) {
    const div = document.createElement("div");
    div.className = "flex w-full justify-end fade-in-up";
    div.innerHTML = `
      <div class="flex max-w-[85%] md:max-w-[75%] bg-primary text-on-primary px-5 md:px-7 py-4 md:py-5 rounded-[28px] rounded-tr-sm shadow-[0_8px_24px_rgba(224,122,95,0.2)]">
        <p class="font-body-md text-body-md leading-relaxed whitespace-pre-wrap break-words">${escapeHtml(text)}</p>
      </div>
    `;
    chatMessages.appendChild(div);
  }

  function appendAssistantMessageDom(text, reasoning) {
    const div = document.createElement("div");
    div.className = "flex w-full fade-in-up";

    let reasoningHtml = "";
    if (reasoning && reasoning.trim()) {
      reasoningHtml = `
        <div class="reasoning-container">
          <details class="bg-surface-variant/40 rounded-2xl p-3 border border-surface-dim/60 mb-2 transition-all">
            <summary class="cursor-pointer text-[13px] font-medium text-tertiary select-none flex items-center gap-1.5 outline-none">
              <span class="material-symbols-outlined text-[16px]">psychology</span>
              <span>Thought Process</span>
            </summary>
            <div class="reasoning-content mt-2 text-[12px] font-code-md text-on-surface-variant/90 leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto border-t border-surface-dim/40 pt-2">${escapeHtml(reasoning)}</div>
          </details>
        </div>
      `;
    }

    div.innerHTML = `
      <div class="flex flex-col gap-2 max-w-[85%] md:max-w-[75%] bg-surface-container-low text-on-surface px-5 md:px-7 py-4 md:py-5 rounded-[28px] rounded-tl-sm shadow-[0_8px_24px_rgba(139,121,105,0.06)] border-none">
        ${reasoningHtml}
        <div class="message-content font-body-md text-body-md leading-relaxed">${formatResponse(text)}</div>
      </div>
    `;
    chatMessages.appendChild(div);
  }

  function createStreamingAssistantMessageElement() {
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

    let targetText = "";
    let displayedText = "";
    let targetReasoning = "";
    let displayedReasoning = "";
    let animFrameId = null;
    let isStreamDone = false;
    let hasFinalizedReasoning = false;

    function renderLoop() {
      let updated = false;

      // Smoothly render reasoning text
      if (displayedReasoning.length < targetReasoning.length) {
        reasoningContainer.classList.remove("hidden");
        const step = Math.max(1, Math.ceil((targetReasoning.length - displayedReasoning.length) / 3));
        displayedReasoning = targetReasoning.slice(0, displayedReasoning.length + step);
        reasoningContent.textContent = displayedReasoning;
        reasoningContent.scrollTop = reasoningContent.scrollHeight;
        updated = true;
      }

      // Smoothly render message text
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
      appendReasoning: function (chunk) {
        targetReasoning += chunk;
        scheduleRender();
      },
      appendText: function (chunk) {
        targetText += chunk;
        scheduleRender();
      },
      getFinalText: function () {
        return targetText;
      },
      getFinalReasoning: function () {
        return targetReasoning;
      },
      finalize: function () {
        isStreamDone = true;
        if (!animFrameId) {
          contentEl.classList.remove("streaming-cursor");
          finalizeReasoningUi();
          scrollToBottom(true);
        }
      },
      appendError: function (errorMsg) {
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

  // --- Render Active Chat Messages Canvas ---
  function renderActiveChatMessages() {
    chatMessages.innerHTML = "";
    const activeChat = getActiveChat();

    if (!activeChat || !activeChat.messages || activeChat.messages.length === 0) {
      renderWelcomeMessage();
      if (activeChatTitle) activeChatTitle.textContent = "New Chat";
    } else {
      if (activeChatTitle) activeChatTitle.textContent = activeChat.title || "Chat Bot";
      activeChat.messages.forEach(function (msg) {
        if (msg.role === "user") {
          appendUserMessageDom(msg.content);
        } else if (msg.role === "assistant") {
          appendAssistantMessageDom(msg.content, msg.reasoning);
        }
      });
    }

    scrollToBottom(true);
  }

  // --- Render Recent Chats Sidebar List ---
  function renderRecentChats() {
    recentChatsList.innerHTML = "";
    chatsCount.textContent = state.chats.length;

    if (state.chats.length === 0) {
      recentChatsList.innerHTML = `
        <div class="py-10 px-3 text-center text-on-surface-variant/60 text-[13px] flex flex-col items-center gap-2.5">
          <span class="material-symbols-outlined text-[30px] opacity-40">forum</span>
          <span>No recent chats yet</span>
        </div>
      `;
      return;
    }

    state.chats.forEach(function (chat) {
      const isActive = chat.id === state.activeChatId;
      const item = document.createElement("div");
      item.className = `chat-item group relative flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all duration-150 text-on-surface hover:bg-surface-variant/70 ${isActive ? "active" : ""}`;
      item.dataset.chatId = chat.id;

      const titleText = escapeHtml(chat.title || "New Chat");

      item.innerHTML = `
        <div class="flex items-center gap-2.5 min-w-0 flex-1">
          <span class="material-symbols-outlined text-[18px] text-on-surface-variant/80 shrink-0 group-hover:text-primary transition-colors">
            ${isActive ? "chat" : "chat_bubble_outline"}
          </span>
          <span class="chat-item-title text-[13px] truncate text-on-surface" title="${titleText}">
            ${titleText}
          </span>
        </div>
        <button class="delete-chat-btn opacity-0 group-hover:opacity-100 p-1 rounded-lg text-on-surface-variant hover:text-error hover:bg-error-container/50 transition-all shrink-0 ml-1" title="Delete chat">
          <span class="material-symbols-outlined text-[16px]">delete</span>
        </button>
      `;

      // Switch to this chat when clicked
      item.addEventListener("click", function (e) {
        if (e.target.closest(".delete-chat-btn")) return;
        switchChat(chat.id);
      });

      // Delete this chat
      const delBtn = item.querySelector(".delete-chat-btn");
      if (delBtn) {
        delBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          deleteChat(chat.id);
        });
      }

      recentChatsList.appendChild(item);
    });
  }

  // --- Chat Actions ---
  function createNewChat() {
    // If generation is active, stop it
    if (isStreaming && currentAbortController) {
      currentAbortController.abort();
      setStreamingState(false);
    }

    const currentChat = getActiveChat();
    // If currently on an empty chat, just focus input
    if (currentChat && (!currentChat.messages || currentChat.messages.length === 0)) {
      chatInput.focus();
      closeMobileSidebar();
      return;
    }

    const newId = generateThreadId();
    state.activeChatId = newId;
    saveState();

    renderActiveChatMessages();
    renderRecentChats();

    chatInput.value = "";
    chatInput.style.height = "auto";
    chatInput.focus();
    closeMobileSidebar();
  }

  function switchChat(chatId) {
    if (chatId === state.activeChatId) {
      closeMobileSidebar();
      return;
    }

    if (isStreaming && currentAbortController) {
      currentAbortController.abort();
      setStreamingState(false);
    }

    state.activeChatId = chatId;
    saveState();

    renderActiveChatMessages();
    renderRecentChats();

    closeMobileSidebar();
    chatInput.focus();
  }

  function deleteChat(chatId) {
    const index = state.chats.findIndex(function (c) {
      return c.id === chatId;
    });
    if (index === -1) return;

    state.chats.splice(index, 1);

    if (state.activeChatId === chatId) {
      if (state.chats.length > 0) {
        state.activeChatId = state.chats[0].id;
        saveState();
        renderActiveChatMessages();
      } else {
        createNewChat();
        return;
      }
    } else {
      saveState();
    }

    renderRecentChats();
  }

  if (newChatBtn) newChatBtn.addEventListener("click", createNewChat);
  if (headerNewChatBtn) headerNewChatBtn.addEventListener("click", createNewChat);

  // --- Streaming State Handler ---
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

  // --- Message Submit & Streaming Handler ---
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

    // Ensure active chat session exists in state.chats
    let activeChat = getActiveChat();
    if (!activeChat) {
      const generatedTitle = text.length > 35 ? text.substring(0, 35).trim() + "..." : text;
      activeChat = {
        id: state.activeChatId,
        title: generatedTitle,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messages: []
      };
      state.chats.unshift(activeChat);
    } else {
      // If it had no messages yet or default title, update title
      if (!activeChat.messages || activeChat.messages.length === 0) {
        activeChat.title = text.length > 35 ? text.substring(0, 35).trim() + "..." : text;
      }
      activeChat.updatedAt = Date.now();
      // Bring active chat to the top of history
      const idx = state.chats.indexOf(activeChat);
      if (idx > 0) {
        state.chats.splice(idx, 1);
        state.chats.unshift(activeChat);
      }
    }

    // Save user message to active chat
    activeChat.messages.push({
      role: "user",
      content: text
    });
    saveState();
    renderRecentChats();
    if (activeChatTitle) activeChatTitle.textContent = activeChat.title;

    // Render user message to DOM
    appendUserMessageDom(text);

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
          thread_id: state.activeChatId
        }),
        signal: currentAbortController.signal
      });

      if (!res.ok) {
        const err = await res.json().catch(function () { return {}; });
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
        buffer = parts.pop(); // keep remainder

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
                assistantMsgObj = createStreamingAssistantMessageElement();
              }
              assistantMsgObj.appendReasoning(data.content);
            } else if (data.type === "token") {
              if (!assistantMsgObj) {
                if (typingIndicator) typingIndicator.classList.add("hidden");
                assistantMsgObj = createStreamingAssistantMessageElement();
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
                appendAssistantMessageDom(`⚠️ Error: ${data.message}`);
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

      // Persist assistant message in active chat
      if (assistantMsgObj && activeChat) {
        const finalText = assistantMsgObj.getFinalText();
        const finalReasoning = assistantMsgObj.getFinalReasoning();
        if (finalText || finalReasoning) {
          activeChat.messages.push({
            role: "assistant",
            content: finalText,
            reasoning: finalReasoning
          });
          activeChat.updatedAt = Date.now();
          saveState();
          renderRecentChats();
        }
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

          // Still persist whatever was streamed so far
          if (activeChat) {
            const partialText = assistantMsgObj.getFinalText();
            const partialReasoning = assistantMsgObj.getFinalReasoning();
            if (partialText || partialReasoning) {
              activeChat.messages.push({
                role: "assistant",
                content: partialText + " *(stopped)*",
                reasoning: partialReasoning
              });
              activeChat.updatedAt = Date.now();
              saveState();
              renderRecentChats();
            }
          }
        }
      } else {
        if (assistantMsgObj) {
          assistantMsgObj.appendError(err.message);
        } else {
          appendAssistantMessageDom(`⚠️ Error: ${err.message}`);
        }
      }
    } finally {
      setStreamingState(false);
      if (typingIndicator) typingIndicator.classList.add("hidden");
      scrollToBottom(true);
      chatInput.focus();
    }
  });

  // Initial Render on Page Load
  renderActiveChatMessages();
  renderRecentChats();
})();
