(() => {
    const script = document.currentScript;
    const toggle = document.querySelector(".handwriting-toggle");
    const passages = [...document.querySelectorAll("[data-ink][data-ink-words]")];
    if (!script || !toggle || !passages.length) return;

    const preference = "handwriting";
    const manifestURL = new URL(script.dataset.manifest, document.baseURI);

    function readPreference() {
        try {
            return localStorage.getItem(preference) === "on";
        } catch {
            return false;
        }
    }

    function savePreference(enabled) {
        try {
            localStorage.setItem(preference, enabled ? "on" : "off");
        } catch {
            // The button still works on the current page without storage.
        }
    }

    function decorate(passage, original, words, demo) {
        let index = 0;
        const decorated = document.createDocumentFragment();
        for (const token of original.split(/(\s+)/)) {
            if (!token) continue;
            if (/^\s+$/.test(token)) {
                decorated.append(token);
                continue;
            }

            const asset = words[index++];
            const word = document.createElement("span");
            word.className = "handwriting-word";

            const text = document.createElement("span");
            text.className = "handwriting-original";
            text.textContent = token;

            const visual = document.createElement(demo ? "span" : "img");
            visual.className = demo ? "handwriting-visual handwriting-demo" : "handwriting-visual";
            visual.setAttribute("aria-hidden", "true");
            if (demo) {
                visual.dataset.word = token;
            } else {
                visual.alt = "";
                visual.src = new URL(asset.src, manifestURL).href;
                visual.style.inlineSize = asset.width + "em";
                if (Number.isFinite(asset.height) && asset.height > 0) {
                    visual.style.blockSize = asset.height + "em";
                }
                if (Number.isFinite(asset.descender) && asset.descender >= 0) {
                    visual.style.verticalAlign = -asset.descender + "em";
                }
                visual.addEventListener("error", () => word.replaceWith(token), { once: true });
            }

            word.append(text, visual);
            decorated.append(word);
        }
        passage.replaceChildren(decorated);
    }

    async function initialize() {
        const response = await fetch(manifestURL);
        if (!response.ok) return;

        const {demo, entries} = await response.json();
        if (!entries || !Object.keys(entries).length) return;

        const matches = passages.flatMap(passage => {
            const entry = entries[passage.dataset.ink];
            const original = passage.textContent;
            const tokens = original.match(/\S+/g) || [];
            if (!Array.isArray(entry?.words)) return [];
            const [start, end] = passage.dataset.inkWords.split(":").map(Number);
            const words = entry.words.slice(start, end);
            if (words.length !== tokens.length ||
                words.some((word, i) => word.text !== tokens[i] ||
                    (!demo && (!word.src || !Number.isFinite(word.width) || word.width <= 0)))) {
                return [];
            }
            return [{passage, original, words}];
        });

        function apply(enabled) {
            toggle.setAttribute("aria-checked", String(enabled));
            for (const {passage, original, words} of matches) {
                if (enabled) {
                    decorate(passage, original, words, demo);
                } else {
                    passage.textContent = original;
                }
            }
        }

        toggle.querySelector(".handwriting-demo-badge").hidden = !demo;
        toggle.hidden = false;
        let enabled = readPreference();
        apply(enabled);
        toggle.addEventListener("click", () => {
            enabled = !enabled;
            apply(enabled);
            savePreference(enabled);
        });
    }

    initialize().catch(() => {
        // The original text stays visible if the manifest cannot be loaded.
    });
})();
