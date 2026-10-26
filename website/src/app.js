/* Browser-local interactions only. No analytics, requests to APIs or user data storage. */
(() => {
  document.documentElement.classList.add("js");
  const menu = document.querySelector(".menu-toggle");
  const navigation = document.querySelector("#navigation");
  menu.hidden = false;
  const closeMenu = () => {
    menu.setAttribute("aria-expanded", "false");
    navigation.dataset.open = "false";
  };
  menu.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    menu.setAttribute("aria-expanded", String(open));
    navigation.dataset.open = String(open);
  });
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) closeMenu();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!navigation.contains(event.target) && !menu.contains(event.target))
      closeMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      menu.getAttribute("aria-expanded") === "true"
    ) {
      closeMenu();
      menu.focus();
    }
  });

  const image = document.querySelector("#workspace-image");
  const panel = document.querySelector("#workspace-panel");
  const tabs = [...document.querySelectorAll("[data-screen]")];
  const screens = {
    chat: [
      "conversation.png",
      "Actual conversation interface with a local model and an example film-planning discussion",
      "Start with a conversation. Keep your ideas, files and results together.",
    ],
    create: [
      "library.png",
      "Actual Library interface with approved neutral demonstration images and a locally generated landscape film",
      "Make something. Keep the output, its settings and where it came from.",
    ],
    video: [
      "video.png",
      "Actual video workspace showing a completed locally generated landscape film",
      "From a scene to a short film, with inspectable progress and reusable results.",
    ],
    agents: [
      "agents.png",
      "Actual agents workspace with illustrative draft agent definitions",
      "Give recurring work a home. Draft an agent, review its permissions, then enable it.",
    ],
  };
  document.querySelector(".workspace-tabs").hidden = false;
  function selectTab(tab) {
    const [file, alt, caption] = screens[tab.dataset.screen];
    tabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
    });
    image.src = `assets/${file}`;
    image.alt = alt;
    panel.setAttribute("aria-labelledby", tab.id);
    document.querySelector("#screen-caption").textContent = caption;
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      const direction = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      let next;
      if (direction)
        next = tabs[(index + direction + tabs.length) % tabs.length];
      else if (event.key === "Home") next = tabs[0];
      else if (event.key === "End") next = tabs.at(-1);
      if (next) {
        event.preventDefault();
        next.focus();
        selectTab(next);
      }
    });
  });

  function bindDialog(dialog) {
    dialog.addEventListener("close", () =>
      document.body.classList.remove("modal-open"),
    );
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (
        event.clientX < box.left ||
        event.clientX > box.right ||
        event.clientY < box.top ||
        event.clientY > box.bottom
      )
        dialog.close();
    });
  }
  const tour = document.querySelector("#tour-dialog");
  const enlarged = document.querySelector("#screen-dialog");
  if (typeof tour.showModal === "function") {
    [tour, enlarged].forEach(bindDialog);
    document.querySelector("[data-tour]").addEventListener("click", (event) => {
      event.preventDefault();
      tour.showModal();
      document.body.classList.add("modal-open");
      tour
        .querySelector("video")
        .play()
        .catch(() => {
          // User-initiated playback can fall back to the native video controls.
        });
    });
    tour.addEventListener("close", () => tour.querySelector("video").pause());
    const expand = document.querySelector(".expand-screen");
    expand.hidden = false;
    expand.addEventListener("click", () => {
      const target = enlarged.querySelector("img");
      target.src = image.src;
      target.alt = image.alt;
      enlarged.showModal();
      document.body.classList.add("modal-open");
    });
  }

  const copy = document.querySelector(".copy-button");
  copy.hidden = false;
  copy.addEventListener("click", async () => {
    const code = document.querySelector("#install-code");
    const status = document.querySelector("#copy-status");
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code.textContent);
        copied = true;
      }
    } catch {
      /* Insecure contexts and denied permissions use the selection fallback. */
    }
    if (!copied) {
      const field = document.createElement("textarea");
      field.value = code.textContent;
      field.style.cssText = "position:fixed;left:-9999px;top:0";
      document.body.append(field);
      field.select();
      try {
        copied = document.execCommand("copy");
      } catch {
        /* Manual selection remains available. */
      }
      field.remove();
      copy.focus();
    }
    if (!copied) {
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
    status.textContent = copied
      ? "Commands copied. Follow the setup guide to configure your models."
      : "Commands selected. Copy the selection with your device’s copy command.";
  });
})();
