const exploreButton = document.querySelector("#explore-button");

exploreButton?.addEventListener("click", () => {
    document.querySelector("#foundation")?.scrollIntoView({ behavior: "smooth" });
});
