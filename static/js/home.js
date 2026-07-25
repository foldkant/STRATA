(() => {
  const hero = document.querySelector(".hero");

  if (!hero || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  let animationFrame = 0;

  const setPointerPosition = (event) => {
    window.cancelAnimationFrame(animationFrame);
    animationFrame = window.requestAnimationFrame(() => {
      const bounds = hero.getBoundingClientRect();
      const relativeX = (event.clientX - bounds.left) / bounds.width - 0.5;
      const relativeY = (event.clientY - bounds.top) / bounds.height - 0.5;

      hero.style.setProperty("--pointer-x", `${relativeX * 11}px`);
      hero.style.setProperty("--pointer-y", `${relativeY * 8}px`);
      hero.style.setProperty("--pointer-x-reverse", `${relativeX * -5}px`);
      hero.style.setProperty("--pointer-y-reverse", `${relativeY * -4}px`);
    });
  };

  const resetPointerPosition = () => {
    window.cancelAnimationFrame(animationFrame);
    hero.style.setProperty("--pointer-x", "0px");
    hero.style.setProperty("--pointer-y", "0px");
    hero.style.setProperty("--pointer-x-reverse", "0px");
    hero.style.setProperty("--pointer-y-reverse", "0px");
  };

  hero.addEventListener("pointermove", setPointerPosition);
  hero.addEventListener("pointerleave", resetPointerPosition);

  window.addEventListener(
    "pagehide",
    () => {
      window.cancelAnimationFrame(animationFrame);
      hero.removeEventListener("pointermove", setPointerPosition);
      hero.removeEventListener("pointerleave", resetPointerPosition);
    },
    { once: true },
  );
})();
