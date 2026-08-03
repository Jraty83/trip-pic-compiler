(() => {
  const imageEl = document.getElementById("image-slide");
  const videoEl = document.getElementById("video-slide");
  const dayEl = document.getElementById("day-label");
  const emptyEl = document.getElementById("empty");
  const counterEl = document.getElementById("counter");
  const clockEl = document.getElementById("clock");
  const barEl = document.getElementById("progress-bar");
  const btnPlay = document.getElementById("btn-play");
  const btnPrev = document.getElementById("btn-prev");
  const btnNext = document.getElementById("btn-next");

  let slides = [];
  let index = 0;
  let playing = false;
  let imageTimer = null;
  let imageStartedAt = 0;
  let imageDurationMs = 8000;

  function formatClock(totalSec) {
    const m = Math.floor(totalSec / 60);
    const s = Math.floor(totalSec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function clearImageTimer() {
    if (imageTimer) {
      clearTimeout(imageTimer);
      imageTimer = null;
    }
  }

  function showDayLabel(slide) {
    if (slide && slide.show_day_label && slide.day_label) {
      dayEl.hidden = false;
      dayEl.textContent = slide.day_label;
    } else {
      dayEl.hidden = true;
      dayEl.textContent = "";
    }
  }

  function updateChrome() {
    counterEl.textContent = slides.length
      ? `${index + 1} / ${slides.length}`
      : "0 / 0";
    const total = slides.reduce((acc, s) => acc + (s.duration_sec || 0), 0);
    const elapsed = slides
      .slice(0, index)
      .reduce((acc, s) => acc + (s.duration_sec || 0), 0);
    clockEl.textContent = slides.length
      ? `${formatClock(elapsed)} / ${formatClock(total)}`
      : "";
    btnPlay.textContent = playing ? "❚❚" : "▶";
  }

  function setProgress(ratio) {
    barEl.style.width = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
  }

  function goTo(nextIndex, autoplay) {
    if (!slides.length) return;
    clearImageTimer();
    videoEl.pause();
    videoEl.removeAttribute("src");
    videoEl.load();

    index = (nextIndex + slides.length) % slides.length;
    const slide = slides[index];
    showDayLabel(slide);
    setProgress(0);
    updateChrome();

    if (slide.kind === "video") {
      imageEl.hidden = true;
      videoEl.hidden = false;
      videoEl.src = slide.src;
      videoEl.onloadedmetadata = () => {
        if (playing || autoplay) {
          videoEl.play().catch(() => {
            playing = false;
            updateChrome();
          });
        }
      };
      videoEl.ontimeupdate = () => {
        if (videoEl.duration) setProgress(videoEl.currentTime / videoEl.duration);
      };
      videoEl.onended = () => {
        if (playing) goTo(index + 1, true);
      };
    } else {
      videoEl.hidden = true;
      imageEl.hidden = false;
      imageEl.src = slide.src;
      imageDurationMs = (slide.duration_sec || 8) * 1000;
      imageStartedAt = performance.now();
      if (playing || autoplay) {
        const tick = () => {
          const ratio = (performance.now() - imageStartedAt) / imageDurationMs;
          setProgress(ratio);
          if (ratio >= 1) {
            goTo(index + 1, true);
          } else {
            imageTimer = setTimeout(tick, 100);
          }
        };
        imageTimer = setTimeout(tick, 100);
      }
    }
  }

  function togglePlay() {
    if (!slides.length) return;
    playing = !playing;
    updateChrome();
    const slide = slides[index];
    if (!playing) {
      clearImageTimer();
      if (slide.kind === "video") videoEl.pause();
      return;
    }
    if (slide.kind === "video") {
      videoEl.play().catch(() => {
        playing = false;
        updateChrome();
      });
    } else {
      const remaining =
        imageDurationMs - (performance.now() - imageStartedAt);
      const resumeFrom = Math.max(0, remaining);
      imageStartedAt = performance.now() - (imageDurationMs - resumeFrom);
      const tick = () => {
        const ratio = (performance.now() - imageStartedAt) / imageDurationMs;
        setProgress(ratio);
        if (ratio >= 1) goTo(index + 1, true);
        else imageTimer = setTimeout(tick, 100);
      };
      imageTimer = setTimeout(tick, 100);
    }
  }

  btnPlay.addEventListener("click", togglePlay);
  btnPrev.addEventListener("click", () => {
    playing = false;
    goTo(index - 1, false);
  });
  btnNext.addEventListener("click", () => {
    const wasPlaying = playing;
    goTo(index + 1, wasPlaying);
  });

  window.addEventListener("keydown", (e) => {
    if (e.key === " ") {
      e.preventDefault();
      togglePlay();
    } else if (e.key === "ArrowRight") btnNext.click();
    else if (e.key === "ArrowLeft") btnPrev.click();
  });

  fetch("timeline.json")
    .then((r) => r.json())
    .then((data) => {
      slides = data.slides || [];
      if (!slides.length) {
        emptyEl.hidden = false;
        updateChrome();
        return;
      }
      goTo(0, false);
    })
    .catch(() => {
      emptyEl.hidden = false;
      emptyEl.textContent = "timeline.json puuttuu — aja pipeline.";
    });
})();
