(function setupRecordingShare() {
  const dialog = document.createElement("dialog");
  dialog.className = "share-dialog";
  dialog.innerHTML = `
    <div class="share-dialog-card">
      <header>
        <div>
          <p class="eyebrow">Share recording</p>
          <h2>Choose where to share</h2>
        </div>
        <button type="button" class="dialog-close share-dialog-close" aria-label="Close share menu">×</button>
      </header>
      <div class="share-platforms">
        <a class="share-platform whatsapp" target="_blank" rel="noopener">WhatsApp</a>
        <a class="share-platform email">Email</a>
        <a class="share-platform facebook" target="_blank" rel="noopener">Facebook</a>
        <a class="share-platform linkedin" target="_blank" rel="noopener">LinkedIn</a>
        <button type="button" class="share-platform copy-link">Copy Link</button>
      </div>
      <p class="share-dialog-note">Anyone with access to this recording link can open the video.</p>
    </div>`;
  document.body.appendChild(dialog);

  const closeButton = dialog.querySelector(".share-dialog-close");
  const copyButton = dialog.querySelector(".copy-link");
  let currentUrl = "";

  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-share-url]");
    if (!trigger) return;
    event.preventDefault();
    if (!trigger.dataset.shareUrl) return;

    currentUrl = new URL(trigger.dataset.shareUrl, window.location.origin).href;
    const title = trigger.dataset.shareTitle || "AI interview recording";
    const message = `${title} — View the interview recording: ${currentUrl}`;

    dialog.querySelector(".whatsapp").href = `https://wa.me/?text=${encodeURIComponent(message)}`;
    dialog.querySelector(".email").href = `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(message)}`;
    dialog.querySelector(".facebook").href = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(currentUrl)}`;
    dialog.querySelector(".linkedin").href = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(currentUrl)}`;
    copyButton.textContent = "Copy Link";
    dialog.showModal();
  });

  closeButton.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", event => {
    event.preventDefault();
    dialog.close();
  });
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(currentUrl);
      copyButton.textContent = "Link Copied";
    } catch (error) {
      window.prompt("Copy this recording link:", currentUrl);
    }
  });
})();
