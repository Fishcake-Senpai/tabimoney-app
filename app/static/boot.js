/* Preferências de interface aplicadas antes da primeira pintura (carregado no <head>, sem defer), para a tela
   não piscar: modo discreto, menu recolhido e tema. Ficam no localStorage deste navegador; sem ele, vale o padrão. */
(function () {
  "use strict";
  var root = document.documentElement;
  var get = function (key, store) { try { return (store || localStorage).getItem("tabimoney." + key); } catch (e) { return null; } };
  // "Abrir sempre discreto" (Configurações › Aparência): começa borrado; desligar no olho vale só até fechar a aba.
  var session = null;
  try { session = sessionStorage; } catch (e) { session = null; }
  var discreet = root.dataset.discretoPadrao === "1" ? get("discreto", session) !== "0" : get("discreto") === "1";
  if (discreet) root.setAttribute("data-discreto", "");
  if (get("menu") === "mini") root.setAttribute("data-nav", "mini");
  var theme = root.dataset.temaPadrao || "escuro";
  if (theme === "sistema") theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "escuro";
  root.setAttribute("data-theme", theme === "claro" ? "light" : "dark");
})();
