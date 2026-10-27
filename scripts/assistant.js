
document.addEventListener("DOMContentLoaded", () => {
  // Chat elements
  const form = document.getElementById("ai-chat-form");
  const input = document.getElementById("ai-chat-input");
  const messages = document.getElementById("ai-chat-messages");
  const sendButton = document.getElementById("ai-chat-send");
  const status = document.getElementById("ai-chat-status");

  // Floating assistant elements
  const assistantPanel = document.getElementById("ai-assistant-panel");
  const assistantToggle = document.getElementById("ai-assistant-toggle");

  // Initialize the floating panel
  if (assistantPanel && assistantToggle) {
    assistantPanel.classList.remove("is-open");
    assistantPanel.setAttribute("aria-hidden", "true");

    assistantToggle.setAttribute("aria-expanded", "false");
    assistantToggle.setAttribute(
      "aria-label",
      "Open ForestScope AI Assistant"
    );

    assistantToggle.title = "ForestScope AI Assistant";

    // Open or close the assistant
    assistantToggle.addEventListener("click", () => {
      const isOpen = assistantPanel.classList.toggle("is-open");

      assistantToggle.setAttribute("aria-expanded", String(isOpen));
      assistantToggle.setAttribute(
        "aria-label",
        isOpen
          ? "Close ForestScope AI Assistant"
          : "Open ForestScope AI Assistant"
      );

      assistantToggle.title = isOpen
        ? "Close AI Assistant"
        : "ForestScope AI Assistant";

      assistantPanel.setAttribute("aria-hidden", String(!isOpen));

      if (isOpen && input) {
        input.focus();
      }
    });
  }

  // Stop if the chat elements are missing
  if (!form || !input || !messages || !sendButton || !status) {
    console.error("ForestScope AI Assistant: Required chat elements not found.");
    return;
  }

  // Add a message to the chat window
  function addMessage(text, className) {
    const message = document.createElement("p");
    message.className = className;
    message.textContent = text;

    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;

    return message;
  }

  // Handle question submission
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const question = input.value.trim();

    if (!question) {
      return;
    }

    // Display the user's question
    addMessage(
      `You: ${question}`,
      "ai-message ai-message-user"
    );

    input.value = "";
    sendButton.disabled = true;
    status.textContent = "Thinking…";

    // Display a temporary assistant response
    const answerMessage = addMessage(
      "ForestScope AI: Thinking…",
      "ai-message ai-message-assistant"
    );

    try {
      const response = await fetch("/api/assistant", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          message: question
        })
      });

      // Read the server response
      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.error || `Request failed (${response.status}).`
        );
      }

      // Display the assistant's answer
      answerMessage.textContent =
        `ForestScope AI: ${data.answer}`;

      status.textContent = "Answer ready.";
    } catch (error) {
      // Display an error if the request fails
      answerMessage.textContent =
        `ForestScope AI: ${
          error.message || "Could not reach the assistant."
        }`;

      status.textContent = "Assistant request failed.";

      console.error("ForestScope AI error:", error);
    } finally {
      // Re-enable the send button
      sendButton.disabled = false;

      // Return focus to the input if the panel is open
      if (
        assistantPanel &&
        assistantPanel.classList.contains("is-open")
      ) {
        input.focus();
      }
    }
  });
});
