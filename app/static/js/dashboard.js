const deleteForms = document.querySelectorAll("[data-portfolio-delete]");

for (const form of deleteForms) {
    form.addEventListener("submit", (event) => {
        if (!window.confirm("Delete this portfolio? This cannot be undone.")) {
            event.preventDefault();
        }
    });
}

// Auto-dismiss floating flash toast notifications after 4 seconds
document.querySelectorAll("[data-flash-toast]").forEach((toast) => {
    setTimeout(() => {
        toast.classList.add("flash-dismissed");
        setTimeout(() => toast.remove(), 350);
    }, 4000);
});

// Theme Toggle Handler
const themeToggleBtn = document.getElementById("theme-toggle-btn");
if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
        const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
        const nextTheme = currentTheme === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", nextTheme);
        localStorage.setItem("forge_theme", nextTheme);
    });
}

