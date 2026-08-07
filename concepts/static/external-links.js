function applyExternalLinks() {
  document.querySelectorAll("a[href^='http']").forEach(function (link) {
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener noreferrer");
  });
}

document.addEventListener("DOMContentLoaded", applyExternalLinks);
document.addEventListener("nav", applyExternalLinks);
