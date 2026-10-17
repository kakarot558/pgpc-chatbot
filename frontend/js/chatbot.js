// Phase 10: the chat page. Talks to POST /api/v1/chat and remembers the conversation through a session token.
// The token lives in sessionStorage, so closing the tab ends the chat. Server text is always inserted with
// textContent (never innerHTML), so nothing a user or a database record contains can run as code.
const TOKEN_KEY = "pgpc_chat_token";
const EXAMPLES = ["How do I enroll?", "What is the uniform?", "What is the vision and mission?",
                  "Who is the president of PGPC?", "What does the handbook say about attendance?",
                  "What are the clinic hours?"];
const GREETING = "Hello! I'm PGPC SmartGuide, the information assistant of Padre Garcia Polytechnic College. " +
                 "Ask me about PGPC offices, facilities, employees, the student handbook and more.";

const chatArea = document.getElementById("chatArea");
const form = document.getElementById("chatForm");
const input = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const notice = document.getElementById("notice");
const chips = document.getElementById("chips");
let busy = false;

const getToken = () => sessionStorage.getItem(TOKEN_KEY);
const setToken = (t) => (t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY));

function showNotice(text, bad = false) {
  notice.textContent = text || "";
  notice.className = "sg-notice" + (bad ? " bad" : "");
}

function scrollDown() { chatArea.scrollTop = chatArea.scrollHeight; }

// Turns the plain-text answer into readable blocks: bold headings, bullet lists, a bold "Short answer:".
// Every piece of text goes in with textContent, never innerHTML, so nothing typed or stored can inject markup.
// Links in an answer become real links. Only http(s) addresses are linked, always in a new tab, and the text of the
// link is set with textContent, so nothing typed or stored can become markup.
const URL_RE = /(https?:\/\/[^\s<>"']*[^\s<>"'.,;:!?)])/g;
function appendWithLinks(el, text) {
  String(text).split(URL_RE).forEach((part, i) => {
    if (!part) return;
    if (i % 2 === 1) {
      let ok = false;
      try { const u = new URL(part); ok = u.protocol === "https:" || u.protocol === "http:"; } catch (e) { ok = false; }
      if (ok) {
        const a = document.createElement("a");
        a.href = part;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.className = "sg-link";
        a.textContent = part;
        el.appendChild(a);
        return;
      }
    }
    el.appendChild(document.createTextNode(part));
  });
}

const HEADING_RE = /^[A-Z][A-Z0-9 ,.'&\/-]{3,}(\s*\([^)]*\))?:?$/;          // "MINOR OFFENSES (lighter violations)"
function renderBody(container, text) {
  let list = null;
  const flushList = () => { list = null; };
  String(text).split("\n").forEach((raw) => {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { flushList(); const g = document.createElement("div"); g.className = "sg-gap"; container.appendChild(g); return; }
    const bullet = /^\s*-\s+(.*)$/.exec(line);
    if (bullet) {
      if (!list) { list = document.createElement("ul"); list.className = "sg-list"; container.appendChild(list); }
      const li = document.createElement("li");
      appendWithLinks(li, bullet[1]);
      list.appendChild(li);
      return;
    }
    flushList();
    const row = document.createElement("div");
    const t = line.trim();
    if (HEADING_RE.test(t) && t.length <= 90) {
      row.className = "sg-h";
      row.textContent = t;
    } else if (/^Short answer:/.test(t)) {
      const strong = document.createElement("span");
      strong.className = "sg-strong";
      strong.textContent = "Short answer:";
      row.appendChild(strong);
      appendWithLinks(row, t.slice("Short answer:".length));
    } else if (t.length <= 90 && /:$/.test(t) && !/^\d+\./.test(t)) {
      row.className = "sg-lead";
      row.textContent = t;
    } else {
      appendWithLinks(row, t);
    }
    container.appendChild(row);
  });
}

function addBubble(role, text, extra) {
  const bubble = document.createElement("div");
  bubble.className = "sg-bubble " + (role === "user" ? "sg-user" : "sg-bot");
  let body = text, source = "";
  const cut = text.lastIndexOf("\n\nSource: ");           // the answer ends with its source line
  if (role !== "user" && cut > -1) { body = text.slice(0, cut); source = text.slice(cut + 2); }
  const p = document.createElement("div");
  p.className = "sg-text";
  if (role === "user") p.textContent = body;                 // what the student typed stays exactly as typed
  else renderBody(p, body);
  bubble.appendChild(p);
  const long = role !== "user" && body.split("\n").length > 24;
  if (long) {                                                // a long handbook answer starts folded, so the chat stays easy to scan
    p.classList.add("sg-folded");
    const more = document.createElement("button");
    more.type = "button";
    more.className = "sg-more";
    more.textContent = "Show full answer";
    more.setAttribute("aria-expanded", "false");
    more.addEventListener("click", () => {
      const open = p.classList.toggle("sg-folded") === false;
      more.textContent = open ? "Show less" : "Show full answer";
      more.setAttribute("aria-expanded", String(open));
    });
    bubble.appendChild(more);
  }
  if (extra && extra.interpreted) {
    const i = document.createElement("div");
    i.className = "sg-meta";
    i.textContent = "Understood as: " + extra.interpreted;
    bubble.appendChild(i);
  }
  if (source) {
    const s = document.createElement("div");
    s.className = "sg-source";
    s.textContent = source;
    bubble.appendChild(s);
  }
  if (role !== "user" && extra && extra.messageId && extra.rate !== false) bubble.appendChild(feedbackRow(extra.messageId));
  if (role !== "user") addCopyButton(bubble, body);
  chatArea.appendChild(bubble);
  if (role !== "user" && extra && extra.messageId) chatArea.scrollTop = Math.max(0, bubble.offsetTop - 12);   // read an answer from its top
  else scrollDown();
  return bubble;
}

function addCopyButton(bubble, text) {
  if (!navigator.clipboard || !text) return;
  let row = bubble.querySelector(".sg-feedback");
  if (!row) { row = document.createElement("div"); row.className = "sg-feedback"; bubble.appendChild(row); }
  const b = document.createElement("button");
  b.type = "button";
  b.className = "sg-fb-btn sg-copy";
  b.textContent = "Copy answer";
  b.addEventListener("click", () => {
    navigator.clipboard.writeText(text).then(() => {
      b.textContent = "Copied";
      setTimeout(() => { b.textContent = "Copy answer"; }, 1800);
    }).catch(() => {});
  });
  row.appendChild(b);
}

// Thumbs up / down under an answer. The vote goes to POST /api/v1/chat/feedback; thumbs-down also offers a reason.
function feedbackRow(messageId) {
  const row = document.createElement("div");
  row.className = "sg-feedback";
  const label = document.createElement("span");
  label.className = "sg-fb-label";
  label.textContent = "Was this helpful?";
  const up = document.createElement("button");
  const down = document.createElement("button");
  [[up, "\u{1F44D}", "Yes, helpful"], [down, "\u{1F44E}", "No, not helpful"]].forEach(([b, icon, title]) => {
    b.type = "button"; b.className = "sg-fb-btn"; b.textContent = icon; b.title = title; b.setAttribute("aria-label", title);
  });
  const thanks = document.createElement("span");
  thanks.className = "sg-fb-thanks";

  async function vote(value, comment) {
    const token = getToken();
    if (!token) return;
    try {
      const res = await fetch("/api/v1/chat/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Session-Token": token },
        body: JSON.stringify({ message_id: messageId, value, comment: comment || null }),
      });
      if (!res.ok) throw new Error("failed");
      up.disabled = down.disabled = true;
      up.classList.toggle("sg-fb-on", value === "up");
      down.classList.toggle("sg-fb-on", value === "down");
      thanks.textContent = value === "up" ? "Thank you!" : "Thank you. We will use this to improve.";
    } catch (e) {
      thanks.textContent = "Could not send your feedback. Please try again.";
    }
  }
  up.addEventListener("click", () => vote("up"));
  down.addEventListener("click", () => {
    if (row.querySelector(".sg-fb-reason")) return;
    const box = document.createElement("div");
    box.className = "sg-fb-reason";
    const text = document.createElement("input");
    text.type = "text"; text.maxLength = 500; text.placeholder = "What was wrong? (optional)";
    text.setAttribute("aria-label", "What was wrong with the answer?");
    const send = document.createElement("button");
    send.type = "button"; send.className = "sg-fb-send"; send.textContent = "Send";
    send.addEventListener("click", () => { box.remove(); vote("down", text.value.trim()); });
    text.addEventListener("keydown", (e) => { if (e.key === "Enter") send.click(); });
    box.append(text, send);
    row.appendChild(box);
    text.focus();
  });
  row.append(label, up, down, thanks);
  return row;
}

function showTyping() {
  const b = document.createElement("div");
  b.className = "sg-bubble sg-bot sg-typing";
  b.setAttribute("aria-label", "PGPC SmartGuide is typing");
  b.innerHTML = "<span></span><span></span><span></span>";    // fixed markup, no data inside
  chatArea.appendChild(b);
  scrollDown();
  return b;
}

function setBusy(on) {
  busy = on;
  sendBtn.disabled = on;
  input.disabled = on;
  if (!on) input.focus();
}

// The first screen: topics a student is likely to ask about. Every button sends a question that has an answer.
const TOPICS = [
  ["Enrollment", ["How do I enroll?", "What are the requirements for enrollment?", "What scholarships are available?"]],
  ["Rules and conduct", ["What is the uniform?", "What is the haircut policy?", "How many absences are allowed?"]],
  ["People and offices", ["Who is the president of PGPC?", "Who is the dean?", "What are the clinic hours?"]],
  ["About PGPC", ["What is the vision and mission?", "What are the core values?", "What is the library policy?"]],
];

function showWelcome() {
  const box = document.createElement("div");
  box.className = "sg-welcome";
  const h = document.createElement("h2");
  h.className = "sg-welcome-title";
  h.textContent = "What can I help you find?";
  const p = document.createElement("p");
  p.className = "sg-welcome-sub";
  p.textContent = "Ask in your own words, in English or Filipino. Answers come from the PGPC Student Handbook and school records.";
  box.appendChild(h);
  box.appendChild(p);
  TOPICS.forEach(([title, questions]) => {
    const g = document.createElement("div");
    g.className = "sg-topic";
    const t = document.createElement("div");
    t.className = "sg-topic-title";
    t.textContent = title;
    g.appendChild(t);
    questions.forEach((q) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sg-topic-btn";
      b.textContent = q;
      b.addEventListener("click", () => send(q));
      g.appendChild(b);
    });
    box.appendChild(g);
  });
  chatArea.appendChild(box);
}

function clearWelcome() {
  const w = chatArea.querySelector(".sg-welcome");
  if (w) w.remove();
}

function renderChips() {
  chips.textContent = "";
  EXAMPLES.forEach((q) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "sg-chip";
    b.textContent = q;
    b.addEventListener("click", () => send(q));
    chips.appendChild(b);
  });
}

function renderSuggestions(list) {
  // follow-up questions under the answer; each is a button that sends that question
  chips.textContent = "";
  (Array.isArray(list) ? list : []).slice(0, 3).forEach((q) => {
    if (typeof q !== "string" || !q) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "sg-chip";
    b.textContent = q;                                  // textContent only: never innerHTML
    b.addEventListener("click", () => send(q));
    chips.appendChild(b);
  });
}

async function send(message) {
  message = (message || "").trim();
  if (!message || busy) return;
  showNotice("");
  chips.textContent = "";
  clearWelcome();
  addBubble("user", message);
  input.value = "";
  setBusy(true);
  const typing = showTyping();
  try {
    const res = await fetch("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_token: getToken() }),
    });
    const data = await res.json().catch(() => ({}));
    typing.remove();
    if (res.status === 429) {
      addBubble("bot", data.detail || "This conversation is full. Please start a new chat.");
      setToken(null);
      showNotice("Conversation limit reached. Press \"New chat\" to continue.", true);
    } else if (!res.ok) {
      const detail = Array.isArray(data.detail) ? "Please check your question and try again." : data.detail;
      addBubble("bot", detail || "Sorry, something went wrong. Please try again.");
    } else {
      if (data.session && data.session.status === "restarted") {
        showNotice("Your previous chat expired, so this is a new conversation.");
      }
      setToken(data.session_token);
      addBubble("bot", data.answer, { interpreted: data.follow_up && data.follow_up.interpreted_as,
                                      messageId: data.message_id, rate: data.kind !== "small_talk" });
      renderSuggestions(data.suggestions);
    }
  } catch (err) {
    typing.remove();
    addBubble("bot", "I can't reach the server right now. Please check your connection and try again.");
  } finally {
    setBusy(false);
  }
}

async function loadHistory() {
  const token = getToken();
  if (!token) return false;
  try {
    const res = await fetch("/api/v1/chat/history", { headers: { "X-Session-Token": token } });
    const data = await res.json();
    if (!data.active || !data.messages.length) { setToken(null); return false; }
    data.messages.forEach((m) => addBubble(m.role, m.message));
    return true;
  } catch (err) {
    return false;
  }
}

async function newChat() {
  if (busy) return;
  const token = getToken();
  setToken(null);
  chatArea.textContent = "";
  showNotice("");
  showWelcome();
  input.focus();
  if (token) {            // best effort: delete the old conversation on the server
    fetch("/api/v1/chat/session", { method: "DELETE", headers: { "X-Session-Token": token } }).catch(() => {});
  }
}

async function checkHealth() {
  const line = document.getElementById("statusLine");
  try {
    const data = await (await fetch("/api/v1/health")).json();
    line.textContent = data.success ? "System status: online" : "System status: the database is unavailable.";
    line.className = "sg-status " + (data.success ? "ok" : "bad");
  } catch (err) {
    line.textContent = "System status: cannot reach the server.";
    line.className = "sg-status bad";
  }
}

form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
document.getElementById("newChatBtn").addEventListener("click", newChat);

(async () => {
  checkHealth();
  if (!(await loadHistory())) showWelcome();
  input.focus();
})();
