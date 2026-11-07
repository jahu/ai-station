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
      "Actual Chat with a completed local Qwen film-planning reply in the demo account",
      "Start with a conversation. Keep your ideas, files and results together.",
    ],
    create: [
      "library.png",
      "Actual demo Library with the generated presenter, emerald-blazer edit, studio image and two completed films",
      "Make something. Keep the output, its settings and where it came from.",
    ],
    video: [
      "video.png",
      "Actual Video workspace with the coastal source image, real motion prompt and completed eight-second film",
      "From a scene to a short film, with inspectable progress and reusable results.",
    ],
    agents: [
      "agents.png",
      "Actual Agents workspace showing a saved, paused daily market-research draft awaiting review",
      "Review a saved daily research draft. Its schedule and tools stay under your control.",
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

// Progressive enhancement: native audio controls remain usable without JavaScript.
(() => {
  const showcase = document.querySelector("#showcase");
  if (!showcase) return;
  const players = [...showcase.querySelectorAll("audio, video")];
  players.forEach((player) =>
    player.addEventListener("play", () => {
      players.forEach((other) => {
        if (other !== player) other.pause();
      });
    }),
  );
  showcase.querySelectorAll("[data-audio-sample]").forEach((card) => {
    const audio = card.querySelector("audio");
    const transport = card.querySelector(".voice-transport");
    const button = card.querySelector(".voice-toggle");
    const name = card.querySelector("h4").textContent;
    const sampleLabel = card.dataset.sampleLabel || `synthetic ${name} sample`;
    const action = card.querySelector(".voice-action");
    const progress = card.querySelector("progress, .music-seek");
    const time = card.querySelector(".voice-time");
    const error = card.querySelector(".voice-error");
    if (!audio || !transport || !button) return;
    const format = (seconds) =>
      `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
    const update = () => {
      const playing = !audio.paused && !audio.ended;
      card.classList.toggle("is-playing", playing);
      button.setAttribute("aria-pressed", String(playing));
      button.setAttribute(
        "aria-label",
        `${playing ? "Pause" : "Play"} ${sampleLabel}`,
      );
      action.textContent = playing
        ? "Now playing"
        : audio.ended
          ? "Play again"
          : audio.currentTime > 0
            ? "Continue listening"
            : "Listen to the sample";
      progress.value =
        Number.isFinite(audio.duration) && audio.duration > 0
          ? audio.currentTime / audio.duration
          : 0;
      if (progress.matches("input")) {
        progress.disabled =
          !Number.isFinite(audio.duration) || audio.duration <= 0;
        progress.style.setProperty("--played", `${progress.value * 100}%`);
      }
      time.textContent = format(
        playing || audio.currentTime > 0
          ? audio.currentTime
          : Number.isFinite(audio.duration)
            ? audio.duration
            : 0,
      );
    };
    ["play", "pause", "ended", "timeupdate", "loadedmetadata"].forEach(
      (event) => audio.addEventListener(event, update),
    );
    if (progress.matches("input"))
      progress.addEventListener("input", () => {
        if (Number.isFinite(audio.duration) && audio.duration > 0)
          audio.currentTime = Number(progress.value) * audio.duration;
      });
    button.addEventListener("click", async () => {
      error.textContent = "";
      if (!audio.paused) {
        audio.pause();
        return;
      }
      try {
        await audio.play();
      } catch {
        error.textContent =
          "Playback could not start. Try again or use the audio controls below.";
        audio.controls = true;
      }
    });
    const loadError = () => {
      error.textContent = "This sample could not load. Please try again.";
      audio.controls = true;
      update();
    };
    audio.addEventListener("error", loadError);
    // Failed <source> downloads do not bubble their error to <audio>.
    audio
      .querySelectorAll("source")
      .forEach((source) => source.addEventListener("error", loadError));
    transport.hidden = false;
    audio.controls = false;
    audio.preload = "metadata";
    update();
  });
})();
