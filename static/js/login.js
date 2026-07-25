(() => {
  const page = document.querySelector(".login-page");
  const context = document.querySelector(".login-context");
  const form = document.querySelector("#login-form");
  const passwordInput = document.querySelector("#id_password");
  const passwordToggle = document.querySelector(".password-toggle");
  const submitButton = document.querySelector(".submit-button");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let isSubmitting = false;

  if (!page || !form || !passwordInput || !passwordToggle || !submitButton) {
    return;
  }

  passwordToggle.addEventListener("click", () => {
    const willShowPassword = passwordInput.type === "password";
    passwordInput.type = willShowPassword ? "text" : "password";
    passwordToggle.textContent = willShowPassword ? "隐藏" : "显示";
    passwordToggle.setAttribute(
      "aria-label",
      passwordToggle.dataset[willShowPassword ? "hideLabel" : "showLabel"] || "",
    );
    passwordInput.focus({ preventScroll: true });
  });

  form.addEventListener("focusin", (event) => {
    if (event.target instanceof HTMLInputElement) {
      page.classList.add("is-input-active");
    }
  });

  form.addEventListener("focusout", () => {
    if (!form.contains(document.activeElement)) {
      page.classList.remove("is-input-active");
    }
  });

  form.addEventListener("submit", (event) => {
    if (!form.checkValidity()) {
      return;
    }
    if (isSubmitting) {
      event.preventDefault();
      return;
    }
    isSubmitting = true;
    page.classList.add("is-submitting");
    form.setAttribute("aria-busy", "true");
    submitButton.setAttribute("aria-disabled", "true");
  });

  window.addEventListener("pageshow", () => {
    isSubmitting = false;
    page.classList.remove("is-submitting");
    form.removeAttribute("aria-busy");
    submitButton.removeAttribute("aria-disabled");
  });

  if (!context || reducedMotion.matches) {
    return;
  }

  let animationFrame = 0;

  const setPointerPosition = (event) => {
    window.cancelAnimationFrame(animationFrame);
    animationFrame = window.requestAnimationFrame(() => {
      const bounds = context.getBoundingClientRect();
      const relativeX = (event.clientX - bounds.left) / bounds.width - 0.5;
      const relativeY = (event.clientY - bounds.top) / bounds.height - 0.5;

      page.style.setProperty("--pointer-x", `${relativeX * 11}px`);
      page.style.setProperty("--pointer-y", `${relativeY * 8}px`);
      page.style.setProperty("--pointer-x-reverse", `${relativeX * -5}px`);
      page.style.setProperty("--pointer-y-reverse", `${relativeY * -4}px`);
    });
  };

  const resetPointerPosition = () => {
    window.cancelAnimationFrame(animationFrame);
    page.style.setProperty("--pointer-x", "0px");
    page.style.setProperty("--pointer-y", "0px");
    page.style.setProperty("--pointer-x-reverse", "0px");
    page.style.setProperty("--pointer-y-reverse", "0px");
  };

  context.addEventListener("pointermove", setPointerPosition);
  context.addEventListener("pointerleave", resetPointerPosition);

  window.addEventListener(
    "pagehide",
    () => {
      window.cancelAnimationFrame(animationFrame);
      context.removeEventListener("pointermove", setPointerPosition);
      context.removeEventListener("pointerleave", resetPointerPosition);
    },
    { once: true },
  );
})();
