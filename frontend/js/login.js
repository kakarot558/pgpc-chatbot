// Signs in through our own API. The token lives in sessionStorage (cleared when the tab closes).
document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("loginError");
  errorBox.textContent = "";
  const body = new URLSearchParams({
    username: document.getElementById("username").value,
    password: document.getElementById("password").value,
  });
  try {
    const res = await fetch("/api/v1/auth/login", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) {
      errorBox.textContent = data.detail || "Sign in failed.";
      return;
    }
    sessionStorage.setItem("pgpc_token", data.access_token);
    window.location.href = data.role === "admin" ? "admin.html" : "index.html";
  } catch (err) {
    errorBox.textContent = "Cannot reach the server.";
  }
});
