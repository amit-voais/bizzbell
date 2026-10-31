/* Bizzbell Version B motion: builds every animation from the JSON plan with the Web Animations API.
   HyperFrames' WAAPI adapter seeks each animation to composition time, so `start` is absolute seconds.
   No clocks, no randomness, no network, no requestAnimationFrame: every frame depends on its time only.
   Plan: {"anims": [{"sel": "#id", "kf": [{...}, {...}], "start": s, "dur": s, "ease": "css easing"}]} */
(function () {
  var plan = JSON.parse(document.getElementById("bb-plan").textContent);
  plan.anims.forEach(function (a) {
    var el = document.querySelector(a.sel);
    if (!el) { return; }
    var anim = el.animate(a.kf, {
      duration: Math.max(1, Math.round(a.dur * 1000)),
      delay: Math.round(a.start * 1000),
      easing: a.ease || "linear",
      fill: "both",
      iterations: 1
    });
    anim.pause();
  });
})();
