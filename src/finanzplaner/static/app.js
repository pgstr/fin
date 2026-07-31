(() => {
  "use strict";

  // Theme. The initial value is applied by theme.js before first paint; this
  // only handles switching it afterwards and keeping the controls in sync.
  const applyTheme = (theme) => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("fin-theme", theme);
    } catch (error) {
      /* storage unavailable — the theme still applies for this page view */
    }
    document.querySelectorAll("[data-theme-option]").forEach((option) => {
      option.checked = option.value === theme;
    });
  };

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme");
      applyTheme(current === "light" ? "dark" : "light");
    });
  });

  document.querySelectorAll("[data-theme-option]").forEach((option) => {
    option.checked =
      option.value === document.documentElement.getAttribute("data-theme");
    option.addEventListener("change", () => {
      if (option.checked) applyTheme(option.value);
    });
  });

  document.querySelectorAll("[data-account-selector]").forEach((select) => {
    select.addEventListener("change", () => {
      if (select.value.startsWith("/")) window.location.assign(select.value);
    });
  });

  document.querySelectorAll("[data-auto-submit]").forEach((input) => {
    input.addEventListener("change", () => input.form?.requestSubmit());
  });

  document.querySelectorAll("[data-print]").forEach((button) => {
    button.addEventListener("click", () => window.print());
  });

  document.querySelectorAll("[data-balance-chart]").forEach((chart) => {
    const tooltip = chart.querySelector("[data-chart-tooltip]");
    if (!tooltip) return;

    const showTooltip = (point, clientX, clientY) => {
      const chartRect = chart.getBoundingClientRect();
      const pointRect = point.getBoundingClientRect();
      const x = clientX ?? pointRect.left + pointRect.width / 2;
      const y = clientY ?? pointRect.top;
      tooltip.textContent = point.dataset.tooltip ?? "";
      tooltip.hidden = false;
      const halfWidth = tooltip.offsetWidth / 2;
      const left = Math.min(
        Math.max(x - chartRect.left, halfWidth + 4),
        chartRect.width - halfWidth - 4,
      );
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(y - chartRect.top - 8, tooltip.offsetHeight + 4)}px`;
    };

    chart.querySelectorAll("[data-chart-point]").forEach((point) => {
      point.addEventListener("pointerenter", (event) => {
        showTooltip(point, event.clientX, event.clientY);
      });
      point.addEventListener("pointermove", (event) => {
        showTooltip(point, event.clientX, event.clientY);
      });
      point.addEventListener("pointerleave", () => {
        tooltip.hidden = true;
      });
      point.addEventListener("focus", () => showTooltip(point));
      point.addEventListener("blur", () => {
        tooltip.hidden = true;
      });
    });
  });
})();
