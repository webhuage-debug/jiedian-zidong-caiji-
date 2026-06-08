const BASE_PATH = window.location.pathname.startsWith("/adminhuage") ? "/adminhuage" : "";
const $ = (id) => document.getElementById(id);

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = payload.error || payload.reason || "";
    } catch (error) {
      detail = "";
    }
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function login(event) {
  event.preventDefault();
  $("loginHint").textContent = "正在登录...";
  try {
    await jsonFetch(`${BASE_PATH}/api/login`, {
      method: "POST",
      body: JSON.stringify({
        username: $("loginUsername").value,
        password: $("loginPassword").value,
      }),
    });
    window.location.href = `${BASE_PATH}/`;
  } catch (error) {
    $("loginHint").textContent = error.message;
  }
}

$("loginForm").onsubmit = login;
