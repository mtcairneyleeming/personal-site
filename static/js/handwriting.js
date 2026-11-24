(() => {
    const script = document.currentScript;
    const toggle = document.querySelector(".handwriting-toggle");
    const passages = [...document.querySelectorAll("[data-ink][data-ink-words]")];
    if (!script || !toggle || !passages.length) return;

    const preference = "handwriting";
    // ?handwriting=debug draws the font and worksheet guides on each handwritten word.
    const debug = new URLSearchParams(location.search).get("handwriting") === "debug";
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

    // Guide lines at heights above the baseline. A zero-height inline-block sits on the
    // baseline, and the lines are positioned from its bottom edge.
    function guides(asset) {
        const ruler = document.createElement("span");
        ruler.className = "handwriting-guides";
        const heights = {
            baseline: "0ex", "font-x": "1ex", "font-cap": "1cap",
            "sheet-base": asset.guides.base, "sheet-x": asset.guides.x,
            "sheet-cap": asset.guides.cap, "sheet-bottom": -asset.guides.bottom,
        };
        for (const [kind, value] of Object.entries(heights)) {
            if (value === undefined) continue;
            const height = typeof value === "number" ? value + "ex" : value;
            const line = document.createElement("span");
            line.className = "handwriting-guide handwriting-guide-" + kind;
            line.style.bottom = height;
            line.style.inlineSize = asset.width + "ex";
            ruler.append(line);
        }
        return ruler;
    }

    function showLegend() {
        const legend = document.createElement("div");
        legend.className = "handwriting-debug-legend";
        legend.setAttribute("aria-hidden", "true");
        for (const [kind, label] of [
            ["font-cap", "Font cap height (1cap)"],
            ["font-x", "Font x-height (1ex)"],
            ["baseline", "Baseline"],
            ["sheet-cap", "Worksheet capital rule, as scaled"],
            ["sheet-x", "Worksheet dashed line, as scaled"],
            ["sheet-base", "Worksheet baseline, as scaled"],
            ["sheet-bottom", "Worksheet box bottom, as scaled"],
            ["image", "Word image"],
        ]) {
            const row = document.createElement("div");
            const swatch = document.createElement("span");
            swatch.className = "handwriting-swatch handwriting-guide-" + kind;
            row.append(swatch, label);
            legend.append(row);
        }
        document.body.append(legend);
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
                // Sizes are in ex, so the written x-height equals the font's.
                visual.style.inlineSize = asset.width + "ex";
                if (Number.isFinite(asset.height) && asset.height > 0) {
                    visual.style.blockSize = asset.height + "ex";
                }
                if (Number.isFinite(asset.descender) && asset.descender >= 0) {
                    visual.style.verticalAlign = -asset.descender + "ex";
                }
                visual.addEventListener("error", () => word.replaceWith(token), { once: true });
            }

            word.append(text, visual);
            // Before the image, so the lines start where the word does.
            if (debug && !demo && asset.guides) visual.before(guides(asset));
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
                passage.classList.toggle("handwriting-passage", enabled);
            }
        }

        toggle.querySelector(".handwriting-demo-badge").hidden = !demo;
        toggle.hidden = false;
        if (debug) {
            document.documentElement.classList.add("handwriting-debug");
            showLegend();
        }
        let enabled = debug || readPreference();
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
