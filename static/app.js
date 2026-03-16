// ================= FORM + REAL-TIME PROGRESS =================
(function () {
  const form = document.getElementById("compare-form");
  const img1 = document.getElementById("image1");
  const img2 = document.getElementById("image2");
  const msg = document.getElementById("msg");
  const loading = document.getElementById("loading");
  const serverLog = document.getElementById("server-log");

  if (!form) return;

  let eventSource = null;

  function show(text, type) {
    if (!msg) return;
    msg.textContent = text || "";
    msg.style.padding = "10px";
    msg.style.borderRadius = "8px";
    msg.style.margin = "10px 0";
    msg.style.border =
      type === "error" ? "1px solid #ff4d4f" : "1px solid #34c759";
    msg.style.background =
      type === "error" ? "#ffecec" : "#e6ffed";

    if (type === "error") {
      alert(text || "Invalid input.");
    }
  }

  function startProgressStream() {
    if (!serverLog) return;

    serverLog.innerHTML = "";
    serverLog.style.display = "block";

    if (eventSource) eventSource.close();

    eventSource = new EventSource("/progress");

    eventSource.onmessage = function (event) {
      if (event.data === "__DONE__") {
        eventSource.close();
        eventSource = null;
        if (loading) loading.style.display = "none";
        return;
      }

      const div = document.createElement("div");
      div.textContent = event.data;
      serverLog.appendChild(div);
      serverLog.scrollTop = serverLog.scrollHeight;
    };

    eventSource.onerror = function () {
      if (eventSource) eventSource.close();
      eventSource = null;
    };
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();

    const f1 = img1?.files?.[0];
    const f2 = img2?.files?.[0];

    if (!f1 || !f2) {
      show("Please choose two images.", "error");
      return;
    }

    if (!f1.type.startsWith("image/") || !f2.type.startsWith("image/")) {
      show("Files must be images (JPG/PNG).", "error");
      return;
    }

    startProgressStream(); // 🔥 START SSE FIRST

    if (loading) loading.style.display = "block";

    const formData = new FormData(form);

    try {
      const response = await fetch("/", {
        method: "POST",
        body: formData
      });

      const html = await response.text();

      // 🔹 minimal fix: replace body with result HTML
      document.body.innerHTML = html;

// 🔥 reattach theme switcher after DOM replacement
if (window.initThemeSwitcher) {
  window.initThemeSwitcher();
}


    } catch (err) {
      show("Server error. Please try again.", "error");
      if (loading) loading.style.display = "none";
    }
  });
})();


// ================= THEME SWITCHER =================
window.initThemeSwitcher = function () {
  const themeSwitch = document.getElementById("themeSwitch");
  const savedTheme = localStorage.getItem("theme");

  // Apply theme immediately
  if (savedTheme === "dark") {
    document.body.classList.add("dark");
  } else {
    document.body.classList.remove("dark");
  }

  if (!themeSwitch) return;

  themeSwitch.checked = savedTheme === "dark";

  themeSwitch.onchange = () => {
    if (themeSwitch.checked) {
      document.body.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.body.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  };
};

document.addEventListener("DOMContentLoaded", initThemeSwitcher);
